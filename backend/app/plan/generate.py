"""Workout generation pipeline (D8-D14). Fixed order, every step deterministic
except the optional LLM extraction and composition, which are fenced in by the
resolver union rules and the validator:

  route -> resolve (rules || LLM) -> constraints -> safety filter -> score
        -> compose (LLM, or deterministic builder) -> validate -> provenance
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from statistics import mean

from ..graph.ns import local
from ..graph.store import domain_graph
from ..llm import available as llm_available
from ..member.model import Member, MemberRepo, member_repo
from ..member.signals import journey, readiness
from ..observability import start_request
from ..resolver import llm_extract
from ..resolver.resolver import Resolver
from ..router import route
from ..safety.filter import SafetyFilter
from .builder import build, substitutes
from .candidates import score
from .catalog import catalog
from .compose import compose
from .pathgraph import path_graph
from .validate import validate


def default_budget(m: Member) -> tuple[int, str]:
    """D5.6: recent actual session length, preference shown alongside."""
    durs = [w["duration_min"] for w in sorted(m.data.get("workout_history", []), key=lambda w: w["date"]) if w.get("completed")][
        -4:
    ]
    pref = m.data.get("preferences", {}).get("preferred_session_minutes")
    if durs:
        mins = max(15, int(5 * round(mean(durs) / 5)))
        return mins, f"default {mins} min = her recent sessions (avg {mean(durs):.0f} min); preferred is {pref} min"
    return pref or 45, f"default {pref or 45} min = preferred session length"


def _dislike_ids(resolver: Resolver, sf: SafetyFilter, m: Member) -> set[str]:
    ids: set[str] = set()
    for d in m.data.get("preferences", {}).get("dislikes", []):
        res = resolver.resolve(f"no {d}")
        for x in res.of("exclusion", "family"):
            ids |= {local(i) for i in sf.members_of(local(x.concept))}
        for x in res.of("exclusion", "pattern"):
            ids |= {local(i) for i in sf.with_pattern(local(x.concept))}
    return ids


def generate(
    member_key: str, prompt: str, time_min: int | None = None, repo: MemberRepo | None = None, replan_reason: str | None = None
) -> dict:
    """The final plan (or the questions that block it)."""
    *_, final = generate_stream(member_key, prompt, time_min, repo, replan_reason)
    return final


def generate_stream(
    member_key: str, prompt: str, time_min: int | None = None, repo: MemberRepo | None = None, replan_reason: str | None = None
) -> Iterator[dict]:
    """Yields a quick draft plan as soon as the safe candidates are scored, then the final plan.

    The draft is the deterministic builder's plan through the same validator, so it is as safe as the
    final one; it is only sent when a composer model will run, because otherwise the two would be identical.
    """
    repo = repo or member_repo()
    m = repo.get(member_key)
    g = domain_graph()
    trace = start_request("generate", member=member_key, prompt_length=len(prompt), replan=bool(replan_reason))
    resolver, sf, cat = Resolver(g), SafetyFilter(g), catalog()

    fut = llm_extract.start(prompt, trace)
    r = readiness(m)
    injuries = [replace(i, status="acute") if i.id in r.acute_today else i for i in m.injuries]
    with trace.stage("extract_llm"):
        llm = llm_extract.collect(fut, trace)
    rt = route(prompt, llm)
    trace.event("routed", intent=rt.intent, confidence=rt.confidence, source=rt.source)
    with trace.stage("resolve") as st:
        res = resolver.resolve(prompt, known_injuries=injuries, llm_mentions=(llm or {}).get("mentions"))
        st.update(
            mentions=len(res.mentions),
            passes=dict(Counter(x.pass_ for x in res.mentions)),
            extractors=dict(Counter(x.extractor for x in res.mentions)),
        )
    if res.blocking:
        out = trace.finish(blocking=len(res.blocking), builder=None, exercise_count=0)  # counts only: questions quote the coach
        yield {"status": "needs_confirmation", "questions": res.blocking, "resolution": _res_view(res), "trace": out}
        return

    today = [c for c in m.checkins() if c["ts"][:10] == m.as_of.isoformat()]
    checkin_equipment = next((c["equipment_today"] for c in reversed(today) if c.get("equipment_today")), None)
    checkin_time = next((c["time_available_min"] for c in reversed(today) if c.get("time_available_min")), None)
    profile_equipment = checkin_equipment or m.data.get("equipment_available", [])
    with trace.stage("constraints"):
        c, notes = resolver.constraints(res, profile_equipment=profile_equipment)
        if checkin_equipment and not res.equipment_only:
            notes.append("equipment from today's check-in (overrides profile for this plan)")
    budget, budget_note = (
        (time_min, "time window from the request form")
        if time_min
        else (res.time_min, "time window from the request")
        if res.time_min
        else (checkin_time, "time available from today's check-in")
        if checkin_time
        else default_budget(m)
    )
    stages, _ = journey(m)
    with trace.stage("safety_filter") as st:
        decisions = sf.evaluate(c)
        st.update(
            excluded=sum(d.tier == "exclude" for d in decisions.values()),
            downranked=sum(d.tier == "downrank" for d in decisions.values()),
        )
    with trace.stage("score"):
        cands = score(cat, decisions, res, m, stages, _dislike_ids(resolver, sf, m))
    context = (
        [budget_note, f"readiness {r.level}: " + "; ".join(e.text for e in r.evidence)]
        + notes
        + [f"injury {i.label}: {i.status}" for i in c.injuries]
    )
    excluded = [d for d in decisions.values() if d.tier == "exclude"]

    def assemble(plan, repairs: list[str], builder_note: str, trace_out: dict) -> dict:
        prov = {
            "activities": [
                {
                    "id": "resolve",
                    "type": "prov:Activity",
                    "used": "coach prompt",
                    "generated": [_mention(x) for x in res.mentions],
                },
                {
                    "id": "safety_filter",
                    "type": "prov:Activity",
                    "used": [i.id for i in c.injuries] + ["equipment", "exclusions"],
                    "generated_excluded": [{"exercise": d.name, "reason": _main_reason(d)} for d in excluded],
                },
                {"id": "compose", "type": "prov:Activity", "agent": plan.builder, "note": builder_note},
                {"id": "validate", "type": "prov:Activity", "repairs": repairs},
            ],
            "summary": _summary(excluded, decisions, notes, budget_note, r, stages, plan),
        }
        subs = {name: substitutes(cat, cat.lookup(name).id, cands) for name in _requested_or_familiar_excluded(m, cat, excluded)}
        return {
            "status": "ok",
            "plan": plan.to_dict(),
            "readiness": {"level": r.level, "rpe_cap": r.rpe_cap, "flags": r.flags},
            "stages": stages,
            "route": rt.__dict__,
            "resolution": _res_view(res),
            "substitutions": subs,
            "provenance": prov,
            "graph": path_graph(decisions, {i.exercise_id for i in plan.items}),
            "trace": trace_out,
        }

    if llm_available("small"):
        with trace.stage("draft"):
            draft, draft_repairs = validate(build(cands, budget, r, stages), cat, cands, r.rpe_cap, r, stages)
        yield {
            **assemble(draft, draft_repairs, "quick plan from the rules; the composer model is still working", trace.snapshot()),
            "draft": True,
        }

    plan, builder_note = None, ""
    with trace.stage("compose") as st:
        for attempt in (1, 2):
            plan = compose(prompt, cands, budget, r, stages, context, trace)
            if plan is None:
                if attempt == 1 and llm_available("small"):
                    continue  # transient model failure (timeout, malformed JSON): one retry
                builder_note = (
                    "deterministic builder (no LLM available)" if attempt == 1 else "deterministic builder (LLM failed twice)"
                )
                break
            plan, repairs = validate(plan, cat, cands, r.rpe_cap, r, stages)
            violations = [x for x in repairs if "to fill" not in x and "to fit" not in x]  # timing edits are not model errors
            if plan.items and len(violations) <= 2:
                break
            trace.event("composer_rejected", attempt=attempt, repairs=repairs)
            builder_note, plan = "deterministic builder (LLM output failed validation twice)", None
        if plan is None:
            plan = build(cands, budget, r, stages)
        st.update(builder=plan.builder)
    with trace.stage("validate") as st:
        plan, repairs = validate(plan, cat, cands, r.rpe_cap, r, stages)
        st.update(repairs=len(repairs))

    result = assemble(
        plan, repairs, builder_note, trace.finish(builder=plan.builder, exercise_count=len(plan.items), blocking=None)
    )
    _store_version(repo, m, prompt, result, replan_reason)
    yield result


def replan_if_needed(member_key: str, reason: str, repo: MemberRepo | None = None) -> dict | None:
    """D13: new member data before a session regenerates today's plan, versioned, with a diff."""
    repo = repo or member_repo()
    m = repo.get(member_key)
    today = [p for p in m.data.get("plans", []) if p["as_of"] == m.as_of.isoformat()]
    if not today:
        return None
    prev = today[-1]
    new = generate(member_key, prev["prompt"], repo=repo, replan_reason=reason)
    if new["status"] != "ok":
        return {"version": None, "status": new["status"], "questions": new.get("questions"), "reason": reason}
    before = {i["name"] for i in prev["plan"]["items"]}
    after = {i["name"] for i in new["plan"]["items"]}
    return {
        "version": new["version"],
        "reason": reason,
        "removed": sorted(before - after),
        "added": sorted(after - before),
        "est_min": (prev["plan"]["est_min"], new["plan"]["est_min"]),
        "plan": new,
    }


