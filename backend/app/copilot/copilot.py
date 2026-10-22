"""AI Copilot (D10, D5.5, D19). Lookup answers single facts from templates; the
Analyst plans tool calls (small model, or keyword rules offline), runs them
deterministically, then writes an answer that may only cite the evidence the
tools returned. A grounding check rejects uncited claims and any quote that is
not verbatim in a source; on failure the deterministic writer answers instead.
"""

from __future__ import annotations

import os
import re

from ..llm import LLMUnavailable, available, complete_json
from ..member.model import Member, member_repo
from ..observability import start_request
from ..plan.generate import generate
from ..plan.validate import UNSAFE_TEXT
from ..router import route
from .tools import TOOLS, Toolbox, ToolResult, as_dict, run

MAX_ROUNDS = 3  # D10 step cap
ANSWER_TIER = os.getenv("FC_ANSWER_TIER", "mid")  # measured: large took up to 25 s for a brief

KEYWORD_PLAN = [
    (
        r"\b(brief|morning|today|catch me up|summar|overview|anything i should know)\b",
        ["get_yesterday", "get_status", "get_churn", "get_sleep"],
    ),
    (r"\b(yesterday|congratulat|last (session|workout))\b", ["get_yesterday"]),
    (r"\b(chang|since last week|vs\.? last week|different)", ["get_changes"]),
    (r"\bsleep|rest(ed)?\b", ["get_sleep"]),
    (r"\b(adherence|consisten|compare|last \d+ weeks|weeks)\b", ["get_adherence"]),
    (r"\b(message|chat|reach(ing)? out|communicat)", ["get_messages"]),
    (r"\b(churn|risk|drop(ping)? off|slipping|quit|engag)", ["get_churn", "get_adherence"]),
    (r"\b(lab|blood|vitamin|ldl|hdl|dexa|body fat|ferritin|crp|hba1c)\b", ["get_labs"]),
    (r"\b(injur|knee|shoulder|back|pain|readiness|ready|status|stage)\b", ["get_status"]),
]


def keyword_plan(q: str) -> list[dict]:
    tools: list[str] = []
    for pat, ts in KEYWORD_PLAN:
        if re.search(pat, q, re.I):
            tools += [t for t in ts if t not in tools]
    days = re.search(r"(\d+)\s*days?", q)
    weeks = re.search(r"(\d+)\s*weeks?", q)
    plan = [{"tool": t, "args": {}} for t in (tools or ["get_status", "get_yesterday"])]
    for p in plan:
        if p["tool"] == "get_sleep" and re.search(r"last night", q, re.I):
            p["args"]["days"] = 1
        elif p["tool"] == "get_sleep" and days:
            p["args"]["days"] = int(days.group(1))
        if p["tool"] in ("get_adherence", "get_messages") and weeks:
            p["args"]["weeks"] = int(weeks.group(1))
    return plan


PLAN_SYSTEM = (
    "You plan read-only tool calls to answer a coach's question about one member. Pick the fewest tools that answer it. "
    "Tools: " + "; ".join(f"{k}: {v}" for k, v in TOOLS.items())
)
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["calls"],
    "properties": {
        "calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tool", "days", "weeks"],
                "properties": {
                    "tool": {"type": "string", "enum": list(TOOLS)},
                    "days": {"type": "integer"},
                    "weeks": {"type": "integer"},
                },
            },
        }
    },
}

ANSWER_SYSTEM = """You are a concise assistant for a fitness coach. Answer using ONLY the evidence items provided.
Every paragraph must list the evidence ids it relies on. Put a member's or coach's words in double quotes ONLY if they appear
verbatim in an evidence "quote". Never upgrade a claim (e.g. do not say "pain-free" if the member said "felt okay").
If evidence is missing, say so, citing the tool's evidence ids that came back empty or closest. If more data is needed, name up to 2 extra tools in need_more (else empty).
Never give medical advice; suggest raising clinical questions with the care team."""
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["paragraphs", "need_more"],
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence"],
                "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
            },
        },
        "need_more": {"type": "array", "items": {"type": "string", "enum": list(TOOLS)}},
    },
}


def grounding_errors(paragraphs: list[dict], results: list[ToolResult]) -> list[str]:
    ev = {e.id: e for r in results for e in r.evidence}
    errors = []
    for p in paragraphs:
        if m := next((m for pat in UNSAFE_TEXT if (m := pat.search(p["text"]))), None):
            errors.append(f"unsafe advice (clinical or push-through-pain) is out of scope: '{m.group(0)}'")
    for p in paragraphs:
        if not p.get("evidence"):
            errors.append(f"uncited paragraph: {p['text'][:60]}")
        for i in p.get("evidence", []):
            if i not in ev:
                errors.append(f"unknown evidence id {i}")
        for q in re.findall(r"“([^”]{6,})”|\"([^\"]{6,})\"", p["text"]):
            q = (q[0] or q[1]).strip(" ,.;:!?'")  # punctuation the writer added around a quote
            if not any(q in (e.quote or "") or q in e.text for e in ev.values()):
                errors.append(f'quote not found verbatim in sources: "{q[:50]}"')
    return errors


