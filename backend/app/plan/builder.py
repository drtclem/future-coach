"""Plan model, timing (D14), deterministic builder (D9 fallback) and substitution (D4)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..member.signals import Readiness
from .candidates import Candidate
from .catalog import Catalog

REP_SECONDS = 4  # shortcut: catalog estimated_rep_duration has unclear units; a fixed 4 s/rep is documented instead
TRANSITION_S = 45
WARMUP_BUDGET_S = 5 * 60


@dataclass
class Item:
    exercise_id: str
    name: str
    block: str  # warmup | main | accessory
    sets: int
    reps: int | None
    duration_s: int | None
    rest_s: int
    rpe_target: int | None
    each_side: bool = False
    cue: str | None = None
    why: list[str] = field(default_factory=list)

    def seconds(self) -> int:
        work = (self.reps or 0) * REP_SECONDS if self.reps else (self.duration_s or 0)
        work *= 2 if self.each_side else 1
        return self.sets * (work + self.rest_s) + TRANSITION_S


@dataclass
class Plan:
    items: list[Item]
    budget_min: int
    builder: str  # llm | deterministic
    summary: str = ""

    @property
    def est_min(self) -> float:
        return round(sum(i.seconds() for i in self.items) / 60, 1)

    def to_dict(self) -> dict:
        from .catalog import catalog
        from .glyph import glyph

        cat = catalog()
        return {
            "items": [{**asdict(i), "glyph": glyph(cat.ex.get(i.exercise_id))} for i in self.items],
            "budget_min": self.budget_min,
            "est_min": self.est_min,
            "builder": self.builder,
            "summary": self.summary,
        }


def prescribe(c: Candidate, block: str, r: Readiness, stages: list[str]) -> Item:
    onboarding = "onboarding" in stages
    if block == "warmup":
        sets, reps, dur, rest, rpe = 1, None, 45, 0, None
    elif block == "main":
        sets, reps, rest = (2, 10, 90) if onboarding else (3, 8, 75)
        dur, rpe = None, min(r.rpe_cap, 7 if onboarding or "at-risk" in stages else 8)
    else:
        sets, reps, rest, dur, rpe = 2, 12, 45, None, min(r.rpe_cap, 7)
    if not c.ex.is_reps and c.ex.is_duration:
        reps, dur = None, 30 if block != "warmup" else 45
    if block != "warmup":
        sets = max(1, round(sets * r.volume_factor))
    return Item(c.ex.id, c.ex.name, block, sets, reps, dur, rest, rpe, c.ex.unilateral, c.cue, list(c.why))


def build(cands: list[Candidate], budget_min: int, r: Readiness, stages: list[str]) -> Plan:
    """Deterministic plan: warm-up, then main lifts with pattern diversity, then accessories, until the budget is used."""
    budget = budget_min * 60
    items: list[Item] = []
    used_patterns: set[str] = set()

    warm = [c for c in cands if c.block == "warmup"]
    reserve = sum(prescribe(c, "warmup", r, stages).seconds() for c in warm[:2])
    for block in ("main", "accessory"):
        for c in (c for c in cands if c.block == block and c.score > 0):
            primary = "lower-push-squat" if "lower-push-squat" in c.ex.pattern_ancestors else sorted(c.ex.patterns)[0]
            if primary in used_patterns or any(i.exercise_id == c.ex.id for i in items):
                continue
            it = prescribe(c, block, r, stages)
            if sum(i.seconds() for i in items) + it.seconds() + reserve <= budget:
                items.append(it)
                used_patterns.add(primary)
    # Small safe pool (e.g. limited equipment): add sets to main work, up to 5, before leaving time unused.
    while items and sum(i.seconds() for i in items) + reserve < 0.75 * budget:
        mains = [i for i in items if i.block == "main" and i.sets < 5 and not i.cue]  # never pad injury-modified work
        if not mains:
            break
        it = min(mains, key=lambda i: i.sets)
        it.sets += 1
        if sum(i.seconds() for i in items) + reserve > budget:
            it.sets -= 1
            break
    # Warm-up chosen last so it matches the session: most muscle overlap with the chosen work.
    worked = set().union(*(cands_by_id(cands)[i.exercise_id].ex.muscles for i in items)) if items else set()
    warm.sort(key=lambda c: (-len(c.ex.muscles & worked), -c.score, c.ex.name))
    items = [prescribe(c, "warmup", r, stages) for c in warm[:2]] + items
    return Plan(
        items, budget_min, "deterministic", "Built by the deterministic planner from the highest-scoring safe candidates."
    )


def cands_by_id(cands: list[Candidate]) -> dict[str, Candidate]:
    return {c.ex.id: c for c in cands}


def substitutes(cat: Catalog, ex_id: str, safe: list[Candidate], k: int = 3) -> list[dict]:
    """D4: alternatives for an exercise that cannot be used. Shared movement pattern first, then muscle overlap.
    Only safe candidates are considered, so substitution can never bring an exclusion back."""
    src = cat.ex[ex_id]
    ranked = []
    for c in safe:
        if c.ex.id == ex_id:
            continue
        shared_p = (src.pattern_ancestors & c.ex.pattern_ancestors) - {"isometric", "balance"}
        overlap = len(src.muscles & c.ex.muscles) / max(len(src.muscles | c.ex.muscles), 1)
        if not shared_p and overlap < 0.34:
            continue
        ranked.append((bool(shared_p), overlap, c.score, c, shared_p))
    ranked.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [
        {
            "exercise_id": c.ex.id,
            "name": c.ex.name,
            "kind": "equivalent" if sp else "partial",
            "why": (f"same pattern ({', '.join(sorted(sp))})" if sp else "different pattern") + f", muscle overlap {ov:.0%}",
        }
        for sp_flag, ov, _, c, sp in ranked[:k]
    ]
