"""Gate logic (D18), same shape as clinical-copilot evals/gate.py:
  (a) every case's checks pass, and
  (b) every rubric metric is at its floor and has not regressed more than 5%
      relative to the committed baseline.
A metric is None (not 0) for cases it does not apply to. The baseline is only
ever written by a human (`--write-baseline`), never by a regular run."""

from __future__ import annotations

import json
from pathlib import Path

FLOORS = {
    "schema_valid": 1.0,
    "safety_respected": 1.0,
    "citation_present": 1.0,
    "grounded": 1.0,
    "fail_closed": 1.0,
    "plan_fill": 1.0,  # anti-gaming guard: an empty plan is trivially "safe"
    "no_member_text_in_logs": 1.0,
    "llm_path": 0.8,  # with keys set, the model paths must actually work (not silently fall back); None offline
}
MAX_RELATIVE_REGRESSION = 0.05
FLOOR_ONLY = {"llm_path"}  # moves ~6 points per flaky model reply, so floor only
BASELINE = Path(__file__).parent / "baseline_results.json"


def rates(results: list[dict]) -> dict[str, float | None]:
    out = {}
    for m in FLOORS:
        vals = [r["metrics"][m] for r in results if r["metrics"].get(m) is not None]
        out[m] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def check(results: list[dict]) -> tuple[bool, list[str]]:
    msgs = []
    failed = [r["id"] for r in results if not r["passed"]]
    if failed:
        msgs.append(f"cases failed: {', '.join(failed)}")
    now = rates(results)
    base = json.loads(BASELINE.read_text())["rates"] if BASELINE.exists() else {}
    for m, floor in FLOORS.items():
        v = now[m]
        if v is None:
            continue
        if v < floor:
            msgs.append(f"{m} {v:.0%} below floor {floor:.0%}")
        b = base.get(m)
        if b and m not in FLOOR_ONLY and (b - v) / b > MAX_RELATIVE_REGRESSION:
            msgs.append(f"{m} regressed {b:.0%} -> {v:.0%}")
    return not msgs, msgs


def write_baseline(results: list[dict]) -> None:
    BASELINE.write_text(json.dumps({"rates": rates(results), "cases": len(results)}, indent=2) + "\n")
