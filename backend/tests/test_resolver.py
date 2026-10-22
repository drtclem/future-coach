"""Resolver golden set (LLM-free pass). Each case states why it exists."""

import json
from pathlib import Path

import pytest

from app.graph.ns import local
from app.resolver.resolver import Resolver

CASES = json.loads((Path(__file__).parents[1] / "evals" / "resolver_cases.json").read_text())


@pytest.fixture(scope="module")
def resolver(graph):
    return Resolver(graph)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_resolver_case(resolver, case):
    res = resolver.resolve(case["prompt"])
    exp = case["expect"]
    got = {role: {local(m.concept) for m in res.of(role)} for role in ("constraint", "target", "exclusion", "equipment")}
    for role in ("constraint", "target", "exclusion", "equipment"):
        if role in exp:
            if exp[role] == []:
                assert not got[role], f"{case['why']}: unexpected {role} {got[role]}"
            else:
                assert set(exp[role]) <= got[role], f"{case['why']}: {role} got {got[role]}"
    every = {local(m.concept) for m in res.mentions if m.concept}
    for c in exp.get("not_concepts", []):
        assert c not in every, case["why"]
    if "blocking" in exp:
        assert bool(res.blocking) == exp["blocking"], f"{case['why']}: blocking={res.blocking}"
    if "time_min" in exp:
        assert res.time_min == exp["time_min"]
    if "equipment_only" in exp:
        assert res.equipment_only == exp["equipment_only"]
    for name, qty in exp.get("quantity", {}).items():
        assert any(local(m.concept) == name and m.quantity == qty for m in res.mentions)
    for name, side in exp.get("side", {}).items():
        assert any(local(m.concept) == name and m.side == side for m in res.mentions)


def test_constraint_precision_is_perfect(resolver):
    """D18 floor: no case produces a constraint it should not (a false constraint is a wrong plan)."""
    for case in CASES:
        if "constraint" in case["expect"]:
            got = {local(m.concept) for m in resolver.resolve(case["prompt"]).of("constraint")}
            assert got <= set(case["expect"]["constraint"]), case["id"]


def test_known_injury_is_reused_not_duplicated(resolver, sf, jordan_knee):
    res = resolver.resolve("lower body, avoid aggravating her knee", known_injuries=[jordan_knee])
    c, notes = resolver.constraints(res)
    assert [i.id for i in c.injuries] == ["inj_knee_left"]
    assert any("recorded injury" in n for n in notes)


def test_new_complaint_fails_closed_as_acute(resolver, sf):
    c, notes = resolver.constraints(resolver.resolve("her wrist is bothering her"))
    assert c.injuries[0].status == "acute" and c.injuries[0].condition == "unspecified-complaint"
    excluded = {d.name for d in sf.evaluate(c).values() if d.tier == "exclude"}
    assert "Push-Up to Knee-Drive" in excluded  # loads the wrist


def test_equipment_statement_drives_the_filter(resolver, sf):
    c, _ = resolver.constraints(
        resolver.resolve("She has no barbell, only dumbbells and a kettlebell"), profile_equipment=["Flat Bench", "Yoga Mat"]
    )
    assert c.equipment == ["dumbbell", "kettlebell"]  # coach statement overrides the profile for this plan
    t = {d.name: d.tier for d in sf.evaluate(c).values()}
    assert t["Double Kettlebell Front Squat"] == "exclude" and t["Kettlebell Goblet Squat"] == "allow"


def test_llm_can_add_caution_but_never_remove_it(resolver):
    res = resolver.resolve("work her shoulders", llm_mentions=[{"text": "shoulders", "role": "avoid"}])
    assert [m.role for m in res.mentions if local(m.concept) == "shoulder"] == ["constraint"]
    assert any("disagreed" in n for n in res.notes)
    res = resolver.resolve("her shoulder hurts", llm_mentions=[{"text": "shoulder", "role": "target"}])
    assert [m.role for m in res.mentions if local(m.concept) == "shoulder"] == ["constraint"]


def test_llm_unresolved_constraint_blocks(resolver):
    res = resolver.resolve("lower body", llm_mentions=[{"text": "funny feeling in her hammy", "role": "injury"}])
    assert res.blocking


def test_llm_mention_with_extra_words_still_resolves(resolver):
    res = resolver.resolve("lower body today", llm_mentions=[{"text": "his knee is bothering him", "role": "constraint"}])
    assert not res.blocking and any(local(m.concept) == "knee" and m.role == "constraint" for m in res.mentions)


def test_llm_symptom_only_mention_does_not_block_when_area_is_known(resolver):
    for text in ("bothering", "bothering him", "40 min"):  # real-model runs returned these as constraints
        res = resolver.resolve("lower body, his knee is bothering him", llm_mentions=[{"text": text, "role": "constraint"}])
        assert not res.blocking
    res = resolver.resolve("lower body", llm_mentions=[{"text": "her hammy", "role": "constraint"}])
    assert res.blocking  # an unknown body area still fails closed


# --- embedding pass (third pass after exact and fuzzy) --------------------------------------
def _embeddings():
    from app.resolver import embed

    if not embed.available():
        pytest.skip("embedding model not available (offline first run)")


def test_embedding_resolves_body_slang_targets(resolver):
    _embeddings()
    res = resolver.resolve("Upper body with some tummy work, plus a bit of booty")
    got = {m.text: (m.concept.rsplit("/", 1)[-1], m.pass_) for m in res.mentions}
    assert got["tummy"] == ("core", "embedding") and got["booty"] == ("glutes", "embedding")


def test_embedding_never_resolves_a_safety_concern_only_suggests(resolver):
    _embeddings()
    res = resolver.resolve("Something's off with her hammy, sore since Saturday")
    assert not [m for m in res.mentions if m.pass_ == "embedding"]  # no silent guess in a pain sentence
    assert res.blocking and "Did you mean the hamstrings?" in res.blocking[0]


def test_embedding_ignores_filler_and_ambiguous_words(resolver):
    _embeddings()
    res = resolver.resolve("Full body workout, focus on strength, 30 minutes")
    assert not [m for m in res.mentions if m.pass_ == "embedding"]
    spine = resolver.resolve("His spine has been achy")
    assert "lumbar spine or the cervical spine" in spine.blocking[0]  # too close to call: ask, naming both
