"""LLM-free safety suite: the three required scenarios plus the traps from
SPEC_REVIEW.md. These block merge (D18)."""

from dataclasses import replace

from conftest import tiers

from app.safety.filter import Constraints, Injury

JUMPS = [
    "Static Jump",
    "Vertical Jump to Broad Jump",
    "BOSU Step Over",
    "Jumping Jack",
    "Jump Rope - Single-Leg",
    "Med Ball Scoop Toss",
]
DEEP_KNEE = [
    "Dumbbell Goblet Split Squat",
    "RNT Split Squat",
    "Med Ball Split Squat",
    "Alternating Dumbbell Racked Crossback Lunge",
    "Kettlebell Goblet Cyclist Squat",
    "Kettlebell Goblet Squat",
    "Wall Sit",
    "Barbell Racked Forward Lunge",
]
DEADLIFTS = {
    "Kettlebell Romanian Deadlift",
    "Dumbbell Romanian Deadlift",
    "Single-Leg Dumbbell Romanian Deadlift",
    "Barbell Conventional Deadlift",
    "Trap Bar Deadlift",
}


# --- scenario 1: lower body that avoids aggravating a knee injury ------------
def test_knee_excludes_impact_and_deep_flexion(sf, jordan_knee):
    t = tiers(sf.evaluate(Constraints(injuries=[jordan_knee])))
    for name in JUMPS + DEEP_KNEE:
        assert t[name] == "exclude", name


def test_knee_keeps_the_rehab_exercises(sf, jordan_knee):
    t = tiers(sf.evaluate(Constraints(injuries=[jordan_knee])))
    for name in ["Kettlebell Goblet Box Squat", "Dumbbell Step-Up (low box)", "Dumbbell Hip Thrust", "Dumbbell Glute Bridge"]:
        assert t[name] == "allow", name


def test_kneeling_is_not_knee_loading(sf, jordan_knee):
    t = tiers(sf.evaluate(Constraints(injuries=[jordan_knee])))
    for name in ["Cow Pose", "High Plank Bird Dog", "Half-Kneeling Dumbbell Press", "Kneeling Stability Ball Lat Stretch"]:
        assert t[name] == "allow", name


def test_hip_work_is_upranked_for_pfp(sf, jordan_knee):
    d = {x.name: x for x in sf.evaluate(Constraints(injuries=[jordan_knee])).values()}
    assert d["Dumbbell Hip Thrust"].uprank
    assert not d["Dumbbell Floor Press"].uprank


def test_every_exclusion_has_a_traceable_reason(sf, jordan_knee):
    for d in sf.evaluate(Constraints(injuries=[jordan_knee])).values():
        if d.tier == "exclude":
            r = max(d.reasons, key=lambda r: r.tier == "exclude")
            assert r.rule and r.path and r.text


def test_care_team_note_is_the_cited_source(sf, jordan_knee):
    d = next(x for x in sf.evaluate(Constraints(injuries=[jordan_knee])).values() if x.name == "Static Jump")
    assert any("care-team note" in (r.source or "") for r in d.reasons if r.tier == "exclude")


# --- scenario 2: exclude deadlift variations ---------------------------------
def test_deadlift_family_excluded_and_nothing_else(sf):
    t = tiers(sf.evaluate(Constraints(excluded_families={"deadlift"})))
    assert {n for n, v in t.items() if v == "exclude"} == DEADLIFTS
    assert t["Kettlebell Swing"] == "allow"  # a hinge, but not a deadlift


def test_no_hinging_removes_the_whole_pattern(sf):
    t = tiers(sf.evaluate(Constraints(excluded_patterns={"lower-pull-hinge"})))
    assert {n for n, v in t.items() if v == "exclude"} == DEADLIFTS | {"Kettlebell Swing"}


# --- scenario 3: no barbell, only dumbbells and a kettlebell -----------------
def test_only_dumbbells_and_a_kettlebell(sf):
    d = {x.name: x for x in sf.evaluate(Constraints(equipment=["Dumbbell", "Kettlebell"])).values()}
    for name in [
        "Barbell Decline Bench Press",
        "Barbell Conventional Deadlift",
        "Trap Bar Deadlift",
        "Wide-Grip Preacher Curl with EZ Bar",
        "Dumbbell Incline Chest Fly",
        "Dumbbell Hip Thrust",
        "Double Kettlebell Front Squat",
        "Machine - Chest-Supported Row",
    ]:
        assert d[name].tier == "exclude", name
    for name in [
        "Kettlebell Goblet Squat",
        "Dumbbell Bent-Over Row",
        "Alternating Dumbbell Overhead Press",
        "Dumbbell Floor Press",
        "Wall Sit",
        "Static Jump",
    ]:
        assert d[name].tier == "allow", name


