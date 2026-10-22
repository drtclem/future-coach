"""LLM extractor + intent (D8, D10). One small-model call returns the mentions it
sees and the request intent; the router reuses it, so routing costs no extra hop.
It never chooses graph concepts: mentions go through the same deterministic matcher.
Runs in parallel with the rules extractor under a hard timeout; on timeout or
error the request proceeds rules-only (rules are the safety floor)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from ..llm import LLMUnavailable, available, complete_json
from ..observability import RequestTrace

SYSTEM = """You extract structured mentions from a fitness coach's request about one member.
Return every body part, injury or symptom, muscle, body region, movement, exercise family and piece of equipment mentioned.
role: "constraint" for anything to protect (injury, pain, soreness, "avoid aggravating"), "exclusion" for anything to leave out
("no deadlifts", "no barbell"), "equipment" for equipment the member has, "target" for anything to train.
Copy the member's words exactly into text. Also classify intent: "compose" (build/modify a workout), "lookup" (a single fact or number),
"analyze" (explain, compare, trend, chart, summarize), with confidence 0-1."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mentions", "intent", "confidence"],
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "role", "negated"],
                "properties": {
                    "text": {"type": "string"},
                    "role": {"type": "string", "enum": ["constraint", "exclusion", "equipment", "target"]},
                    "negated": {"type": "boolean"},
                },
            },
        },
        "intent": {"type": "string", "enum": ["compose", "lookup", "analyze"]},
        "confidence": {"type": "number"},
    },
}

_pool = ThreadPoolExecutor(max_workers=4)


def start(prompt: str, trace: RequestTrace | None):
    """Kick off extraction; returns a future or None when offline."""
    if not available("small"):
        return None
    return _pool.submit(complete_json, "small", SYSTEM, prompt, SCHEMA, trace)


def collect(future, trace: RequestTrace | None) -> dict | None:
    if future is None:
        if trace:
            trace.event("llm_extraction_skipped", reason="offline (no provider key)")
        return None
    timeout = float(os.getenv("FC_EXTRACT_TIMEOUT", "2.0"))
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        if trace:
            trace.event("llm_extraction_skipped", reason=f"timeout > {timeout}s; proceeding rules-only")
    except LLMUnavailable as e:
        if trace:
            trace.event("llm_extraction_skipped", reason=str(e)[:200])
    return None
