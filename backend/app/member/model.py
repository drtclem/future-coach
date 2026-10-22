"""Member knowledge graph (KG2): members, injuries, observations, workouts, messages.

Each member's JSON (data/members/) is the seed. Runtime inputs -- check-ins and
async messages (D12, D13) -- are appended to an event log (var/events.jsonl)
and replayed on startup, so nothing is overwritten and every value keeps its
source and timestamp. Every fact gets a stable node id that the copilot cites.

The bridge to KG1 is a single edge per injury: injury --instance-of--> Condition,
plus injury --at--> Structure (D2). Care-team notes are read into member-specific
rules through the load-type labels in the graph.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from pyoxigraph import Literal, NamedNode, Quad

from ..graph.ns import BASE, FC, FCA, FCC, FCE, FCL, RDF_TYPE, SKOS, local, slug
from ..graph.store import REPO, DomainGraph, domain_graph
from ..plan import prov
from ..resolver.resolver import Resolver, _norm_tokens
from ..safety.filter import Injury, InjuryRule

MEMBERS_DIR = REPO / "data" / "members"
EVENTS = Path(os.getenv("FC_EVENTS_PATH", str(REPO / "var" / "events.jsonl")))
KG2 = NamedNode(BASE + "/graph/member")
MEM = BASE + "/member/"


@dataclass
class Member:
    key: str  # file stem, e.g. "jordan"
    data: dict
    injuries: list[Injury] = field(default_factory=list)
    injury_notes: dict[str, list[str]] = field(default_factory=dict)  # injury id -> trace notes

    @property
    def id(self) -> str:
        return self.data["profile"]["id"]

    @property
    def name(self) -> str:
        return self.data["profile"]["name"]

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.data.get("as_of") or self.data["coach_brief"]["generated_for"])

    def node(self, kind: str, key: str) -> str:
        """Stable citation id, e.g. member/jordan/workout/2026-06-03."""
        return f"member/{self.key}/{kind}/{key}"

    def checkins(self) -> list[dict]:
        return sorted(self.data.get("checkins", []), key=lambda c: c["ts"])

    def messages(self) -> list[dict]:
        return sorted(self.data.get("chat_history", []), key=lambda c: c["ts"])


def _iri(path: str) -> NamedNode:
    return NamedNode(BASE + "/" + path)


def read_care_team_rules(g: DomainGraph, note: str, source: str) -> tuple[list[InjuryRule], list[str]]:
    """'avoid deep knee flexion under load and plyometrics' -> two exclude rules;
    'progress overhead pressing gradually' -> a downrank rule. Matching is on the
    load-type labels stored in KG1, longest label first."""
    labels = sorted(
        (
            (tuple(_norm_tokens(r["l"].value)), local(r["lt"].value))
            for r in g.query("SELECT ?lt ?l WHERE { ?lt fc:demand ?d . VALUES ?k { skos:prefLabel skos:altLabel } ?lt ?k ?l }")
        ),
        key=lambda x: -len(x[0]),
    )
    rules: list[InjuryRule] = []
    notes: list[str] = []
    for sentence in re.split(r"[.;]", note):
        toks = _norm_tokens(sentence)
        tier = (
            "exclude" if "avoid" in toks else "downrank" if any(t in toks for t in ("progress", "gradually", "limit")) else None
        )
        if not tier:
            continue
        text = " " + " ".join(toks) + " "
        seen = set()
        for lt_toks, lt in labels:
            phrase = " " + " ".join(lt_toks) + " "
            if phrase in text and lt not in seen:
                seen.add(lt)
                text = text.replace(phrase, " _ ")
                rules.append(InjuryRule(lt, tier, source))
                notes.append(f"care-team note: '{sentence.strip()}' -> {tier} {lt}")
    return rules, notes


def build_injuries(g: DomainGraph, resolver: Resolver, m: Member) -> None:
    for inj in m.data.get("injuries", []):
        notes = []
        res = resolver.resolve(f"{inj.get('notes', '')} {inj.get('region', '')} injury")
        cond = next((x for x in res.of("constraint", "condition")), None)
        structure = slug(inj.get("joint") or inj["region"])
        condition = "unspecified-complaint"
        if cond:
            condition = cond.concept.removeprefix(FCC)
            structure = resolver.affects[cond.concept].removeprefix(FCA)
            notes.append(f"'{cond.text}' in the injury note -> condition {condition} (instance-of)")
        else:
            notes.append("no diagnosis in the note -> unspecified complaint, stage defaults apply")
        rules, rnotes = read_care_team_rules(g, inj.get("notes", ""), f"care-team note {inj['id']} ({m.key}.json)")
        side = next((s for s in ("left", "right") if s in inj["region"].lower()), None)
        m.injuries.append(
            Injury(
                id=inj["id"],
                label=f"{inj['region']} ({condition.replace('-', ' ')})",
                structure=structure,
                status=inj["status"],
                condition=condition,
                side=side,
                extra_rules=tuple(rules),
            )
        )
        m.injury_notes[inj["id"]] = notes + rnotes


def materialize(g: DomainGraph, m: Member) -> None:
    """Write the member graph into the store (named graph KG2)."""

    def add(s, p, o):
        g.store.add(Quad(_iri(s) if isinstance(s, str) else s, NamedNode(p), o, KG2))

    me = _iri(f"member/{m.key}")
    add(me, RDF_TYPE, NamedNode(FC + "Member"))
    add(me, SKOS + "prefLabel", Literal(m.name))
    for inj in m.injuries:
        node = m.node("injury", inj.id)
        add(node, RDF_TYPE, NamedNode(FC + "Injury"))
        add(node, FC + "instanceOf", NamedNode(FCC + inj.condition))
        add(node, FC + "at", NamedNode(FCA + inj.structure))
        add(node, FC + "status", Literal(inj.status))
        if inj.side:
            add(node, FC + "laterality", NamedNode(FC + inj.side.capitalize()))
        for r in inj.extra_rules:
            add(node, FC + "memberRule", Literal(f"{r.tier}:{r.load_type}"))
            add(node, FC + "memberRuleLoad", NamedNode(FCL + r.load_type))
        g.store.add(Quad(me, NamedNode(FC + "hasInjury"), _iri(node), KG2))
    for goal in m.data.get("goals", []):
        node = m.node("goal", goal["id"])
        add(node, RDF_TYPE, NamedNode(FC + "Goal"))
        add(node, SKOS + "prefLabel", Literal(goal["text"]))
        g.store.add(Quad(me, NamedNode(FC + "hasGoal"), _iri(node), KG2))
    for label in m.data.get("equipment_available", []):  # links KG2 to KG1 equipment nodes
        add(me, FC + "hasEquipment", NamedNode(FCE + slug(label)))
    for w in m.data.get("workout_history", []):
        node = m.node("workout", w["date"])
        add(node, RDF_TYPE, NamedNode(FC + "WorkoutSession"))
        add(node, FC + "date", Literal(w["date"]))
        add(node, FC + "completed", Literal(str(w.get("completed"))))
        g.store.add(Quad(me, NamedNode(FC + "hasWorkout"), _iri(node), KG2))
    for c in m.messages():
        node = m.node("message", c["ts"])
        add(node, RDF_TYPE, NamedNode(FC + "Message"))
        add(node, FC + "author", Literal(c["from"]))
        add(node, FC + "text", Literal(c["text"]))
        g.store.add(Quad(me, NamedNode(FC + "hasMessage"), _iri(node), KG2))


class MemberRepo:
    def __init__(self, g: DomainGraph, events: Path = EVENTS):
        self.g = g
        self.resolver = Resolver(g)
        self.events = events
        self.members: dict[str, Member] = {}
        for f in sorted(MEMBERS_DIR.glob("*.json")):
            m = Member(f.stem, json.loads(f.read_text()))
            build_injuries(g, self.resolver, m)
            self.members[m.key] = m
        if events.exists():
            for line in events.read_text().splitlines():
                self._apply(json.loads(line))
        for m in self.members.values():
            materialize(g, m)

    def get(self, key: str) -> Member:
        if key not in self.members:
            raise KeyError(key)
        return self.members[key]

    def append(self, event: dict) -> None:
        """Record a check-in or message. Append-only; nothing is overwritten (D12)."""
        event.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
        self._apply(event)
        self.events.parent.mkdir(parents=True, exist_ok=True)
        with self.events.open("a") as fh:
            fh.write(json.dumps(event) + "\n")

    def _apply(self, e: dict) -> None:
        m = self.members.get(e["member"])
        if not m:
            return
        if e["type"] == "checkin":
            m.data.setdefault("checkins", []).append(e["payload"])
        elif e["type"] == "message":
            m.data.setdefault("chat_history", []).append(e["payload"])
        elif e["type"] == "plan":
            m.data.setdefault("plans", []).append(e["payload"])
            prov.record(self.g.store, m.key, e["payload"])

    def reset(self) -> None:
        """'Reset demo data': drop runtime events and rebuild from the seed files."""
        if self.events.exists():
            self.events.unlink()
        self.g.store.clear_graph(prov.KG_PROV)
        member_repo.cache_clear()


@lru_cache(maxsize=1)
def member_repo() -> MemberRepo:
    return MemberRepo(domain_graph())