def _store_version(repo: MemberRepo, m: Member, prompt: str, result: dict, reason: str | None) -> None:
    versions = [p for p in m.data.get("plans", []) if p["as_of"] == m.as_of.isoformat()]
    result["version"] = len(versions) + 1
    repo.append(
        {
            "type": "plan",
            "member": m.key,
            "payload": {
                "as_of": m.as_of.isoformat(),
                "version": result["version"],
                "prompt": prompt,
                "reason": reason,
                "request_id": result["trace"]["request_id"],
                "created": datetime.now().isoformat(timespec="seconds"),
                "plan": result["plan"],
                "provenance": {  # enough to rebuild the PROV-O record on replay (plan/prov.py)
                    "excluded": [
                        {
                            "exercise_id": r["path"][0],
                            "text": r["text"],
                            "rule": r.get("rule"),
                            "source": r.get("source"),
                            "path": r["path"],
                        }
                        for x in result["provenance"]["activities"][1]["generated_excluded"]
                        if (r := x["reason"])["path"]
                    ]
                },
            },
        }
    )


def _requested_or_familiar_excluded(m: Member, cat, excluded) -> list[str]:
    """Exercises from recent history that are now excluded get substitutes (e.g. 'no barbell')."""
    recent = {cat.lookup(n).id for w in m.data.get("workout_history", [])[:12] for n in w.get("exercises", []) if cat.lookup(n)}
    return sorted(cat.ex[i].name for i in recent & {d.exercise for d in excluded})


