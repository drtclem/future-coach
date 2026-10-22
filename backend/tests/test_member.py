"""Member graph, longitudinal signals, check-ins and async messages (D5, D11-D13)."""

import json

import pytest

from app.graph.store import REPO
from app.member.intake import record_checkin, record_message
from app.member.model import MemberRepo
from app.member.signals import churn, completed_weeks, journey, readiness


@pytest.fixture
def repo(graph, tmp_path):
    return MemberRepo(graph, events=tmp_path / "events.jsonl")


def test_provided_member_data_is_preserved_in_the_extension():
    src = json.loads((REPO / "data" / "member-context.json").read_text())
    ext = json.loads((REPO / "data" / "members" / "jordan.json").read_text())
    for w in src["workout_history"]:
        assert w in ext["workout_history"]
    assert [d["sleep_hours"] for d in ext["biomarkers"]["daily"][-7:]] == src["biomarkers"]["sleep_hours_last_7_days"]


def test_injury_note_becomes_condition_and_care_team_rules(repo):
    inj = repo.get("jordan").injuries[0]
    assert (inj.condition, inj.structure, inj.status, inj.side) == ("pfp", "patellofemoral-joint", "recovering", "left")
    assert {(r.load_type, r.tier) for r in inj.extra_rules} == {("impact", "exclude"), ("loaded_deep_flexion", "exclude")}


def test_cleared_injury_is_kept_but_inactive(repo, sf):
    priya = repo.get("priya")
    assert {i.condition: i.status for i in priya.injuries} == {"rc-tendinopathy": "recovering", "lbp": "cleared"}


def test_partial_week_is_not_counted_and_brief_disagreement_is_explained(repo):
    j = repo.get("jordan")
    done, cur = completed_weeks(j)
    assert done[-1] == {"week_of": "2026-05-26", "pct": 75} and cur["days_elapsed"] == 3
    c = churn(j)
    assert c["level"] == "elevated" and "only 3 days in" in c["disagreement"]
    assert sum(e["points"] for e in c["evidence"]) == c["score"] <= c["max_score"]  # the card shows each signal's points


def test_journey_stages_differ_by_member(repo):
    assert journey(repo.get("jordan"))[0] == ["established", "at-risk", "rehab"]
    assert journey(repo.get("sam"))[0] == ["onboarding"]
    assert journey(repo.get("priya"))[0] == ["established", "rehab"]


def test_bad_night_lowers_readiness_and_never_raises_it(repo):
    j = repo.get("jordan")
    assert readiness(j).level == "normal"
    record_checkin(repo, j, {"note": "baby was up all night, slept 4 hours"})
    r = readiness(j)
    assert r.level == "low" and r.sleep_last_night == 4.0 and r.sleep_source == "today's check-in" and r.rpe_cap == 6
    record_checkin(repo, j, {"sleep_hours": 10})
    assert readiness(j).rpe_cap <= 8  # a great night never lifts the cap above normal


def test_pain_over_threshold_makes_the_injury_acute_today(repo):
    j = repo.get("jordan")
    out = record_message(repo, j, "left knee is cranky this morning, 6/10")
    assert out["readiness"].acute_today == ["inj_knee_left"]
    assert out["reply_to_member"] == "Thanks for letting us know. Your coach has been notified."


def test_new_area_pain_asks_the_coach(repo):
    out = record_message(repo, repo.get("jordan"), "my wrist hurts")
    assert any("new area" in f for f in out["flags"])


def test_async_message_extracts_time_and_acknowledges_with_a_template(repo):
    out = record_message(repo, repo.get("jordan"), "only have 20 min today")
    assert out["extracted"]["time_available_min"] == 20
    assert out["reply_to_member"] == "Got it, today's session will fit in 20 min."


def test_events_are_append_only_and_replayed(graph, tmp_path):
    ev = tmp_path / "e.jsonl"
    r1 = MemberRepo(graph, events=ev)
    record_message(r1, r1.get("sam"), "slept 5 hours")
    r2 = MemberRepo(graph, events=ev)
    assert readiness(r2.get("sam")).sleep_last_night == 5.0


def test_member_endpoint_shows_evidence():
    from fastapi.testclient import TestClient

    from app.main import app

    body = TestClient(app).get("/api/members/jordan").json()
    assert body["churn"]["evidence"] and body["injuries"][0]["how_read"]
