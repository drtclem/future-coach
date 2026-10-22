"""Longitudinal signals, one job per timescale (D11), plus check-in flags (D12)
and honest churn (D5.3). Pure functions of member data and the as-of date;
every output carries the evidence it used, cited by node id.

All thresholds are PARAMETERS (documented, overridable), not facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean

from .model import Member

PARAMS = {
    "readiness_low_sleep_deficit_h": 2.0,  # vs personal 28-day baseline
    "readiness_low_sleep_floor_h": 5.0,
    "readiness_reduced_sleep_deficit_h": 1.0,
    "readiness_low_energy": 2,  # check-in energy (1-5) at or below
    "pain_acute_threshold": 4,  # 0-10, clinician-owned (sources range 2-5)
    "baseline_days": 28,
    "cold_start_days": 14,
    "population_sleep_default_h": 7.0,
    "onboarding_days": 28,
    "established_days": 180,
    "at_risk_last_week_max": 80,
    "at_risk_drop_points": 20,
}
CAPS = {"normal": (8, 1.0), "reduced": (7, 0.85), "low": (6, 0.6)}  # level -> (RPE cap, volume factor)


@dataclass
class Evidence:
    text: str
    node: str | None = None


@dataclass
class Readiness:
    level: str  # normal | reduced | low
    rpe_cap: int
    volume_factor: float
    sleep_last_night: float | None
    sleep_source: str
    baseline: float | None
    evidence: list[Evidence] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    acute_today: list[str] = field(default_factory=list)  # injury ids escalated to acute for today


def _day(ts: str) -> date:
    return datetime.fromisoformat(ts).date()


def readiness(m: Member, as_of: date | None = None) -> Readiness:
    """Readiness can only LOWER intensity (D11). Precedence for last night's sleep (D12):
    today's check-in > last night's device > personal rolling average > self-reported typical > population default."""
    as_of = as_of or m.as_of
    ev: list[Evidence] = []
    daily = [d for d in m.data.get("biomarkers", {}).get("daily", []) if d.get("sleep_hours") is not None]
    window = [d for d in daily if as_of - timedelta(days=PARAMS["baseline_days"]) < date.fromisoformat(d["date"]) < as_of]
    baseline = round(mean(d["sleep_hours"] for d in window), 1) if len(window) >= PARAMS["cold_start_days"] else None
    typical = (m.data.get("self_reported") or {}).get("typical_sleep_hours")
    ref = baseline or typical or PARAMS["population_sleep_default_h"]
    ref_src = "28-day personal average" if baseline else "self-reported typical" if typical else "population default"

    today = [c for c in m.checkins() if _day(c["ts"]) == as_of]
    checkin = {k: v for c in today for k, v in c.items() if v is not None} if today else None  # later fields win
    device = next((d for d in daily if d["date"] == as_of.isoformat()), None)
    if checkin and checkin.get("sleep_hours") is not None:
        sleep, src, node = checkin["sleep_hours"], "today's check-in", m.node("checkin", checkin["ts"])
    elif device:
        sleep, src, node = device["sleep_hours"], "device (last night)", m.node("biomarker", device["date"])
    else:
        sleep, src, node = None, "no data today", None
    if not checkin:
        ev.append(Evidence("no check-in today"))

    level = "normal"
    if sleep is not None:
        deficit = ref - sleep
        ev.append(Evidence(f"slept {sleep} h ({src}) vs {ref} h {ref_src}", node))
        if deficit >= PARAMS["readiness_low_sleep_deficit_h"] or sleep <= PARAMS["readiness_low_sleep_floor_h"]:
            level = "low"
        elif deficit >= PARAMS["readiness_reduced_sleep_deficit_h"]:
            level = "reduced"
    energy = checkin.get("energy") if checkin else None
    if energy is not None and energy <= PARAMS["readiness_low_energy"]:
        level = "low" if level != "normal" else "reduced"
        ev.append(Evidence(f"check-in energy {energy}/5", m.node("checkin", checkin["ts"])))

    r = Readiness(level, *CAPS[level], sleep, src, baseline, ev)
    if level != "normal":
        r.flags.append(f"readiness {level}: intensity capped at RPE {r.rpe_cap}, volume x{r.volume_factor}")
    if checkin and checkin.get("pain"):
        p = checkin["pain"]
        for inj in m.injuries:
            area = p.get("area", "").lower()
            if inj.status != "cleared" and (inj.structure.split("-")[0] in area or inj.label.split(" (")[0].lower() in area):
                if p["score"] >= PARAMS["pain_acute_threshold"]:
                    r.acute_today.append(inj.id)
                    r.flags.append(
                        f"pain {p['score']}/10 in {area} >= {PARAMS['pain_acute_threshold']}: {inj.id} treated as ACUTE today; coach notified"
                    )
                else:
                    r.evidence.append(
                        Evidence(f"pain {p['score']}/10 in {area} (below threshold)", m.node("checkin", checkin["ts"]))
                    )
    return r


# ---------------------------------------------------------------- adherence & journey
def completed_weeks(m: Member, as_of: date | None = None) -> tuple[list[dict], dict | None]:
    """Provided weekly adherence split into completed weeks and the in-progress week (C2)."""
    as_of = as_of or m.as_of
    weeks = sorted(m.data.get("adherence", {}).get("weekly_completion_pct", []), key=lambda w: w["week_of"])
    done = [w for w in weeks if date.fromisoformat(w["week_of"]) + timedelta(days=7) <= as_of]
    cur = next(
        (w for w in weeks if date.fromisoformat(w["week_of"]) <= as_of < date.fromisoformat(w["week_of"]) + timedelta(days=7)),
        None,
    )
    if cur:
        cur = dict(cur, days_elapsed=(as_of - date.fromisoformat(cur["week_of"])).days + 1)
    return done, cur


def journey(m: Member, as_of: date | None = None) -> tuple[list[str], list[Evidence]]:
    as_of = as_of or m.as_of
    tenure = (as_of - date.fromisoformat(m.data["profile"]["member_since"])).days
    done, _ = completed_weeks(m, as_of)
    ev = [Evidence(f"member for {tenure} days")]
    stages: list[str] = []
    if tenure < PARAMS["onboarding_days"]:
        stages.append("onboarding")
    elif len(done) >= 4:
        last, prior = done[-1]["pct"], mean(w["pct"] for w in done[-4:-1])
        ev.append(
            Evidence(
                f"last completed week {last}% vs prior 3-week mean {prior:.0f}%",
                f"member/{m.key}/adherence/{done[-1]['week_of']}",
            )
        )
        if last <= PARAMS["at_risk_last_week_max"] and prior - last >= PARAMS["at_risk_drop_points"]:
            stages.append("at-risk")
        stages.insert(
            0, "established" if tenure >= PARAMS["established_days"] and mean(w["pct"] for w in done[-4:]) >= 80 else "building"
        )
    else:
        stages.append("building")
    if any(i.status != "cleared" for i in m.injuries):
        stages.append("rehab")
    return stages, ev


# ---------------------------------------------------------------- churn (D5.3)
FATIGUE_WORDS = ("wiped", "tired", "exhausted", "slammed", "busy", "work", "deadline", "sick")


MAX_CHURN = 7  # adherence drop 2 + under 80% 1 + skips 1 + messages 1 + short sessions 1 + sleep 1


def churn(m: Member, as_of: date | None = None) -> dict:
    as_of = as_of or m.as_of
    ev: list[dict] = []
    score = 0
    done, cur = completed_weeks(m, as_of)
    if len(done) >= 4:
        last, prior = done[-1]["pct"], mean(w["pct"] for w in done[-4:-1])
        pts = (2 if prior - last >= 20 else 1 if prior - last >= 10 else 0) + (1 if last < 80 else 0)
        score += pts
        ev.append(
            {
                "signal": "adherence",
                "points": pts,
                "text": f"last completed week (of {done[-1]['week_of']}) {last}% vs prior 3-week mean {prior:.0f}%",
                "node": f"member/{m.key}/adherence/{done[-1]['week_of']}",
            }
        )
    if cur:
        ev.append(
            {
                "signal": "adherence",
                "points": 0,
                "text": f"current week (of {cur['week_of']}) in progress, {cur['days_elapsed']} of 7 days; "
                f"its {cur['pct']}% is not counted",
                "node": f"member/{m.key}/adherence/{cur['week_of']}",
            }
        )
    recent = [w for w in m.data.get("workout_history", []) if as_of - timedelta(days=14) <= date.fromisoformat(w["date"]) < as_of]
    skipped = [w for w in recent if w.get("completed") is False]
    if skipped:
        reasons = [
            c
            for c in m.messages()
            if c["from"] == "member"
            and any(f in c["text"].lower() for f in FATIGUE_WORDS)
            and as_of - timedelta(days=14) <= _day(c["ts"]) <= as_of
        ]
        score += 1
        ev.append(
            {
                "signal": "skips",
                "points": 1,
                "text": f"{len(skipped)} skipped session(s) in 14 days"
                + (f'; member said: "{reasons[-1]["text"]}"' if reasons else ""),
                "node": m.node("message", reasons[-1]["ts"]) if reasons else m.node("workout", skipped[0]["date"]),
            }
        )

    def member_msgs(a, b):
        return [c for c in m.messages() if c["from"] == "member" and a <= _day(c["ts"]) < b]

    last4 = member_msgs(as_of - timedelta(days=28), as_of + timedelta(days=1))
    prev4 = member_msgs(as_of - timedelta(days=56), as_of - timedelta(days=28))
    pts = 1 if prev4 and len(last4) <= len(prev4) / 2 else 0
    score += pts
    ev.append(
        {
            "signal": "messages",
            "points": pts,
            "text": f"member-initiated messages: {len(last4)} in the last 4 weeks vs {len(prev4)} the 4 weeks before",
            "node": None,
        }
    )
    pref = m.data.get("preferences", {}).get("preferred_session_minutes")
    durs = [w["duration_min"] for w in sorted(m.data.get("workout_history", []), key=lambda w: w["date"]) if w.get("completed")][
        -4:
    ]
    if pref and durs and mean(durs) < 0.7 * pref:
        score += 1
        ev.append(
            {
                "signal": "session length",
                "points": 1,
                "text": f"last 4 sessions averaged {mean(durs):.0f} min vs {pref} min preferred",
                "node": None,
            }
        )
    week = [
        d["sleep_hours"]
        for d in m.data.get("biomarkers", {}).get("daily", [])
        if as_of - timedelta(days=7) < date.fromisoformat(d["date"]) <= as_of
    ]
    goal = 7.0
    if week and mean(week) < goal - 0.5:
        score += 1
        ev.append(
            {
                "signal": "sleep",
                "points": 1,
                "text": f"sleep averaged {mean(week):.1f} h over 7 days vs {goal} h goal",
                "node": None,
            }
        )
    level = "elevated" if score >= 4 else "moderate" if score >= 2 else "low"
    provided = (m.data.get("coach_brief") or {}).get("churn_risk")
    note = None
    if provided:
        parts = []
        if provided["level"] != level:
            parts.append(f"The morning brief rates the risk {provided['level']}, but the signals above add up to {level}.")
        if any("50%" in r for r in provided.get("reasons", [])) and cur and len(done) >= 4:
            prior = mean(w["pct"] for w in done[-4:-1])
            parts.append(
                f"The brief says adherence fell to 50%, but that's this week, which is only {cur['days_elapsed']} days in. "
                f"Comparing full weeks, it fell from {prior:.0f}% to {done[-1]['pct']}%."
            )
        note = " ".join(parts) or None
    return {"level": level, "score": score, "max_score": MAX_CHURN, "evidence": ev, "provided": provided, "disagreement": note}
