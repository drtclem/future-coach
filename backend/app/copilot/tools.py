"""Copilot tools over the member graph (KG2). Each returns evidence items with a
stable node id, and charts are built here from the data (never from LLM numbers).
Relative dates are anchored to the member's as-of date (SPEC_REVIEW 2.8)."""

from __future__ import annotations

import inspect
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean

from ..member.model import Member
from ..member.signals import churn, completed_weeks, journey, readiness


@dataclass
class Evidence:
    id: str
    node: str
    text: str
    quote: str | None = None  # member/coach words verbatim, if any


@dataclass
class ToolResult:
    tool: str
    evidence: list[Evidence] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


class Toolbox:
    def __init__(self, m: Member):
        self.m = m
        self.n = 0

    def _ev(self, node: str, text: str, quote: str | None = None) -> Evidence:
        self.n += 1
        return Evidence(f"E{self.n}", node, text, quote)

    def _days(self, n: int) -> tuple[date, date]:
        return self.m.as_of - timedelta(days=n - 1), self.m.as_of

    # -------------------------------------------------------------- tools
    def get_yesterday(self) -> ToolResult:
        y = self.m.as_of - timedelta(days=1)
        out = ToolResult("get_yesterday")
        for w in self.m.data.get("workout_history", []):
            if w["date"] == y.isoformat():
                status = "completed" if w.get("completed") else "skipped" if w.get("completed") is False else "scheduled"
                out.evidence.append(
                    self._ev(
                        self.m.node("workout", w["date"]),
                        f"{w['date']}: {w['title']} {status}"
                        + (
                            f", {w['duration_min']} min, RPE {w['rpe']}: {', '.join(w['exercises'])}"
                            if w.get("completed")
                            else ""
                        ),
                    )
                )
        for c in self.m.messages():
            if datetime.fromisoformat(c["ts"]).date() == y:
                out.evidence.append(self._ev(self.m.node("message", c["ts"]), f"{c['from']} on {y}", quote=c["text"]))
        return out

    def get_sleep(self, days: int = 7) -> ToolResult:
        a, b = self._days(days)
        rows = [d for d in self.m.data.get("biomarkers", {}).get("daily", []) if a <= date.fromisoformat(d["date"]) <= b]
        out = ToolResult("get_sleep")
        if not rows:
            out.evidence.append(self._ev(f"member/{self.m.key}/biomarkers", "no device sleep data in this period"))
            return out
        vals = [r["sleep_hours"] for r in rows]
        weeknights = [r["sleep_hours"] for r in rows if date.fromisoformat(r["date"]).weekday() < 5]
        out.facts = {
            "avg": round(mean(vals), 1),
            "min": min(vals),
            "max": max(vals),
            "weeknight_avg": round(mean(weeknights), 1) if weeknights else None,
            "nights_7plus": sum(v >= 7 for v in vals),
            "n": len(vals),
        }
        out.evidence.append(
            self._ev(
                f"member/{self.m.key}/biomarker/{rows[0]['date']}..{rows[-1]['date']}",
                f"sleep {rows[0]['date']} to {rows[-1]['date']}: avg {out.facts['avg']} h (weeknights {out.facts['weeknight_avg']} h), "
                f"{out.facts['nights_7plus']}/{len(vals)} nights at 7 h or more",
            )
        )
        if days > 1:
            out.charts.append(
                {
                    "type": "line",
                    "title": f"Sleep, last {days} days",
                    "unit": "h",
                    "goal": 7.0,
                    "x": [r["date"] for r in rows],
                    "series": [{"name": "sleep (h)", "values": vals}],
                }
            )
        return out

    def get_adherence(self, weeks: int = 4) -> ToolResult:
        done, cur = completed_weeks(self.m)
        done = done[-weeks:]
        out = ToolResult("get_adherence", facts={"completed": done, "current": cur})
        for w in done:
            out.evidence.append(
                self._ev(
                    f"member/{self.m.key}/adherence/{w['week_of']}", f"week of {w['week_of']}: {w['pct']}% of planned sessions"
                )
            )
        if cur:
            out.evidence.append(
                self._ev(
                    f"member/{self.m.key}/adherence/{cur['week_of']}",
                    f"week of {cur['week_of']} in progress ({cur['days_elapsed']} of 7 days), {cur['pct']}% so far",
                )
            )
        out.charts.append(
            {
                "type": "bar",
                "title": f"Adherence, last {len(done)} completed weeks",
                "unit": "%",
                "x": [w["week_of"] for w in done],
                "series": [{"name": "completed %", "values": [w["pct"] for w in done]}],
                "note": f"current week in progress ({cur['days_elapsed']}/7 days), not shown" if cur else None,
            }
        )
        return out

    def get_messages(self, weeks: int = 8) -> ToolResult:
        """Message pattern (D19): member-initiated messages per week, plus who initiates."""
        start = self.m.as_of - timedelta(weeks=weeks)
        msgs = [c for c in self.m.messages() if datetime.fromisoformat(c["ts"]).date() > start]
        buckets = Counter()
        for c in msgs:
            if c["from"] == "member":
                d = datetime.fromisoformat(c["ts"]).date()
                buckets[(d - timedelta(days=d.weekday())).isoformat()] += 1
        wk = [(start + timedelta(days=7 * i)) for i in range(weeks + 1)]
        x = sorted({(d - timedelta(days=d.weekday())).isoformat() for d in wk if d <= self.m.as_of})
        who = Counter(c["from"] for c in msgs)
        out = ToolResult("get_messages", facts={"per_week": {k: buckets.get(k, 0) for k in x}, "by_author": dict(who)})
        out.evidence.append(
            self._ev(
                f"member/{self.m.key}/messages",
                f"last {weeks} weeks: {who.get('member', 0)} member-initiated, {who.get('coach', 0)} from the coach",
            )
        )
        for c in msgs[-3:]:
            out.evidence.append(self._ev(self.m.node("message", c["ts"]), f"{c['from']} on {c['ts'][:10]}", quote=c["text"]))
        out.charts.append(
            {
                "type": "bar",
                "title": "Member-initiated messages per week",
                "unit": "messages",
                "x": x,
                "series": [{"name": "member messages", "values": [buckets.get(k, 0) for k in x]}],
            }
        )
        return out

    def get_churn(self) -> ToolResult:
        c = churn(self.m)
        out = ToolResult("get_churn", facts={"level": c["level"], "score": c["score"], "disagreement": c["disagreement"]})
        for e in c["evidence"]:
            quote = e["text"].split('member said: "', 1)[1].rstrip('"') if 'member said: "' in e["text"] else None
            out.evidence.append(self._ev(e["node"] or f"member/{self.m.key}/signals/{e['signal']}", e["text"], quote=quote))
        if c["provided"]:
            out.evidence.append(
                self._ev(f"member/{self.m.key}/coach_brief", f"provided brief: churn risk '{c['provided']['level']}'")
            )
        return out

    def get_status(self) -> ToolResult:
        r = readiness(self.m)
        stages, _ = journey(self.m)
        out = ToolResult("get_status", facts={"readiness": r.level, "stages": stages})
        out.evidence.append(
            self._ev(
                f"member/{self.m.key}/readiness/{self.m.as_of}",
                f"readiness today: {r.level} (RPE cap {r.rpe_cap}); " + "; ".join(e.text for e in r.evidence),
            )
        )
        out.evidence.append(self._ev(f"member/{self.m.key}/journey", f"journey stage: {', '.join(stages)}"))
        for i in self.m.injuries:
            out.evidence.append(
                self._ev(
                    self.m.node("injury", i.id),
                    f"injury: {i.label}, {i.status}"
                    + (
                        f", member rules: {', '.join(r.tier + ' ' + r.load_type for r in i.extra_rules)}" if i.extra_rules else ""
                    ),
                )
            )
        for c in self.m.checkins()[-2:]:
            out.evidence.append(
                self._ev(
                    self.m.node("checkin", c["ts"]),
                    f"check-in {c['ts'][:10]}: "
                    + ", ".join(f"{k} {v}" for k, v in c.items() if k in ("sleep_hours", "energy", "pain", "time_available_min")),
                    quote=c.get("note"),
                )
            )
        return out

    def get_labs(self) -> ToolResult:
        labs = self.m.data.get("labs") or {}
        out = ToolResult("get_labs", facts=labs)
        for panel, vals in labs.items():
            out.evidence.append(
                self._ev(
                    f"member/{self.m.key}/labs/{panel}",
                    f"{panel} ({vals.get('date')}): " + ", ".join(f"{k} {v}" for k, v in vals.items() if k != "date"),
                )
            )
        return out

    def get_changes(self) -> ToolResult:
        """This week (7 days to the as-of date) against the 7 days before, one evidence item per signal."""
        b1 = self.m.as_of
        a1, a0 = b1 - timedelta(days=6), b1 - timedelta(days=13)
        b0 = a1 - timedelta(days=1)

        def within(d: date, a: date, b: date) -> bool:
            return a <= d <= b

        daily = self.m.data.get("biomarkers", {}).get("daily", [])
        out = ToolResult("get_changes", facts={"this_week": f"{a1}..{b1}", "last_week": f"{a0}..{b0}"})

        def avg(key: str, a: date, b: date):
            v = [r[key] for r in daily if key in r and within(date.fromisoformat(r["date"]), a, b)]
            return round(mean(v), 1) if v else None

        for key, label, unit in (
            ("sleep_hours", "sleep", " h"),
            ("hrv_ms", "HRV", " ms"),
            ("resting_hr_bpm", "resting HR", " bpm"),
        ):
            now, before = avg(key, a1, b1), avg(key, a0, b0)
            if now is not None and before is not None:
                out.facts[key] = [before, now]
                out.evidence.append(
                    self._ev(
                        f"member/{self.m.key}/biomarkers/{a0}..{b1}",
                        f"{label} averaged {now}{unit} this week vs {before}{unit} last week",
                    )
                )
        w = self.m.data.get("workout_history", [])
        for label, a, b in (("this week", a1, b1), ("last week", a0, b0)):
            days = [x for x in w if within(date.fromisoformat(x["date"]), a, b)]
            done = [x for x in days if x.get("completed")]
            skipped = [x for x in days if x.get("completed") is False]
            out.facts[f"sessions_{label.split()[0]}"] = len(done)
            out.evidence.append(
                self._ev(
                    f"member/{self.m.key}/workouts/{a}..{b}",
                    f"{label}: {len(done)} sessions completed" + (f", {len(skipped)} skipped" if skipped else ""),
                )
            )
        msgs = [c for c in self.m.messages() if c["from"] == "member"]
        n1 = sum(within(datetime.fromisoformat(c["ts"]).date(), a1, b1) for c in msgs)
        n0 = sum(within(datetime.fromisoformat(c["ts"]).date(), a0, b0) for c in msgs)
        out.evidence.append(
            self._ev(f"member/{self.m.key}/messages/{a0}..{b1}", f"member messages: {n1} this week vs {n0} last week")
        )
        for c in self.m.checkins():
            if within(datetime.fromisoformat(c["ts"]).date(), a1, b1) and c.get("pain"):
                p = c["pain"]
                out.evidence.append(
                    self._ev(
                        self.m.node("checkin", c["ts"]),
                        f"check-in {c['ts'][:10]}: pain in {p['area']} {p.get('score')}/10",
                        quote=c.get("note"),
                    )
                )
        return out

    def get_brief(self) -> ToolResult:
        b = self.m.data.get("coach_brief") or {}
        out = ToolResult("get_brief", facts=b)
        for t in b.get("morning_tasks", []):
            out.evidence.append(self._ev(f"member/{self.m.key}/coach_brief", f"provided brief task ({t['type']}): {t['text']}"))
        return out


TOOLS = {
    "get_yesterday": "yesterday's workout and messages",
    "get_sleep": "sleep stats and chart (args: days)",
    "get_adherence": "weekly adherence, completed weeks only (args: weeks)",
    "get_messages": "message pattern: member-initiated messages per week (args: weeks)",
    "get_churn": "computed churn risk with evidence and disagreement with the provided brief",
    "get_status": "readiness, journey stage, injuries, latest check-ins",
    "get_labs": "blood panel and DEXA",
    "get_brief": "the provided morning brief tasks",
    "get_changes": "what changed this week vs last week: sleep, HRV, resting HR, sessions, messages, pain check-ins",
}


def run(tb: Toolbox, name: str, args: dict | None = None) -> ToolResult:
    fn = getattr(tb, name)
    accepted = inspect.signature(fn).parameters  # the planner may send days/weeks to a tool that takes neither
    return fn(**{k: int(v) for k, v in (args or {}).items() if k in ("days", "weeks") and k in accepted})


def as_dict(r: ToolResult) -> dict:
    return {"tool": r.tool, "evidence": [asdict(e) for e in r.evidence], "charts": r.charts, "facts": r.facts}
