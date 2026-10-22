"""Router (D10): a component, not an agent. Rules decide obvious cases; otherwise
the intent the extraction call already returned is used. Low confidence or a
rules/LLM conflict goes to the broadest route (analyst). Routing can never make
a request unsafe: every route that outputs exercises passes the same gate."""

from __future__ import annotations

import re
from dataclasses import dataclass

COMPOSE = re.compile(
    r"\b(build|create|make|give|plan|program|generate|design|write)\b.*\b(workout|session|plan|routine|exercises?|day)\b"
    r"|\b\d+\s*-?\s*min|\bleg day\b|\bupper body\b|\blower[- ]body\b|\bfull[- ]body\b",
    re.I,
)
LOOKUP_Q = re.compile(r"^\s*(what|when|how (much|many|long)|did|is|was)\b", re.I)
LOOKUP_WHEN = re.compile(r"\b(last night|yesterday|today|last|latest|current|her|his)\b", re.I)
LOOKUP_METRIC = re.compile(
    r"\b(sleep|slept|hrv|weigh|weight|heart rate|rhr|rpe|adherence|ldl|hdl|vitamin d|ferritin|crp|hba1c|body fat)\b", re.I
)
ANALYZE = re.compile(
    r"\b(why|compare|trend|pattern|chart|graph|plot|summar|brief|risk|churn|explain|changed?|over the last|week)\b", re.I
)
QUESTION = re.compile(r"\?\s*$|^\s*(what|why|how|when|who|which|is|are|did|does|can|should)\b", re.I)


@dataclass
class Route:
    intent: str  # compose | lookup | analyze | analyze+compose
    confidence: float
    source: str  # rules | llm | rules+llm | fallback
    reason: str


def route(prompt: str, llm: dict | None = None) -> Route:
    compose = (
        bool(COMPOSE.search(prompt))
        and not QUESTION.search(prompt)
        or bool(re.search(r"\b(build|make|give|create)\b.*\b(workout|session|something|plan|routine|exercises?)\b", prompt, re.I))
    )
    lookup = all(p.search(prompt) for p in (LOOKUP_Q, LOOKUP_WHEN, LOOKUP_METRIC))
    analyze = bool(ANALYZE.search(prompt)) or (bool(QUESTION.search(prompt)) and not lookup)
    if compose and analyze and re.search(r"\b(why|explain|summar|compare)\b", prompt, re.I):
        return Route("analyze+compose", 0.9, "rules", "asks for analysis and a workout")
    rules_intent = "compose" if compose else "lookup" if lookup else "analyze" if analyze else None
    if llm:
        li, lc = llm.get("intent"), float(llm.get("confidence") or 0)
        if rules_intent and li and li != rules_intent:
            return Route("analyze", 0.5, "rules+llm", f"rules said {rules_intent}, model said {li}: broadest route")
        if rules_intent:
            return Route(rules_intent, 0.95, "rules+llm", "rules and model agree")
        if li and lc >= 0.6:
            return Route(li, lc, "llm", "model intent")
    if rules_intent:
        return Route(rules_intent, 0.85, "rules", "keyword rules")
    return Route("analyze", 0.4, "fallback", "unclear request: broadest route")
