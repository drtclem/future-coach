"""Copilot grounding and routing (D5.5, D10, D19). Offline: deterministic planner and writer."""

import pytest

from app.copilot.copilot import ask, grounding_errors
from app.copilot.tools import Evidence, ToolResult


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def text(r):
    return " ".join(p["text"] for p in r["answer"])


def test_yesterday_quotes_the_member_not_the_brief():
    r = ask("jordan", "Congratulate Jordan on yesterday's workout")
    t = text(r)
    assert "2026-06-03" not in t or "Lower Body" in t
    assert '"Knocked out the lower body session! Knee felt okay with the box squats."' in t
    assert "pain-free" not in t  # the brief's stronger claim is never echoed (C6)


def test_every_paragraph_is_cited_and_ids_exist():
    r = ask("jordan", "Give me the morning brief")
    ids = {e["id"] for e in r["evidence"]}
    assert r["answer"] and all(p["evidence"] and set(p["evidence"]) <= ids for p in r["answer"])


def test_partial_week_is_explained_in_adherence_and_churn():
    assert "only 3 of 7 days in" in text(ask("jordan", "Compare adherence over the last 4 weeks"))
    assert "only 3 days in" in text(ask("jordan", "Is she a churn risk?"))


def test_charts_are_built_from_data():
    r = ask("jordan", "Show her sleep this week")
    c = r["charts"][0]
    assert c["series"][0]["values"][-7:] == [6.1, 5.4, 7.2, 6.0, 5.1, 7.8, 6.3]


def test_message_pattern_is_member_initiated_per_week():
    r = ask("jordan", "Show message pattern")
    assert r["charts"][0]["title"] == "Member-initiated messages per week"


def test_lookup_last_night():
    r = ask("jordan", "What was her sleep last night?")
    assert r["route"]["intent"] == "lookup" and "6.3 h last night" in text(r)


def test_labs_are_context_not_advice():
    assert "care team" in text(ask("jordan", "Any lab concerns?"))


def test_compose_requests_are_delegated_to_the_safe_generator():
    r = ask("jordan", "Build her a 30 minute lower body workout")
    assert r["route"]["intent"] == "compose" and r["workout"]["status"] == "ok"


def test_grounding_check_rejects_invented_quotes_and_uncited_claims():
    res = [
        ToolResult(
            "get_yesterday", evidence=[Evidence("E1", "n", "member on 2026-06-03", quote="Knee felt okay with the box squats.")]
        )
    ]
    assert grounding_errors([{"text": 'She said "my knee is pain-free now"', "evidence": ["E1"]}], res)
    assert grounding_errors([{"text": "She is fine.", "evidence": []}], res)
    assert grounding_errors([{"text": "x", "evidence": ["E9"]}], res)
    assert not grounding_errors([{"text": 'She said "Knee felt okay with the box squats."', "evidence": ["E1"]}], res)


def test_clinical_advice_is_rejected_by_the_grounding_check():
    res = [ToolResult("get_labs", evidence=[Evidence("E1", "n", "vitamin_d_ng_ml 28")])]
    assert grounding_errors([{"text": "Her vitamin D is 28; she could start a supplement.", "evidence": ["E1"]}], res)
    assert grounding_errors([{"text": "Take 2000 IU daily.", "evidence": ["E1"]}], res)
    assert not grounding_errors([{"text": "LDL was 118 mg/dL; worth raising with her care team.", "evidence": ["E1"]}], res)


def test_punctuation_inside_a_quote_is_not_a_fabrication():
    res = [ToolResult("m", evidence=[Evidence("E1", "n", "member", quote="Knee felt okay, legs tired.")])]
    assert not grounding_errors([{"text": 'She said the knee "felt okay," which is progress.', "evidence": ["E1"]}], res)


def test_tools_ignore_planner_args_they_do_not_take():
    """The LLM planner sends days/weeks on every call; a tool without them must not crash (found by the golden set)."""
    from app.copilot.tools import Toolbox, run
    from app.member.model import member_repo

    r = run(Toolbox(member_repo().get("jordan")), "get_changes", {"days": 7, "weeks": 2})
    assert r.tool == "get_changes" and r.evidence
