"""Score safe candidates (deterministic). Every score component is recorded so the
trace can say *why* an exercise was preferred. Excluded exercises never appear."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..graph.ns import local
from ..member.model import Member
from ..resolver.resolver import Resolution
from ..safety.filter import Decision
from .catalog import Catalog, Ex

WARMUP_PATTERNS = {"mobility-dynamic", "mobility-static", "yoga", "regen", "car"}
MAIN_PATTERNS = {
    "lower-push-squat",
    "lower-push-squat-box-partial",
    "lower-push-lunge",
    "lower-push-split-squat",
    "lower-push-step-up",
    "lower-pull-hip-lift",
    "lower-pull-hinge",
    "upper-push-horizontal",
    "upper-push-vertical",
    "upper-pull-horizontal",
    "upper-pull-vertical",
}


@dataclass
class Candidate:
    ex: Ex
    decision: Decision
    score: float = 0.0
    why: list[str] = field(default_factory=list)
    cue: str | None = None

    @property
    def block(self) -> str:
        if self.ex.patterns & WARMUP_PATTERNS and not self.ex.patterns & MAIN_PATTERNS:
            return "warmup"
        return "main" if self.ex.patterns & MAIN_PATTERNS else "accessory"


def recent_exercise_dates(m: Member, cat: Catalog, as_of: date) -> dict[str, date]:
    seen: dict[str, date] = {}
    for w in m.data.get("workout_history", []):
        if not w.get("completed"):
            continue
        d = date.fromisoformat(w["date"])
        for name in w.get("exercises", []):
            e = cat.lookup(name)
            if e and (e.id not in seen or d > seen[e.id]):
                seen[e.id] = d
    return seen


def score(
    cat: Catalog, decisions: dict[str, Decision], res: Resolution, m: Member, stages: list[str], dislike_ids: set[str]
) -> list[Candidate]:
    as_of = m.as_of
    region_targets = {local(x.concept) for x in res.of("target", "region")}
    muscle_targets = {local(x.concept) for x in res.of("target", "muscle")}
    pattern_targets = {local(x.concept) for x in res.of("target", "pattern")}
    wanted_patterns = set().union(*(cat.region_patterns.get(r, set()) for r in region_targets)) if region_targets else set()
    recent = recent_exercise_dates(m, cat, as_of)
    out: list[Candidate] = []
    for d in decisions.values():
        if d.tier == "exclude":
            continue
        e = cat.ex[d.exercise]
        c = Candidate(e, d)
        if wanted_patterns and e.patterns & wanted_patterns:
            c.score += 3
            c.why.append("matches the requested body region")
        if "full-body" in region_targets or not (region_targets or muscle_targets or pattern_targets):
            c.score += 1
        if muscle_targets & e.muscles:
            c.score += 3
            c.why.append(f"targets {', '.join(sorted(muscle_targets & e.muscles))}")
        if pattern_targets & e.pattern_ancestors:
            c.score += 3
            c.why.append("requested movement")
        if d.uprank:
            c.score += 2
            c.why.append(next(r.text for r in d.reasons if r.kind == "uprank"))
        if d.tier == "downrank":
            c.score -= 2
            r = next(r for r in d.reasons if r.tier == "downrank")
            c.cue = r.text.split("Cue: ", 1)[1] if "Cue: " in r.text else None
            c.why.append("modified for the injury" + (f": {c.cue}" if c.cue else ""))
        if e.id in dislike_ids:
            c.score -= 2
            c.why.append("listed as a dislike (soft preference)")
        last = recent.get(e.id)
        if last and ("at-risk" in stages or "onboarding" in stages) and as_of - last <= timedelta(days=28):
            c.score += 1
            c.why.append(f"familiar: last done {last.isoformat()}")
        if last and as_of - last <= timedelta(days=1):
            c.score -= 2
            c.why.append("done yesterday")
        if "onboarding" in stages and (e.unilateral or "balance" in e.patterns or "cardio-plyometric" in e.patterns):
            c.score -= 1
        if d.flags:
            c.why.append(d.flags[0])
        out.append(c)
    return sorted(out, key=lambda c: (-c.score, c.ex.name))
