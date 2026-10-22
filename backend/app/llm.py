"""LLM access through LiteLLM (D17): tiered models, cross-provider fallback,
structured output, per-attempt telemetry.

Tiers (D10): small = extraction/routing/lookup, mid = composer, large = analyst.
Each tier is a list tried in order (primary, then fallback provider). If no
provider key is set, `available()` is False and callers use their
deterministic path (offline mode). Eval mode (FC_EVAL_MODE=1) disables
fallback and pins temperature 0 so a run scores exactly one model.
"""

from __future__ import annotations

import json
import os
import time

import json_repair

from .observability import RequestTrace

DEFAULT_TIERS = {
    "small": ["anthropic/claude-haiku-5-5", "openai/gpt-5-mini"],
    "mid": ["anthropic/claude-sonnet-5-5", "openai/gpt-5.4"],
    "large": ["anthropic/claude-opus-5-5", "openai/gpt-5.4"],
}
TIMEOUTS = {"small": 4.0, "mid": 20.0, "large": 45.0}


class LLMUnavailable(Exception):
    pass


def _has_key(model: str) -> bool:
    provider = model.split("/", 1)[0]
    return bool(os.getenv({"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider, "_NONE_")))


def models_for(tier: str) -> list[str]:
    env = os.getenv(f"FC_MODELS_{tier.upper()}")
    chain = [m.strip() for m in env.split(",")] if env else DEFAULT_TIERS[tier]
    chain = [m for m in chain if _has_key(m)]
    return chain[:1] if os.getenv("FC_EVAL_MODE") == "1" else chain


def available(tier: str = "mid") -> bool:
    return bool(models_for(tier))


def _parse_json(text: str) -> tuple[dict, bool]:
    """Strict parse first; on malformed JSON (seen from the small tier: a stray quote or comma), repair it.
    A repaired plan is still checked field by field by the validator, so leniency here can't loosen safety."""
    body = text[text.find("{") : text.rfind("}") + 1]
    try:
        return json.loads(body), False
    except json.JSONDecodeError:
        data = json_repair.loads(body or text)
        if not isinstance(data, dict) or not data:
            raise
        return data, True


def complete_json(
    tier: str,
    system: str,
    user: str,
    schema: dict,
    trace: RequestTrace | None = None,
    timeout: float | None = None,
    max_tokens: int = 2000,
) -> dict:
    """One structured call with fallback across providers. Raises LLMUnavailable
    when every model in the tier failed or none is configured."""
    import litellm  # imported lazily: offline mode never needs it

    litellm.drop_params = True  # e.g. Claude 5.5 accepts only temperature=1: drop it rather than fail ("where supported")
    chain = models_for(tier)
    if not chain:
        raise LLMUnavailable(f"no provider key configured for tier '{tier}'")
    last = None
    for attempt, model in enumerate(chain, 1):
        t = time.perf_counter()
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
                timeout=timeout or TIMEOUTS[tier],
                max_tokens=max_tokens,
                temperature=0,
            )
            text = resp.choices[0].message.content or ""
            data, repaired = _parse_json(text)
            usage = getattr(resp, "usage", None)
            cost = None
            try:
                cost = litellm.completion_cost(completion_response=resp)
            except Exception:
                pass  # shortcut: unknown price -> None; set FC prices in config if a model is missing from LiteLLM's map
            if trace:
                trace.llm(
                    tier=tier,
                    model=model,
                    attempt=attempt,
                    ok=True,
                    json_repaired=repaired,
                    ms=round((time.perf_counter() - t) * 1000),
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                    cost_usd=cost,
                )
            return data
        except Exception as e:  # record every attempt, then try the next provider
            last = e
            if trace:
                trace.llm(
                    tier=tier,
                    model=model,
                    attempt=attempt,
                    ok=False,
                    ms=round((time.perf_counter() - t) * 1000),
                    error=type(e).__name__ + ": " + str(e)[:200],
                )
    raise LLMUnavailable(f"all models failed for tier '{tier}': {last}")