def _main_reason(d) -> dict:
    r = next(x for x in d.reasons if x.tier == "exclude")
    return {"text": r.text, "rule": r.rule, "source": r.source, "path": r.path}


def _mention(x) -> dict:
    return {
        "text": x.text,
        "concept": local(x.concept) if x.concept else None,
        "type": x.ctype,
        "role": x.role,
        "pass": x.pass_,
        "confidence": round(x.confidence, 2),
        "extractor": x.extractor,
        "side": x.side,
    }


def _res_view(res) -> dict:
    return {
        "mentions": [_mention(x) for x in res.mentions],
        "time_min": res.time_min,
        "notes": res.notes,
        "blocking": res.blocking,
    }


def _summary(excluded, decisions, notes, budget_note, r, stages, plan) -> list[str]:
    by_rule = Counter(_main_reason(d)["rule"] for d in excluded)
    lines = [f"{len(excluded)} exercises excluded: " + ", ".join(f"{n} by {k}" for k, n in by_rule.most_common())]
    mod = sum(d.tier == "downrank" for d in decisions.values())
    if mod:
        lines.append(f"{mod} allowed with a modification cue")
    lines += notes + [
        budget_note,
        f"readiness {r.level} (RPE cap {r.rpe_cap})",
        f"stage: {', '.join(stages)}",
        f"built by: {plan.builder}; est. {plan.est_min} of {plan.budget_min} min",
    ]
    return lines