def deterministic_answer(m: Member, results: list[ToolResult]) -> list[dict]:
    """Template writer used offline and whenever the LLM answer fails grounding."""
    name = m.first_name
    she = (m.data["profile"].get("pronouns") or "they/them").split("/")[0]
    paras: list[dict] = []
    for r in results:
        ids = [e.id for e in r.evidence]
        if r.tool == "get_yesterday":
            done = [e for e in r.evidence if "completed" in e.text]
            quote = next((e for e in r.evidence if e.quote and "member" in e.text), None)
            if done:
                title, rest = done[0].text.split(": ", 1)[1].split(" completed", 1)
                text = f"Yesterday {name} completed {title}{rest.replace(', ', ' (', 1).replace(': ', '): ', 1)}."
            else:
                text = f"No completed session for {name} yesterday."
            if quote:
                text += f' {she.capitalize()} wrote: "{quote.quote}"'
            paras.append({"text": text, "evidence": ids})
        elif r.tool == "get_sleep" and r.facts and r.facts["n"] == 1:
            paras.append({"text": f"{name} slept {r.facts['avg']} h last night (device).", "evidence": ids})
        elif r.tool == "get_sleep" and r.facts:
            f = r.facts
            paras.append(
                {
                    "text": f"Sleep averaged {f['avg']} h over {f['n']} nights (weeknights {f['weeknight_avg']} h), with "
                    f"{f['nights_7plus']} of {f['n']} nights at 7 h or more; range {f['min']}-{f['max']} h.",
                    "evidence": ids,
                }
            )
        elif r.tool == "get_adherence":
            done, cur = r.facts["completed"], r.facts["current"]
            t = "Completed weeks: " + ", ".join(f"{w['week_of']} {w['pct']}%" for w in done) + "."
            if cur:
                t += f" The current week is only {cur['days_elapsed']} of 7 days in, so its {cur['pct']}% is not counted."
            paras.append({"text": t, "evidence": ids})
        elif r.tool == "get_messages":
            pw = r.facts["per_week"]
            paras.append(
                {
                    "text": "Member-initiated messages per week: "
                    + ", ".join(f"{k}: {v}" for k, v in pw.items())
                    + f". Overall {r.facts['by_author'].get('member', 0)} from {name}, {r.facts['by_author'].get('coach', 0)} from the coach.",
                    "evidence": ids,
                }
            )
        elif r.tool == "get_churn":
            f = r.facts
            t = f"Computed churn risk: {f['level']} (score {f['score']}). " + " ".join(
                e.text + "." for e in r.evidence[:-1] if e.text
            )
            if f["disagreement"]:
                t += " " + f["disagreement"]
            paras.append({"text": t, "evidence": ids})
        elif r.tool == "get_changes":
            paras.append({"text": "This week vs last week: " + "; ".join(e.text for e in r.evidence) + ".", "evidence": ids})
        elif r.tool in ("get_status", "get_labs", "get_brief"):
            t = " ".join(e.text + "." for e in r.evidence)
            if r.tool == "get_labs" and r.evidence:
                t += " Clinical values are context only: worth raising with her care team, not a change to today's plan."
            paras.append({"text": t, "evidence": ids})
    return paras


def ask(member_key: str, question: str) -> dict:
    m = member_repo().get(member_key)
    rt = route(question)
    trace = start_request("copilot", member=member_key, intent=rt.intent, question_length=len(question))
    if rt.intent == "compose":
        trace.finish(delegated="generate")
        return {"route": rt.__dict__, "workout": generate(member_key, question)}
    tb = Toolbox(m)
    results: list[ToolResult] = []
    builder = "deterministic"
    with trace.stage("plan_tools") as st:
        calls = keyword_plan(question)
        if rt.intent == "analyze" and available("small"):
            try:
                planned = complete_json("small", PLAN_SYSTEM, f"Question: {question}", PLAN_SCHEMA, trace)["calls"]
                calls = [{"tool": c["tool"], "args": {k: c[k] for k in ("days", "weeks") if c.get(k)}} for c in planned][
                    :4
                ] or calls
                st["planner"] = "llm"
            except (LLMUnavailable, KeyError):
                st["planner"] = "keywords (llm failed)"
        st["calls"] = [c["tool"] for c in calls]
    paragraphs: list[dict] = []
    feedback = ""
    for rnd in range(MAX_ROUNDS):
        with trace.stage("run_tools", round=rnd + 1):
            done = {r.tool for r in results}
            results += [run(tb, c["tool"], c.get("args")) for c in calls if c["tool"] not in done]
        if rt.intent == "lookup" or not available(ANSWER_TIER):
            break
        with trace.stage("answer", round=rnd + 1) as st:
            payload = [as_dict(r) for r in results]
            try:
                out = complete_json(
                    ANSWER_TIER,
                    ANSWER_SYSTEM,
                    f"Question: {question}\nMember: {m.first_name}\nEvidence: {payload}{feedback}",
                    ANSWER_SCHEMA,
                    trace,
                )
            except LLMUnavailable:
                break
            errs = grounding_errors(out["paragraphs"], results)
            st["grounding_errors"] = [e.split(":")[0] for e in errs]  # kinds only: errors quote member text
            if not errs:
                paragraphs, builder = out["paragraphs"], "llm"
            need = [t for t in out.get("need_more", []) if t not in {r.tool for r in results}]
            if errs and not paragraphs and not need and rnd < MAX_ROUNDS - 1:  # one repair round with the reasons
                feedback = "\nYour previous answer was rejected: " + "; ".join(errs) + ". Fix exactly these problems."
                calls = []
                continue
            if not need or rnd == MAX_ROUNDS - 1:
                if need:
                    trace.event("step_cap_reached", pending=need)
                break
            calls = [{"tool": t, "args": {}} for t in need]
    if not paragraphs:
        paragraphs = deterministic_answer(m, results)
    if rt.intent == "analyze+compose":
        workout = generate(member_key, question)
    else:
        workout = None
    out = trace.finish(builder=builder, tools=[r.tool for r in results])
    return {
        "route": rt.__dict__,
        "answer": paragraphs,
        "builder": builder,
        "evidence": [e.__dict__ for r in results for e in r.evidence],
        "charts": [c for r in results for c in r.charts],
        "workout": workout,
        "trace": out,
    }
