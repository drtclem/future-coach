"""Router golden cases (D10). Misroutes can never be unsafe, but they should be rare."""

import pytest

from app.router import route

CASES = [
    ("Build her a 30 minute lower body workout", "compose"),
    ("Lower-body exercises that avoid aggravating a knee injury", "compose"),
    ("Full body, no deadlift variations, 40 min", "compose"),
    ("Give me a leg day for Sam", "compose"),
    ("What was her sleep last night?", "lookup"),
    ("How much did she weigh last week?", "lookup"),
    ("Congratulate Jordan on yesterday's workout", "analyze"),
    ("Compare adherence over the last 4 weeks", "analyze"),
    ("Show message pattern", "analyze"),
    ("Why is she slipping?", "analyze"),
    ("Is she a churn risk?", "analyze"),
    ("Why is she slipping, and build her something easier for 20 min", "analyze+compose"),
]


@pytest.mark.parametrize("prompt,intent", CASES)
def test_rules_route(prompt, intent):
    assert route(prompt).intent == intent


def test_rules_llm_conflict_goes_to_the_broadest_route():
    r = route("Build her a 30 minute workout", llm={"intent": "lookup", "confidence": 0.9})
    assert r.intent == "analyze" and r.source == "rules+llm"


def test_unclear_request_falls_back_to_analyst():
    assert route("hmm").intent == "analyze"
