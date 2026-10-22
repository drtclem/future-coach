"""Observability (D18), modeled on the clinical-copilot TurnObserver.

Every request gets a request id at the moment it arrives. It seeds the Langfuse
trace id, so structured logs and the Langfuse UI line up; either alone is enough
to reconstruct a request. Without LANGFUSE_* keys nothing is sent anywhere and
the structured JSON log (stdout) is the full record.

Member free text is never logged; lengths and ids are.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("future_coach")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def log(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


def langfuse_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


_client = None


def _langfuse():
    global _client
    if _client is None and langfuse_enabled():
        from langfuse import Langfuse  # optional at runtime

        _client = Langfuse(host=os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"))
    return _client


@dataclass
class RequestTrace:
    request_id: str
    route: str
    stages: list[dict] = field(default_factory=list)  # {stage, ms, ...}
    llm_calls: list[dict] = field(default_factory=list)  # {tier, model, attempt, ok, ms, tokens, cost_usd, error}
    events: list[dict] = field(default_factory=list)
    _span: Any = None
    _t0: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str, **meta: Any):
        t = time.perf_counter()
        child = self._span.start_observation(name=name, as_type="span", metadata=meta) if self._span else None
        rec = {"stage": name, **meta}
        try:
            yield rec
        finally:
            rec["ms"] = round((time.perf_counter() - t) * 1000, 1)
            self.stages.append(rec)
            log("stage", request_id=self.request_id, **rec)
            if child is not None:
                child.update(metadata=rec)
                child.end()

    def llm(self, **call: Any) -> None:
        self.llm_calls.append(call)
        log("llm_call", request_id=self.request_id, **call)
        if self._span is not None:
            g = self._span.start_observation(
                name=f"llm:{call.get('tier')}",
                as_type="generation",
                model=call.get("model"),
                metadata={k: v for k, v in call.items() if k not in ("model",)},
            )
            g.end()

    def event(self, name: str, **fields: Any) -> None:
        self.events.append({"event": name, **fields})
        log(name, request_id=self.request_id, **fields)

    def snapshot(self, **summary: Any) -> dict:
        """The trace so far, without closing it (used for the quick draft plan)."""
        return {
            "request_id": self.request_id,
            "route": self.route,
            "total_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "stages": list(self.stages),
            "llm_calls": list(self.llm_calls),
            "cost_usd": round(sum(c.get("cost_usd") or 0 for c in self.llm_calls), 6),
            **summary,
        }

    def finish(self, **summary: Any) -> dict:
        out = self.snapshot(**summary)
        total = out["total_ms"]
        log("request_finished", **{k: v for k, v in out.items() if k not in ("stages", "llm_calls")})
        if self._span is not None:
            self._span.update(
                output={k: v for k, v in summary.items() if k in ("builder", "exercise_count", "blocking")},
                metadata={"total_ms": total, "cost_usd": out["cost_usd"]},
            )
            self._span.end()
        return out


def start_request(route: str, member: str | None = None, request_id: str | None = None, **meta: Any) -> RequestTrace:
    rid = request_id or uuid.uuid4().hex[:16]
    log("request_started", request_id=rid, route=route, member=member, **meta)
    span = None
    client = _langfuse()
    if client is not None:
        try:
            span = client.start_observation(
                trace_context={"trace_id": client.create_trace_id(seed=rid)},
                name=route,
                as_type="agent",
                metadata={"request_id": rid, "member": member, **meta},
            )
        except Exception as e:  # observability must never break a request
            log("langfuse_start_failed", request_id=rid, error=str(e))
    return RequestTrace(rid, route, _span=span)


def attach_feedback(request_id: str, rating: str, comment: str | None = None) -> bool:
    """Coach thumbs up/down on a plan -> Langfuse score on that request's trace."""
    log("coach_feedback", request_id=request_id, rating=rating, has_comment=bool(comment))
    client = _langfuse()
    if client is None:
        return False
    try:
        client.create_score(
            trace_id=client.create_trace_id(seed=request_id),
            name="coach_feedback",
            value=1.0 if rating == "up" else 0.0,
            data_type="BOOLEAN",
            comment=comment,
        )
        return True
    except Exception:
        log("feedback_langfuse_attach_failed", request_id=request_id)
        return False