def test_single_kettlebell_quantity(sf):
    d = {x.name: x for x in sf.evaluate(Constraints(equipment=["Dumbbell", "Kettlebell"])).values()}
    assert any("2x kettlebell" in r.text for r in d["Double Kettlebell Front Squat"].reasons)


def test_floor_stands_in_for_a_mat_but_is_flagged(sf):
    d = {x.name: x for x in sf.evaluate(Constraints(equipment=["Dumbbell"])).values()}
    assert d["Dumbbell Glute Bridge"].tier == "allow"
    assert any("floor works as yoga-mat" in f for f in d["Dumbbell Glute Bridge"].flags)


def test_no_barbell_removes_the_barbell_family(sf):
    d = {
        x.name: x
        for x in sf.evaluate(
            Constraints(
                equipment=["Barbell", "EZ Bar", "Trap Bar", "Plate", "Rack", "Preacher Curl Bench"],
                excluded_equipment={"barbell-family"},
            )
        ).values()
    }
    for name in ["Wide-Grip Preacher Curl with EZ Bar", "Trap Bar Deadlift", "Barbell Racked Forward Lunge"]:
        assert d[name].tier == "exclude", name


def test_adjustable_bench_provides_every_position_flat_bench_does_not(sf):
    adj = tiers(sf.evaluate(Constraints(equipment=["Dumbbell", "Adjustable Bench"])))
    flat = tiers(sf.evaluate(Constraints(equipment=["Dumbbell", "Flat Bench"])))
    assert adj["Dumbbell Incline Chest Fly"] == "allow"
    assert flat["Dumbbell Incline Chest Fly"] == "exclude"
    assert flat["Dumbbell Neutral-Grip Bench Press"] == "allow"


# --- traps -------------------------------------------------------------------
def test_part_of_traversal_runs_both_ways(sf):
    up = sf.related_structures("patella")  # injury at a sub-structure reaches the joint
    down = sf.related_structures("knee")  # injury at the joint reaches its sub-structures
    assert any(s.endswith("/knee") for s in up)
    assert any(s.endswith("/patella") for s in down) and any(s.endswith("/medial-meniscus") for s in down)


def test_subpart_injury_catches_joint_level_exercises(sf):
    meniscus = Injury(id="t", label="meniscus", structure="medial-meniscus", status="acute")
    assert tiers(sf.evaluate(Constraints(injuries=[meniscus])))["Dumbbell Goblet Split Squat"] == "exclude"


def test_laterality_never_changes_safety(sf, jordan_knee):
    left = tiers(sf.evaluate(Constraints(injuries=[jordan_knee])))
    right = tiers(sf.evaluate(Constraints(injuries=[replace(jordan_knee, side="right")])))
    assert left == right


def test_unresolved_complaint_fails_closed(sf):
    complaint = Injury(id="c", label="knee (bothering her)", structure="knee", status="acute")
    t = tiers(sf.evaluate(Constraints(injuries=[complaint])))
    assert t["Kettlebell Goblet Box Squat"] == "exclude"  # stage default for acute
    assert t["Cow Pose"] == "allow"  # contact-only still fine


def test_cleared_injury_is_inactive(sf, jordan_knee):
    t = tiers(sf.evaluate(Constraints(injuries=[replace(jordan_knee, status="cleared", extra_rules=())])))
    assert set(t.values()) == {"allow"}


def test_lumbar_and_shoulder_rules_generalize(sf):
    lbp = Injury(id="b", label="low back", structure="lumbar-spine", status="acute", condition="lbp")
    d = {x.name: x for x in sf.evaluate(Constraints(injuries=[lbp])).values()}
    assert d["Dead Bug"].uprank and d["Dead Bug"].tier == "allow"
    assert d["Kettlebell Romanian Deadlift"].tier == "downrank"
    rc = Injury(id="s", label="rotator cuff", structure="rotator-cuff", status="acute", condition="rc-tendinopathy")
    d = {x.name: x for x in sf.evaluate(Constraints(injuries=[rc])).values()}
    assert d["Side-Lying Dumbbell External Rotation"].uprank
    assert d["Dumbbell Incline Chest Fly"].tier == "exclude"  # end range under load, acute
