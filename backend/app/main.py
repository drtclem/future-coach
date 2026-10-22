"""FastAPI entry point. Slice 1 exposes the graph and the deterministic safety
filter; the generator and copilot routes land in later slices."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pyoxigraph import RdfFormat, Triple, serialize

from .copilot.copilot import ask
from .copilot.tools import Toolbox
from .graph.ns import BASE, FC
from .graph.store import domain_graph
from .member.graphview import member_graph
from .member.intake import record_checkin, record_message
from .member.model import member_repo
from .member.signals import churn, completed_weeks, journey, readiness
from .observability import attach_feedback
from .plan.generate import generate, generate_stream, replan_if_needed
from .plan.prov import KG_PROV, PROV
from .resolver.resolver import Resolver
from .safety.filter import Constraints, Injury, InjuryRule, SafetyFilter

app = FastAPI(title="Future Coach", version="0.1.0")


@app.on_event("startup")
def _warm_embeddings() -> None:
    """Load the resolver's embedding model and label vectors off the request path (about 2-3 s once)."""
    threading.Thread(target=lambda: member_repo().resolver.index.ranked("warm", {"muscle"}), daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    g = domain_graph()
    return {"status": "ok", "triples": len(g.store)}


@app.get("/api/kg/normalization")
def normalization() -> list[dict]:
    """Every data-quality fix made at ingestion (D5.1)."""
    return domain_graph().normalization_log


class InjuryIn(BaseModel):
    id: str
    label: str
    structure: str
    status: str
    condition: str = "unspecified-complaint"
    side: str | None = None
    extra_rules: list[dict] = []


class ConstraintsIn(BaseModel):
    injuries: list[InjuryIn] = []
    equipment: list[str] | None = None
    excluded_families: list[str] = []
    excluded_patterns: list[str] = []
    excluded_equipment: list[str] = []


@app.post("/api/safety/evaluate")
def evaluate(body: ConstraintsIn) -> list[dict]:
    c = Constraints(
        injuries=[
            Injury(**{**i.model_dump(), "extra_rules": tuple(InjuryRule(**r) for r in i.extra_rules)}) for i in body.injuries
        ],
        equipment=body.equipment,
        excluded_families=set(body.excluded_families),
        excluded_patterns=set(body.excluded_patterns),
        excluded_equipment=set(body.excluded_equipment),
    )
    return [asdict(d) for d in SafetyFilter(domain_graph()).evaluate(c).values()]


class ResolveIn(BaseModel):
    prompt: str


@app.post("/api/resolve")
def resolve(body: ResolveIn) -> dict:
    """Show how a coach prompt maps onto graph concepts (D8): mention, concept, role, match pass, confidence."""
    r = Resolver(domain_graph())
    res = r.resolve(body.prompt)
    c, notes = r.constraints(res)
    return {
        "mentions": [asdict(m) for m in res.mentions],
        "time_min": res.time_min,
        "blocking": res.blocking,
        "notes": res.notes + notes,
        "constraints": asdict(c),
    }


def _member(key: str):
    try:
        return member_repo().get(key)
    except KeyError:
        raise HTTPException(404, f"unknown member '{key}'") from None


@app.get("/api/members")
def members() -> list[dict]:
    return [
        {"key": k, "name": m.name, "pronouns": m.data["profile"].get("pronouns"), "as_of": m.as_of.isoformat()}
        for k, m in member_repo().members.items()
    ]


@app.get("/api/members/{key}/graph")
def member_graph_view(key: str) -> dict:
    """The member's KG2 neighbourhood and the KG1 concepts it links to (read by SPARQL)."""
    _member(key)
    return member_graph(domain_graph(), key)


@app.get("/api/members/{key}/messages")
def message_history(key: str) -> list[dict]:
    """Coach-member chat, oldest first. Image attachments point at a synthetic file named <member>-<date>.svg."""
    m = _member(key)
    out = []
    for c in m.messages():
        atts = [
            dict(a, src=f"/media/{key}-{c['ts'][:10]}.svg") if a.get("type") == "image" else a for a in c.get("attachments", [])
        ]
        out.append({**c, "attachments": atts})
    return out


@app.get("/api/prov/{request_id}", response_class=PlainTextResponse)
def provenance(request_id: str) -> str:
    """The W3C PROV-O record of one plan, as Turtle, read back from the graph store."""
    root = f"{BASE}/prov/{request_id}"
    triples = [
        Triple(q.subject, q.predicate, q.object)
        for q in domain_graph().store.quads_for_pattern(None, None, None, KG_PROV)
        if q.subject.value.startswith(root + "/")
    ]
    if not triples:
        raise HTTPException(404, "no provenance for that request")
    prefixes = {"prov": PROV, "fc": FC, "fcx": f"{BASE}/exercise/", "run": root + "/", "xsd": "http://www.w3.org/2001/XMLSchema#"}
    return serialize(triples, format=RdfFormat.TURTLE, prefixes=prefixes).decode()


@app.get("/api/members/{key}")
def member(key: str) -> dict:
    """Member summary with the computed signals (D5.3, D11) and the evidence behind each."""
    m = _member(key)
    stages, stage_ev = journey(m)
    done, cur = completed_weeks(m)
    return {
        "profile": m.data["profile"],
        "goals": m.data.get("goals", []),
        "preferences": m.data.get("preferences", {}),
        "equipment_available": m.data.get("equipment_available", []),
        "injuries": [dict(asdict(i), how_read=m.injury_notes.get(i.id, [])) for i in m.injuries],
        "readiness": asdict(readiness(m)),
        "journey": {"stages": stages, "evidence": [asdict(e) for e in stage_ev]},
        "adherence": {"completed_weeks": done, "current_week": cur},
        "churn": churn(m),
        "sleep": (Toolbox(m).get_sleep(14).charts or [None])[0],  # same series the copilot charts, for the member card
    }


class CheckinIn(BaseModel):
    sleep_hours: float | None = None
    energy: int | None = None
    soreness: int | None = None
    stress: int | None = None
    pain: dict | None = None
    time_available_min: int | None = None
    equipment_today: list[str] | None = None
    note: str | None = None


_replans: dict[
    str, dict
] = {}  # latest background re-plan per member; shortcut: in-process, move to the event log if we run >1 worker


def _replan_later(key: str, reason: str, tasks: BackgroundTasks) -> dict | None:
    """Reply to the member at once; re-plan (8-20 s with the LLM) after the response is sent."""
    m = member_repo().get(key)
    if not any(p["as_of"] == m.as_of.isoformat() for p in m.data.get("plans", [])):
        return None
    _replans[key] = {"status": "pending", "reason": reason}
    tasks.add_task(lambda: _replans.__setitem__(key, {"status": "done", **(replan_if_needed(key, reason) or {})}))
    return _replans[key]


@app.get("/api/members/{key}/replan")
def replan_status(key: str) -> dict | None:
    return _replans.get(key)


@app.post("/api/members/{key}/checkins")
def checkin(key: str, body: CheckinIn, tasks: BackgroundTasks, source: str = "self-report") -> dict:
    out = record_checkin(member_repo(), _member(key), body.model_dump(), source=source)
    out["replan"] = _replan_later(key, "check-in", tasks) if out["flags"] else None
    return {**out, "readiness": asdict(out["readiness"])}


class MessageIn(BaseModel):
    text: str


@app.post("/api/members/{key}/messages")
def message(key: str, body: MessageIn, tasks: BackgroundTasks) -> dict:
    out = record_message(member_repo(), _member(key), body.text)
    if "readiness" in out:
        out["readiness"] = asdict(out["readiness"])
        out["replan"] = _replan_later(key, f"member message: {', '.join(out['extracted'])}", tasks)  # D13
    return out


class GenerateIn(BaseModel):
    prompt: str
    time_min: int | None = None


@app.post("/api/members/{key}/generate")
def generate_plan(key: str, body: GenerateIn) -> dict:
    _member(key)
    return generate(key, body.prompt, time_min=body.time_min)


@app.post("/api/members/{key}/generate/stream")
def generate_plan_stream(key: str, body: GenerateIn) -> StreamingResponse:
    """Server-sent events: a quick, already-validated draft within ~2 s, then the composer's plan."""
    _member(key)
    events = (f"data: {json.dumps(e)}\n\n" for e in generate_stream(key, body.prompt, time_min=body.time_min))
    return StreamingResponse(events, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class FeedbackIn(BaseModel):
    request_id: str
    rating: str  # up | down
    comment: str | None = None


@app.post("/api/feedback")
def feedback(body: FeedbackIn) -> dict:
    return {"attached_to_langfuse": attach_feedback(body.request_id, body.rating, body.comment)}


@app.post("/api/demo/reset")
def reset() -> dict:
    """Drop runtime check-ins/messages and rebuild from the seed data."""
    member_repo().reset()
    _replans.clear()
    return {"status": "reset"}


class AskIn(BaseModel):
    question: str


@app.post("/api/members/{key}/copilot")
def copilot(key: str, body: AskIn) -> dict:
    _member(key)
    return ask(key, body.question)


# Serve the built dashboard (frontend/dist) from the same process: one command to run.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="dashboard")
