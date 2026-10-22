"""Deterministic post-validation (D9, SPEC_REVIEW 1.2). Always runs, whichever
builder produced the plan. Violations are repaired (safe substitute) or dropped,
and every repair is reported for the trace."""

from __future__ import annotations

import re

from .builder import Plan, prescribe, substitutes
from .candidates import Candidate
from .catalog import Catalog

CLINICAL_ADVICE = re.compile(
    r"\b(supplement\w*|dosage|dose|\d+\s*(mg|iu|mcg)\b(?!\s*(/|per\b))|prescri\w+|medication|you should take|start taking|statin)",
    re.I,
)
PAIN_PUSH = re.compile(
    r"\b(push(ing)?|work(ing)?|grind(ing)?|power(ing)?) (it )?through (\w+ ){0,3}(pain|hurt\w*)|ignor\w* (the |any )?pain"
    r"|no pain,? no gain|even if it hurts|pain is (fine|ok|okay|normal|good)|don'?t worry about (the )?(pain|knee|back|shoulder)",
    re.I,
)
# Model text that reaches the coach must never coach through pain or give clinical advice.
UNSAFE_TEXT = (CLINICAL_ADVICE, PAIN_PUSH)
REPS, HOLD_S = (1, 30), (5, 180)
REST_S = {"warmup": (0, 60), "main": (30, 300), "accessory": (15, 180)}


def unsafe(text: str | None) -> bool:
    return bool(text) and any(p.search(text) for p in UNSAFE_TEXT)


def _clamp(it, field: str, lo: int, hi: int, repairs: list[str]) -> None:
    v = getattr(it, field)
    if v is not None and not lo <= v <= hi:
        setattr(it, field, min(max(v, lo), hi))
        repairs.append(f"'{it.name}': {field} {v} clamped to {getattr(it, field)}")


def validate(
    plan: Plan, cat: Catalog, safe: list[Candidate], rpe_cap: int, readiness=None, stages=None
) -> tuple[Plan, list[str]]:
    by_id = {c.ex.id: c for c in safe}
    safe_ids = set(by_id)
    if unsafe(plan.summary):
        plan.summary = ""
        repairs_pre = ["plan summary dropped (unsafe wording)"]
    else:
        repairs_pre = []
    repairs: list[str] = repairs_pre
    kept, seen = [], set()
    for it in plan.items:
        if it.exercise_id not in cat.ex:
            repairs.append(f"dropped '{it.name}': not in the catalog (hallucinated)")
            continue
        if it.exercise_id not in safe_ids:
            alt = substitutes(cat, it.exercise_id, safe, k=1)
            alt = [a for a in alt if a["exercise_id"] not in seen]
            if alt:
                repairs.append(f"replaced '{it.name}' with '{alt[0]['name']}': not in the safe set ({alt[0]['why']})")
                it.exercise_id, it.name = alt[0]["exercise_id"], alt[0]["name"]
                it.cue, it.why = None, [alt[0]["why"]]  # the old exercise's text doesn't describe the substitute
            else:
                repairs.append(f"dropped '{it.name}': not in the safe set and no safe substitute")
                continue
        if it.exercise_id in seen:
            repairs.append(f"dropped duplicate '{it.name}'")
            continue
        # Text: the graph's cue for this exercise always shows; model text is added only if it passes the guard.
        graph_cue = by_id[it.exercise_id].cue
        model_cue = None if it.cue in (None, "", graph_cue) else it.cue
        if model_cue and unsafe(model_cue):
            repairs.append(f"'{it.name}': model cue dropped (unsafe wording)")
            model_cue = None
        if graph_cue and model_cue and graph_cue in model_cue:
            graph_cue = None  # the model already repeated it verbatim
        it.cue = " ".join(x for x in (graph_cue, model_cue) if x) or None
        if any(unsafe(w) for w in it.why):
            repairs.append(f"'{it.name}': model reason dropped (unsafe wording)")
            it.why = [w for w in it.why if not unsafe(w)]
        # Numbers: keep doses inside sane ranges.
        if not it.reps and not it.duration_s:
            repairs.append(f"dropped '{it.name}': no reps or hold time")
            continue
        _clamp(it, "reps", *REPS, repairs)
        _clamp(it, "duration_s", *HOLD_S, repairs)
        _clamp(it, "rest_s", *REST_S.get(it.block, REST_S["main"]), repairs)
        if it.rpe_target and it.rpe_target > rpe_cap:
            repairs.append(f"'{it.name}': RPE {it.rpe_target} lowered to the readiness cap {rpe_cap}")
            it.rpe_target = rpe_cap
        it.sets = max(1, min(it.sets, 6))
        seen.add(it.exercise_id)
        kept.append(it)
    plan.items = kept
    # Time window (D14): trim accessories from the end first, never the warm-up.
    while plan.est_min > plan.budget_min + 1:
        idx = next((i for i in range(len(plan.items) - 1, -1, -1) if plan.items[i].block == "accessory"), None)
        if idx is None:
            idx = next((i for i in range(len(plan.items) - 1, -1, -1) if plan.items[i].block == "main"), None)
        if idx is None:
            break
        it = plan.items[idx]
        if it.sets > 1 and it.block == "main":
            it.sets -= 1
            repairs.append(f"'{it.name}': one set removed to fit {plan.budget_min} min")
        else:
            repairs.append(f"removed '{it.name}' to fit {plan.budget_min} min")
            plan.items.pop(idx)
    # Under-filled plan (D14 + anti-gaming guard): add sets to main work, then safe accessories, up to ~80% of the window.
    if readiness is not None:
        used = {i.exercise_id for i in plan.items}
        pool = [c for c in safe if c.ex.id not in used and c.block != "warmup" and c.score > 0 and not c.cue]
        while plan.items and plan.est_min < 0.8 * plan.budget_min:
            mains = [
                i for i in plan.items if i.block == "main" and i.sets < 5 and not by_id[i.exercise_id].cue
            ]  # never pad injury-modified work (graph cue, not model text)
            if not mains:  # then uninjured accessory work, up to 4 sets
                mains = [i for i in plan.items if i.block == "accessory" and i.sets < 4 and not by_id[i.exercise_id].cue]
            if mains:
                it = min(mains, key=lambda i: i.sets)
                it.sets += 1
                undo = lambda it=it: setattr(it, "sets", it.sets - 1)  # noqa: E731
                repairs.append(f"'{it.name}': set added to fill {plan.budget_min} min")
            elif pool:
                c = pool.pop(0)
                plan.items.append(prescribe(c, "accessory", readiness, stages or []))
                undo = plan.items.pop
                repairs.append(f"added '{c.ex.name}' to fill {plan.budget_min} min")
            else:
                break
            if plan.est_min > plan.budget_min + 1:  # overshot the window: undo the last step and stop
                undo()
                repairs.pop()
                break
    return plan, repairs
