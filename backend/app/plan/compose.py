"""LLM composer (D9 primary path). The model only sees safe candidates and must
answer with their IDs (an enum in the schema), so it cannot name anything else.
Output still goes through the deterministic validator; two failed attempts fall
back to the deterministic builder."""

from __future__ import annotations

import os

from ..llm import LLMUnavailable, available, complete_json
from ..member.signals import Readiness
from ..observability import RequestTrace
from .builder import Item, Plan
from .candidates import Candidate

SYSTEM = """You are an experienced strength coach composing ONE session for a coach to review.
Use ONLY exercises from the candidate table, referenced by exercise_id. Every candidate is already safety-checked.
Order: 1-2 warm-up items, then main lifts, then accessories. Respect the time budget, the RPE cap and any cue given.
Prefer higher scores. Cues: under 12 words. "why": one sentence under 15 words. summary: two sentences at most.
Use reps for rep-based items and duration_s (with reps=0) for timed holds."""


def schema(ids: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items", "summary"],
        "properties": {
            "summary": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["exercise_id", "block", "sets", "reps", "duration_s", "rest_s", "rpe_target", "cue", "why"],
                    "properties": {
                        "exercise_id": {"type": "string", "enum": ids},
                        "block": {"type": "string", "enum": ["warmup", "main", "accessory"]},
                        "sets": {"type": "integer"},
                        "reps": {"type": "integer"},
                        "duration_s": {"type": "integer"},
                        "rest_s": {"type": "integer"},
                        "rpe_target": {"type": "integer"},
                        "cue": {"type": "string"},
                        "why": {"type": "string"},
                    },
                },
            },
        },
    }


def compose(
    prompt: str,
    cands: list[Candidate],
    budget_min: int,
    r: Readiness,
    stages: list[str],
    context: list[str],
    trace: RequestTrace | None,
) -> Plan | None:
    tier = os.getenv("FC_COMPOSE_TIER", "small")  # measured: mid took 8-16 s; small keeps the ~5 s target (see DECISIONS D10)
    if not available(tier):
        return None
    top = cands[:30]
    table = "\n".join(
        f"{c.ex.id} | {c.ex.name} | {c.block} | patterns: {', '.join(sorted(c.ex.patterns))} | score {c.score:g}"
        + (f" | cue: {c.cue}" if c.cue else "")
        + (" | each side" if c.ex.unilateral else "")
        for c in top
    )
    user = (
        f"Coach request: {prompt}\nTime budget: {budget_min} min. RPE cap: {r.rpe_cap}. Volume factor: {r.volume_factor}.\n"
        f"Member stage: {', '.join(stages)}.\nContext:\n- "
        + "\n- ".join(context)
        + f"\n\nCandidates (id | name | block | ...):\n{table}"
    )
    try:
        data = complete_json(
            tier, SYSTEM, user, schema([c.ex.id for c in top]), trace, timeout=float(os.getenv("FC_COMPOSE_TIMEOUT", "12"))
        )
    except LLMUnavailable:
        return None
    by_id = {c.ex.id: c for c in top}
    items = []
    for it in data.get("items", []):
        c = by_id.get(it["exercise_id"])
        name = c.ex.name if c else it["exercise_id"]
        items.append(
            Item(
                it["exercise_id"],
                name,
                it["block"],
                int(it["sets"]),
                int(it["reps"]) or None,
                int(it["duration_s"]) or None,
                int(it["rest_s"]),
                int(it["rpe_target"]) or None,
                bool(c and c.ex.unilateral),
                it.get("cue") or (c.cue if c else None),
                [it.get("why", "")] + (c.why if c else []),
            )
        )
    return Plan(items, budget_min, "llm", data.get("summary", ""))
