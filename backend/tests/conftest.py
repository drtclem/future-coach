import os
import tempfile

import pytest

# Never let tests write to the real demo event log.
os.environ.setdefault("FC_EVENTS_PATH", os.path.join(tempfile.mkdtemp(), "events.jsonl"))

from app.graph.store import domain_graph
from app.safety.filter import Injury, InjuryRule, SafetyFilter


@pytest.fixture(scope="session")
def graph():
    return domain_graph()


@pytest.fixture(scope="session")
def sf(graph):
    return SafetyFilter(graph)


@pytest.fixture
def jordan_knee():
    """Jordan's injury as recorded in member-context.json, with the care-team
    note ("avoid deep knee flexion under load and plyometrics") as the cited
    source for her two hard exclusions (D2)."""
    note = "care-team note inj_knee_left (member-context.json)"
    return Injury(
        id="inj_knee_left",
        label="knee (patellofemoral pain)",
        structure="patellofemoral-joint",
        status="recovering",
        condition="pfp",
        side="left",
        extra_rules=(InjuryRule("impact", "exclude", note), InjuryRule("loaded_deep_flexion", "exclude", note)),
    )


def tiers(decisions):
    return {d.name: d.tier for d in decisions.values()}
