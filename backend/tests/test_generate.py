"""Generator pipeline, validator red-team and re-planning (D9, D13, D14). Offline: the
deterministic builder is exercised here; LLM composition is covered by the golden-set job."""

import pytest

from app.member.intake import record_message
from app.member.model import MemberRepo
from app.plan.builder import Item, Plan
from app.plan.catalog import catalog
from app.plan.generate import generate, replan_if_needed
from app.plan.validate import validate


@pytest.fixture
def repo(graph, tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY"):
        monkeypatch.delenv(k, raising=False)
    return MemberRepo(graph, events=tmp_path / "events.jsonl")


def names(result):
    return {i["name"] for i in result["plan"]["items"]}


def test_knee_scenario_plan_is_safe_and_fits(repo):
    r = generate("jordan", "Lower-body exercises that avoid aggravating a knee injury", repo=repo)
    assert r["status"] == "ok" and r["plan"]["builder"] == "deterministic"
    excluded = {e["exercise"] for e in r["provenance"]["activities"][1]["generated_excluded"]}
    assert not names(r) & excluded
    assert r["plan"]["est_min"] <= r["plan"]["budget_min"] + 1
    assert any(i["block"] == "warmup" for i in r["plan"]["items"])


def test_default_time_is_recent_actual_not_preference(repo):
    r = generate("jordan", "Upper body", repo=repo)
    assert r["plan"]["budget_min"] == 30  # recent sessions ~29 min; preferred 50 (D5.6)


def test_deadlift_and_equipment_scenarios(repo):
    r = generate("jordan", "Full body, no deadlift variations, 40 min", repo=repo)
    assert r["plan"]["budget_min"] == 40 and not any("Deadlift" in n for n in names(r))
    r = generate("jordan", "She has no barbell, only dumbbells and a kettlebell. Lower body.", repo=repo)
    cat = catalog()
    for n in names(r):
        assert {"Barbell", "Flat Bench", "Box"}.isdisjoint({cat.ex[cat.lookup(n).id].name}), n
    assert "Dumbbell Hip Thrust" in r["substitutions"]  # needs a bench: equivalent alternatives offered


def test_unresolved_safety_concern_blocks_generation(repo):
    r = generate("jordan", "Something's off with her hammy, sore since Saturday. Lower body.", repo=repo)
    assert r["status"] == "needs_confirmation" and r["questions"]


def test_low_readiness_shrinks_the_plan(repo):
    base = generate("jordan", "Upper body, 30 min", repo=repo)
    record_message(repo, repo.get("jordan"), "baby was up all night, slept 4 hours")
    tired = generate("jordan", "Upper body, 30 min", repo=repo)
    assert tired["readiness"]["level"] == "low" and tired["readiness"]["rpe_cap"] == 6
    assert sum(i["sets"] for i in tired["plan"]["items"]) <= sum(i["sets"] for i in base["plan"]["items"])
    assert all((i["rpe_target"] or 0) <= 6 for i in tired["plan"]["items"])


def test_async_message_replans_with_a_diff(repo):
    generate("jordan", "Lower body", repo=repo)
    record_message(repo, repo.get("jordan"), "left knee is cranky this morning, 6/10")
    diff = replan_if_needed("jordan", "member message: knee pain 6/10", repo=repo)
    assert diff["version"] == 2 and diff["reason"].startswith("member message")
    assert any("ACUTE today" in f for f in diff["plan"]["readiness"]["flags"])
    # Evidence-based rule table: shallow knee loading stays allowed for PFP even when acute; impact/deep stay out.
    assert not {"Static Jump", "Dumbbell Goblet Split Squat"} & names(diff["plan"])


def test_journey_changes_the_prescription(repo):
    sam = generate("sam", "Full body, 45 min", repo=repo)
    assert all(i["sets"] <= 2 for i in sam["plan"]["items"] if i["block"] == "main")  # onboarding: lower volume


# --- validator red-team (D18 floor: 100%) --------------------------------------
@pytest.fixture
def safe(repo):
    from app.graph.store import domain_graph
    from app.member.signals import journey
    from app.plan.candidates import score
    from app.resolver.resolver import Resolver
    from app.safety.filter import SafetyFilter

    j = repo.get("jordan")
    res = Resolver(domain_graph()).resolve("lower body", known_injuries=j.injuries)
    c, _ = Resolver(domain_graph()).constraints(res, profile_equipment=j.data["equipment_available"])
    return score(catalog(), SafetyFilter(domain_graph()).evaluate(c), res, j, journey(j)[0], set())


def item(ex_id, name, block="main", sets=3, rpe=7):
    return Item(ex_id, name, block, sets, 8, None, 60, rpe)


def test_validator_drops_hallucinated_exercises(safe):
    p, repairs = validate(Plan([item("made-up-id", "Quantum Squat")], 30, "llm"), catalog(), safe, 8)
    assert not p.items and "hallucinated" in repairs[0]


def test_validator_replaces_excluded_exercises(safe):
    p, repairs = validate(Plan([item("01ff62bc-e887-49e4-9cc8-bcd367b34cfd", "Static Jump")], 30, "llm"), catalog(), safe, 8)
    assert all(i.exercise_id in {c.ex.id for c in safe} for i in p.items)
    assert "not in the safe set" in repairs[0]


def test_validator_enforces_rpe_cap_duplicates_and_time(safe):
    c = safe[0].ex
    p, repairs = validate(
        Plan(
            [item(c.id, c.name, rpe=9), item(c.id, c.name)] + [item(x.ex.id, x.ex.name, "accessory", 4) for x in safe[1:12]],
            20,
            "llm",
        ),
        catalog(),
        safe,
        7,
    )
    assert p.items[0].rpe_target == 7 and len({i.exercise_id for i in p.items}) == len(p.items)
    assert p.est_min <= 21


def test_time_fill_never_adds_volume_to_injury_modified_work(repo):
    r = generate("priya", "No barbell today, only dumbbells and a kettlebell. Upper body.", repo=repo)
    modified = [i for i in r["plan"]["items"] if i["cue"]]
    assert modified and all(i["sets"] <= 3 for i in modified)  # shoulder-cued press stays at the prescribed dose
    repairs = " ".join(r["provenance"]["activities"][-1]["repairs"])
    assert not any(i["name"] in repairs for i in modified)  # fill never adds or pads injury-modified exercises
    assert r["plan"]["est_min"] >= 0.6 * r["plan"]["budget_min"]  # the gate's plan_fill floor still holds


def test_fill_pads_uninjured_accessories_when_main_work_is_injury_modified():
    cat = catalog()
    a, b = list(cat.ex)[:2]
    plan = Plan(
        [Item(a, "A", "main", 3, 8, None, 75, 7, cue="shoulder cue"), Item(b, "B", "accessory", 2, 12, None, 45, 7)],
        30,
        "llm",
        "",
    )
    cues = {a: "shoulder cue", b: None}  # the injury modification comes from the graph candidate
    safe = [type("C", (), {"ex": cat.ex[x], "block": "main", "score": 0, "cue": cues[x]})() for x in (a, b)]  # minimal stand-in
    out, repairs = validate(plan, cat, safe, 8, readiness=object())
    assert out.items[0].sets == 3  # injury-modified main work keeps its dose
    assert out.items[1].sets > 2 and any("set added" in r for r in repairs)


# --- red team: a model that returns everything wrong at once ---------------------------------


def _malicious_plan(cands):
    cued = next(c for c in cands if c.cue)  # an exercise carrying an injury cue from the graph
    plain = next(c for c in cands if not c.cue and c.block == "main" and c.ex.id != cued.ex.id)
    bad = "Push through the pain, it's fine. Take 5000 IU vitamin D before training."
    items = [
        Item("not-a-real-exercise", "Imaginary Lift", "main", 3, 8, None, 75, 7),
        Item(cued.ex.id, cued.ex.name, "main", 20, 300, None, 0, 10, cue=bad, why=[bad]),
        Item(plain.ex.id, plain.ex.name, "main", 3, 0, 0, 75, 7),
        Item(plain.ex.id, plain.ex.name, "accessory", 2, 12, None, 45, 7),
    ]
    return Plan(items, 30, "llm", "No pain, no gain today."), cued


def test_validator_neutralizes_a_malicious_model_plan(repo, monkeypatch):
    seen = {}
    monkeypatch.setattr("app.plan.generate.compose", lambda prompt, cands, *a, **k: seen.setdefault("cands", cands) and None)
    generate("priya", "Upper body, 30 min", repo=repo)
    plan, cued = _malicious_plan(seen["cands"])
    out, repairs = validate(plan, catalog(), seen["cands"], 6)
    by = {i.exercise_id: i for i in out.items}
    assert "not-a-real-exercise" not in by  # hallucinated ID dropped
    it = by[cued.ex.id]
    assert it.cue == cued.cue  # the graph's safety cue survives; the model's text doesn't
    assert not any("pain" in w.lower() or "IU" in w for w in it.why)
    assert (it.sets, it.reps, it.rest_s, it.rpe_target) == (6, 30, 30, 6)  # clamped, and capped to readiness
    assert [i.block for i in out.items] == ["main", "accessory"]  # the no-dose copy is dropped, so the other copy stays
    assert out.summary == ""
    text = " ".join(repairs)
    assert "Push through" not in text and "vitamin" not in text  # repairs never echo model text into logs


def test_malicious_model_output_falls_back_to_the_deterministic_builder(repo, monkeypatch):
    calls = []

    def evil(prompt, cands, *a, **k):
        calls.append(1)
        return _malicious_plan(cands)[0]

    monkeypatch.setattr("app.plan.generate.compose", evil)
    r = generate("priya", "Upper body, 30 min", repo=repo)
    assert len(calls) == 2 and r["plan"]["builder"] == "deterministic"  # rejected twice, then the floor
    shown = " ".join([r["plan"]["summary"]] + [f"{i['cue']} {' '.join(i['why'])}" for i in r["plan"]["items"]])
    assert "Push through" not in shown and "IU" not in shown


def test_unsafe_wording_guard():
    from app.plan.validate import unsafe

    for bad in ("Push through the pain", "push through the knee pain", "no pain, no gain", "take 5000 IU daily"):
        assert unsafe(bad), bad
    for ok in ("Keep the range pain-tolerable.", "Stop if pain rises above 3/10.", "LDL was 118 mg/dL"):
        assert not unsafe(ok), ok


def test_every_exercise_gets_a_drawn_pictogram():
    from app.plan.catalog import catalog
    from app.plan.glyph import FALLBACK, glyph

    cat = catalog()
    missing = [e.name for e in cat.ex.values() if glyph(e) == FALLBACK]
    assert not missing, missing
    assert glyph(cat.lookup("Dumbbell Goblet Split Squat")) == "lunge"  # most specific pattern wins over "squat"
    assert glyph(cat.lookup("Kettlebell Goblet Box Squat")) == "boxsquat"


def test_stream_sends_a_validated_draft_first_then_the_final_plan(monkeypatch):
    """With a composer model available, the coach sees a safe draft before the model answers."""
    import json

    from fastapi.testclient import TestClient

    from app.main import app
    from app.plan import generate as gen

    monkeypatch.setattr(gen, "llm_available", lambda tier: True)
    monkeypatch.setattr(gen, "compose", lambda *a, **k: None)  # the "model" fails, so the final plan is the builder's
    r = TestClient(app).post(
        "/api/members/jordan/generate/stream", json={"prompt": "Lower-body exercises that avoid aggravating a knee injury"}
    )
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert [e.get("draft", False) for e in events] == [True, False]
    draft, final = events
    assert "version" not in draft and final["version"] >= 1  # only the final plan is stored as a version
    left_out = {x["exercise"] for x in final["provenance"]["activities"][1]["generated_excluded"]}
    assert left_out and not left_out & {i["name"] for i in draft["plan"]["items"]}  # the draft passed the same safety filter
