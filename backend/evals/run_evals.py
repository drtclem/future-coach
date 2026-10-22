"""Run the golden set: `python -m evals.run_evals [--write-baseline]`.

Uses real LLM calls when provider keys are set (eval mode: no fallback,
temperature 0), otherwise exercises the deterministic paths. Writes
evals/results/latest.json and latest.md, then applies the gate."""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("FC_EVAL_MODE", "1")
os.environ.setdefault("FC_EVENTS_PATH", os.path.join(tempfile.mkdtemp(), "events.jsonl"))

from app.copilot.copilot import ask, grounding_errors  # noqa: E402
from app.copilot.tools import Evidence, ToolResult  # noqa: E402
from app.graph.store import domain_graph  # noqa: E402
from app.llm import available, models_for  # noqa: E402
from app.member.intake import record_message  # noqa: E402
from app.member.model import MemberRepo  # noqa: E402
from app.plan.generate import generate  # noqa: E402
from app.plan.validate import unsafe  # noqa: E402

from . import gate  # noqa: E402
from .cases import CASES, Case, independent_safety  # noqa: E402

OUT = Path(__file__).parent / "results"


def run_case(case: Case) -> dict:
    repo = MemberRepo(domain_graph(), events=Path(tempfile.mkdtemp()) / "e.jsonl")
    for msg in case.setup_messages:
        record_message(repo, repo.get(case.member), msg)
    secrets = [case.text, *case.setup_messages]
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("future_coach").addHandler(handler)
    t = time.perf_counter()
    problems: list[str] = []
    metrics: dict[str, float | None] = {k: None for k in gate.FLOORS}
    try:
        if case.kind == "generate":
            r = generate(case.member, case.text, repo=repo)
        else:
            r = ask(case.member, case.text)  # copilot cases use the seed data only (no setup messages)
        r_w = r.get("workout") if case.kind == "copilot" else None
    finally:
        logging.getLogger("future_coach").removeHandler(handler)
    ms = round((time.perf_counter() - t) * 1000)
    builder = None
    plan_result = r if case.kind == "generate" else r_w
    if case.expect_block:
        ok = plan_result is not None and plan_result.get("status") == "needs_confirmation"
        metrics["fail_closed"] = float(ok)
        if not ok:
            problems.append("expected a confirmation question, got a plan")
    elif plan_result is not None and plan_result.get("status") == "needs_confirmation":
        metrics["schema_valid"] = 0.0
        problems.append("unexpected confirmation question: " + " | ".join(plan_result.get("questions", []))[:300])
    if plan_result is not None and plan_result.get("status") == "ok" and not case.expect_block:
        ok_schema = plan_result.get("status") == "ok" and all(
            {"exercise_id", "name", "sets", "rest_s", "block"} <= set(i) for i in plan_result["plan"]["items"]
        )
        metrics["schema_valid"] = float(ok_schema)
        if not ok_schema:
            problems.append(f"bad plan result: status={plan_result.get('status')}")
        else:
            items = plan_result["plan"]["items"]
            safety = independent_safety(case, items)
            texts = [plan_result["plan"]["summary"]] + [t for i in items for t in [i.get("cue") or "", *i.get("why", [])]]
            safety += ["unsafe wording reached the coach"] if any(unsafe(t) for t in texts) else []
            metrics["safety_respected"] = float(not safety)
            problems += safety
            fill = plan_result["plan"]["est_min"] / max(plan_result["plan"]["budget_min"], 1)
            metrics["plan_fill"] = float(fill >= 0.6 and len(items) >= 3)
            if not metrics["plan_fill"]:
                problems.append(f"plan fill {fill:.0%} with {len(items)} items")
            metrics["citation_present"] = float(bool(plan_result["provenance"]["activities"]))
            if case.extra:
                problems += case.extra(plan_result)
            builder = plan_result["plan"]["builder"]
    if case.kind == "copilot" and r.get("answer") is not None:
        builder = r["builder"]
        paras = r["answer"]
        ev = [ToolResult("all", evidence=[Evidence(**e) for e in r["evidence"]])]
        g = grounding_errors(paras, ev)
        text = " ".join(p["text"] for p in paras)
        metrics["schema_valid"] = float(isinstance(paras, list) and all("text" in p for p in paras))
        metrics["citation_present"] = float(bool(paras) and all(p.get("evidence") for p in paras))
        bad = [w for w in case.must_not_say if w.lower() in text.lower()]
        missing = [w for w in case.must_say if w.lower() not in text.lower()]
        quote_ok = case.must_quote is None or case.must_quote in text
        metrics["grounded"] = float(not g and not bad and quote_ok)
        problems += g + [f"said '{w}'" for w in bad] + ([f"missing quote '{case.must_quote}'"] if not quote_ok else [])
        problems += [f"missing '{w}'" for w in missing]
    if available("mid") and builder is not None and not (case.kind == "copilot" and r.get("route", {}).get("intent") == "lookup"):
        metrics["llm_path"] = float(builder == "llm")
    leaked = [s for s in secrets if len(s) > 12 and s in buf.getvalue()]
    metrics["no_member_text_in_logs"] = float(not leaked)
    if leaked:
        problems.append("member/coach free text found in logs")
    return {
        "id": case.id,
        "why": case.why,
        "kind": case.kind,
        "member": case.member,
        "builder": builder,
        "ms": ms,
        "passed": not problems,
        "problems": problems,
        "metrics": metrics,
    }


def main() -> int:
    OUT.mkdir(exist_ok=True)
    mode = (
        "llm (" + ", ".join(f"{t}={','.join(models_for(t))}" for t in ("small", "mid", "large")) + ")"
        if available("mid")
        else "offline"
    )
    results = [run_case(c) for c in CASES]
    ok, msgs = gate.check(results)
    rates = gate.rates(results)
    (OUT / "latest.json").write_text(json.dumps({"mode": mode, "rates": rates, "results": results}, indent=2) + "\n")
    lines = [f"# Eval results ({mode})", "", "| Case | Kind | Builder | ms | Pass | Problems |", "|---|---|---|---|---|---|"]
    lines += [
        f"| {r['id']} | {r['kind']} | {r['builder'] or '-'} | {r['ms']} | {'✅' if r['passed'] else '❌'} | {'; '.join(r['problems'])[:120]} |"
        for r in results
    ]
    lines += ["", "| Metric | Rate | Floor |", "|---|---|---|"]
    lines += [f"| {m} | {'-' if v is None else f'{v:.0%}'} | {gate.FLOORS[m]:.0%} |" for m, v in rates.items()]
    lines += ["", "**Gate: " + ("PASS" if ok else "FAIL — " + "; ".join(msgs)) + "**"]
    (OUT / "latest.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if "--write-baseline" in sys.argv:
        gate.write_baseline(results)
        print("baseline written (commit it deliberately)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
