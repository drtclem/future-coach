"""Check-ins and async member messages (D12, D13).

Free text goes through the same resolver as coach prompts, so "baby was up all
night, slept 4 hours" and "knee is cranky, 6/10" become structured observations.
Inputs can only add caution: they lower readiness or add constraints, never
loosen a safety rule. Replies to the member are fixed acknowledgements; nothing
clinical is ever generated for the member (D19).
"""

from __future__ import annotations

import re
from datetime import datetime

from ..graph.ns import local
from .model import Member, MemberRepo
from .signals import PARAMS, readiness

ONE_OFF_CAUSES = ("baby", "kid", "deadline", "travel", "flight", "sick", "party", "late night", "jet lag", "work")


def parse_note(repo: MemberRepo, text: str) -> dict:
    """Structured fields from free text. Unparsed text is kept verbatim as the note."""
    out: dict = {"note": text}
    t = text.lower()
    m = re.search(r"(?:slept|sleep|got)\D{0,12}?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b", t) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:h|hrs|hours?)\s+(?:of\s+)?sleep", t
    )
    if m:
        out["sleep_hours"] = float(m.group(1))
    cause = next((c for c in ONE_OFF_CAUSES if c in t), None)
    if cause:
        out["context"] = f"one-off cause mentioned: '{cause}'"
    res = repo.resolver.resolve(text)
    if res.time_min:
        out["time_available_min"] = res.time_min
    equipment = [local(x.concept) for x in res.of("equipment", "equipment")]
    if equipment:
        out["equipment_today"] = equipment
    score = re.search(r"(\d{1,2})\s*/\s*10", t)
    for c in res.of("constraint", "structure", "condition"):
        area = local(repo.resolver.affects.get(c.concept, c.concept)).replace("-", " ")
        out["pain"] = {"area": f"{c.side + ' ' if c.side else ''}{area}", "score": int(score.group(1)) if score else None}
    if res.blocking:
        out["unresolved_concern"] = res.blocking
    return out


def acknowledgement(fields: dict, flags: list[str]) -> str:
    """Fixed templates only (D19)."""
    if fields.get("pain") or fields.get("unresolved_concern") or any("ACUTE" in f for f in flags):
        return "Thanks for letting us know. Your coach has been notified."
    if fields.get("time_available_min"):
        return f"Got it, today's session will fit in {fields['time_available_min']} min."
    if flags:
        return "Got it, today's session has been adjusted."
    return "Got it, thanks!"


def record_checkin(repo: MemberRepo, m: Member, payload: dict, source: str = "self-report") -> dict:
    fields = parse_note(repo, payload["note"]) if payload.get("note") else {}
    fields.update({k: v for k, v in payload.items() if v is not None})  # explicit form fields win over parsed text
    fields.setdefault("ts", datetime.combine(m.as_of, datetime.now().time()).isoformat(timespec="seconds"))
    fields["source"] = source
    if fields.get("pain") and fields["pain"].get("score") is None:
        fields["pain"]["score"] = PARAMS["pain_acute_threshold"]  # unknown severity: assume at threshold (fail closed)
    repo.append({"type": "checkin", "member": m.key, "payload": fields})
    r = readiness(m)
    flags = list(r.flags)
    if fields.get("unresolved_concern"):
        flags.append("unresolved concern in the note: coach must confirm before the next plan")
    if fields.get("pain") and not any(fields["pain"]["area"].split()[-1] in (i.structure + i.label) for i in m.injuries):
        flags.append(f"pain reported in a new area ({fields['pain']['area']}): coach must confirm before the next plan")
    return {
        "recorded": fields,
        "readiness": r,
        "flags": flags,
        "reply_to_member": acknowledgement(fields, flags),
        "node": m.node("checkin", fields["ts"]),
    }


def record_message(repo: MemberRepo, m: Member, text: str, ts: str | None = None) -> dict:
    ts = ts or datetime.combine(m.as_of, datetime.now().time()).isoformat(timespec="seconds")
    msg = {"ts": ts, "from": "member", "text": text, "channel": "async"}
    repo.append({"type": "message", "member": m.key, "payload": msg})
    fields = parse_note(repo, text)
    structured = {k: v for k, v in fields.items() if k != "note"}
    result: dict = {"message_node": m.node("message", ts), "extracted": structured}
    if structured:  # the message carried plan-relevant data: record it as a derived check-in (D13)
        result.update(
            record_checkin(
                repo, m, {**structured, "note": text, "ts": ts, "derived_from": m.node("message", ts)}, source="member-async"
            )
        )
    else:
        result["reply_to_member"] = acknowledgement({}, [])
    return result
