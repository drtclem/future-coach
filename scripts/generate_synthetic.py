"""Deterministic synthetic member data (D1, D5.3, D11-D13, SPEC_REVIEW 4).

Writes data/members/{jordan,sam,priya}.json. Jordan's file EXTENDS the provided
member-context.json: every provided value is kept exactly (verified below) and
history is added before it, reconciled with the provided adherence figures
(C3). Sam and Priya are new synthetic members that exercise the journey
stages (onboarding / established) and the shoulder rules.

Run: python scripts/generate_synthetic.py   (seeded; output is stable)
"""

from __future__ import annotations

import copy
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 6, 4)
rng = random.Random(20260604)


def d(s: str) -> date:
    return date.fromisoformat(s)


def iso(x: date) -> str:
    return x.isoformat()


def daily_series(
    end: date,
    days: int,
    tail: list[float],
    base: float,
    drift: float,
    noise: float,
    nd: int = 1,
) -> list[tuple[date, float]]:
    """`days` values ending at `end`; the last len(tail) values are exactly `tail`."""
    out = []
    head = days - len(tail)
    for i in range(head):
        v = base + drift * i / max(head - 1, 1) + rng.uniform(-noise, noise)
        out.append(round(v, nd))
    out += tail
    return [(end - timedelta(days=days - 1 - i), v) for i, v in enumerate(out)]


# --------------------------------------------------------------------------- Jordan
def jordan() -> dict:
    src = json.loads((ROOT / "data" / "member-context.json").read_text())
    m = copy.deepcopy(src)
    m["_note"] = (
        src["_note"]
        + " Extended with synthetic history by scripts/generate_synthetic.py; provided values are unchanged."
    )
    m["as_of"] = iso(AS_OF)
    m["profile"]["pronouns"] = "she/her"
    m["self_reported"] = {
        "typical_sleep_hours": 6.5,
        "typical_session_minutes": 45,
        "reported_on": "2024-09-15",
    }

    # Adherence: 8 synthetic completed weeks before the provided 4 (weeks start on Tuesday, as provided).
    earlier = [100, 100, 75, 100, 100, 100, 75, 100]
    first = d("2026-05-12") - timedelta(weeks=len(earlier))
    m["adherence"]["weekly_completion_pct"] = [
        {"week_of": iso(first + timedelta(weeks=i)), "pct": p}
        for i, p in enumerate(earlier)
    ] + src["adherence"]["weekly_completion_pct"]

    # Workouts: planned on Mon/Wed/Thu/Sat. Completion per week follows the adherence series.
    lower_pre = [
        "Kettlebell Goblet Squat",
        "Kettlebell Romanian Deadlift",
        "Dumbbell Hip Thrust",
    ]
    lower_post = [
        "Kettlebell Goblet Box Squat",
        "Dumbbell Hip Thrust",
        "Banded Lateral Walk",
    ]
    upper = [
        "Dumbbell Floor Press",
        "Dumbbell Bent-Over Row",
        "Half-Kneeling Dumbbell Press",
        "Band Pull-Apart",
    ]
    full = [
        "Kettlebell Goblet Squat",
        "Dumbbell Floor Press",
        "Dumbbell Bent-Over Row",
        "Dead Bug",
    ]
    titles = {
        "Wed": ("Lower Body", None),
        "Thu": ("Upper Body", upper),
        "Sat": ("Full Body", full),
        "Mon": ("Upper Body Push", upper),
    }
    given = {w["date"] for w in src["workout_history"]}
    history = list(src["workout_history"])
    # Add 2026-05-28 (Thu, completed) so week 05-26 reproduces the provided 75% (3 of 4): resolves C3.
    history.append(
        {
            "date": "2026-05-28",
            "title": "Upper Body",
            "planned": True,
            "completed": True,
            "duration_min": 30,
            "rpe": 6,
            "exercises": upper[:3],
        }
    )
    week_start = first
    for pct in earlier + [100, 100]:  # weeks 03-17 .. 05-19 are fully synthetic
        days = [week_start + timedelta(days=k) for k in range(7)]
        planned = [x for x in days if x.strftime("%a") in titles]
        skip = set(rng.sample(planned, round(len(planned) * (100 - pct) / 100)))
        for x in planned:
            if iso(x) in given or x >= d("2026-05-26"):
                continue
            title, ex = titles[x.strftime("%a")]
            if title == "Lower Body":
                ex = lower_pre if x < d("2026-05-10") else lower_post
            done = x not in skip
            mins = (48 if x < d("2026-05-01") else 38) + rng.randint(-4, 4)
            history.append(
                {
                    "date": iso(x),
                    "title": title,
                    "planned": True,
                    "completed": done,
                    "duration_min": mins if done else 0,
                    "rpe": rng.choice([6, 7]) if done else None,
                    "exercises": ex if done else [],
                }
            )
        week_start += timedelta(weeks=1)
    history.append(
        {
            "date": "2026-06-04",
            "title": "Lower Body",
            "planned": True,
            "completed": None,
            "duration_min": None,
            "rpe": None,
            "exercises": [],
            "status": "scheduled_today",
        }
    )
    m["workout_history"] = sorted(history, key=lambda w: w["date"], reverse=True)

    # Device biomarkers: 56 days, ending in the provided last-7-days sleep (oldest -> newest, ending on as_of; C9).
    sleep = daily_series(
        AS_OF, 56, src["biomarkers"]["sleep_hours_last_7_days"], 6.9, -0.4, 0.5
    )
    hrv = daily_series(AS_OF, 56, [float(src["biomarkers"]["hrv_ms"])], 53, -5, 3, nd=0)
    rhr = daily_series(
        AS_OF, 56, [float(src["biomarkers"]["resting_hr_bpm"])], 56, 2, 1.5, nd=0
    )
    m["biomarkers"]["daily"] = [
        {
            "date": iso(a),
            "sleep_hours": s,
            "hrv_ms": int(h),
            "resting_hr_bpm": int(r),
            "source": "device",
        }
        for (a, s), (_, h), (_, r) in zip(sleep, hrv, rhr, strict=True)
    ]

    # Day-of check-ins (D12).
    m["checkins"] = [
        {
            "ts": "2026-05-29T07:05:00-07:00",
            "sleep_hours": 6.1,
            "energy": 2,
            "stress": 4,
            "note": "work is slammed, might skip today",
            "source": "self-report",
        },
        {
            "ts": "2026-06-02T06:50:00-07:00",
            "sleep_hours": 5.1,
            "energy": 2,
            "soreness": 2,
            "stress": 4,
            "note": "deadline week, barely slept",
            "source": "self-report",
        },
        {
            "ts": "2026-06-03T07:10:00-07:00",
            "sleep_hours": 7.8,
            "energy": 4,
            "pain": {"area": "left knee", "score": 2},
            "note": "knee feels okay, ready for box squats",
            "source": "self-report",
        },
    ]

    # Older member-initiated messages: frequency declines over the period (feeds D19 message pattern).
    older = [
        (
            "2026-03-11T19:20:00-07:00",
            "member",
            "Loved the full body session, legs are nicely sore!",
        ),
        ("2026-03-14T09:02:00-07:00", "member", "Can we add more glute work?"),
        (
            "2026-03-14T10:15:00-07:00",
            "coach",
            "Absolutely, adding hip thrusts this week.",
        ),
        ("2026-03-20T18:40:00-07:00", "member", "Done! Hit a new hip thrust PR."),
        (
            "2026-03-26T08:11:00-07:00",
            "member",
            "Quick q: ok to do the session at lunch instead?",
        ),
        ("2026-03-28T12:30:00-07:00", "member", "Saturday session done, felt strong."),
        ("2026-04-03T20:05:00-07:00", "member", "This week was great, 4 for 4."),
        ("2026-04-09T07:45:00-07:00", "member", "Sleep was rough but I still trained."),
        ("2026-04-18T17:22:00-07:00", "member", "Finished the upper body day."),
        (
            "2026-04-27T09:30:00-07:00",
            "coach",
            "How are you feeling about the new program?",
        ),
        ("2026-04-27T21:10:00-07:00", "member", "Good! Busy at work though."),
        (
            "2026-05-11T08:00:00-07:00",
            "member",
            "Tweaked my left knee hiking this weekend, kneecap area is sore.",
        ),
        (
            "2026-05-11T08:40:00-07:00",
            "coach",
            "Thanks for flagging. Let's go knee-friendly until the care team clears you.",
        ),
        ("2026-05-16T18:30:00-07:00", "coach", "Checking in, how's the knee?"),
    ]
    m["chat_history"] = sorted(
        src["chat_history"] + [{"ts": ts, "from": f, "text": t} for ts, f, t in older],
        key=lambda c: c["ts"],
        reverse=True,
    )

    # Verify the provided data is preserved exactly.
    for w in src["workout_history"]:
        assert w in m["workout_history"], w
    for c in src["chat_history"]:
        assert c in m["chat_history"], c
    for a in src["adherence"]["weekly_completion_pct"]:
        assert a in m["adherence"]["weekly_completion_pct"], a
    assert [x["sleep_hours"] for x in m["biomarkers"]["daily"][-7:]] == src[
        "biomarkers"
    ]["sleep_hours_last_7_days"]
    for k in (
        "profile",
        "goals",
        "preferences",
        "equipment_available",
        "injuries",
        "labs",
        "coach_brief",
    ):
        for kk, v in src[k].items() if isinstance(src[k], dict) else enumerate(src[k]):
            assert m[k][kk] == v, (k, kk)
    return m


# --------------------------------------------------------------------------- Sam (onboarding)
def sam() -> dict:
    start = d("2026-05-21")
    hist = []
    for x, title, ex in [
        (
            d("2026-05-22"),
            "Intro Full Body",
            [
                "Kettlebell Goblet Box Squat",
                "Dumbbell Floor Press",
                "Dumbbell Bent-Over Row",
                "Dead Bug",
            ],
        ),
        (
            d("2026-05-26"),
            "Intro Full Body",
            [
                "Kettlebell Goblet Squat",
                "Alternating Dumbbell Overhead Press",
                "Dumbbell Glute Bridge",
            ],
        ),
        (
            d("2026-05-29"),
            "Intro Full Body",
            [
                "Dumbbell Step-Up (low box)",
                "Dumbbell Neutral-Grip Bench Press",
                "High Plank Bird Dog",
            ],
        ),
        (
            d("2026-06-02"),
            "Intro Full Body",
            ["Kettlebell Goblet Squat", "Dumbbell Bent-Over Row", "Dead Bug"],
        ),
    ]:
        hist.append(
            {
                "date": iso(x),
                "title": title,
                "planned": True,
                "completed": True,
                "duration_min": 35,
                "rpe": 6,
                "exercises": ex,
            }
        )
    return {
        "_note": "Synthetic, fictional member (onboarding stage). Generated by scripts/generate_synthetic.py.",
        "as_of": iso(AS_OF),
        "profile": {
            "id": "mbr_02SAM",
            "name": "Sam Okafor",
            "pronouns": "he/him",
            "age": 29,
            "sex": "male",
            "height_cm": 180,
            "weight_kg": 78.0,
            "timezone": "America/Chicago",
            "member_since": iso(start),
            "coach_id": "coach_01HXSAM",
            "tier": "1:1 Coaching",
        },
        "goals": [
            {
                "id": "goal_strength",
                "text": "Learn the main lifts and build general strength",
                "priority": 1,
                "target_date": None,
            }
        ],
        "preferences": {
            "preferred_session_minutes": 40,
            "training_days_per_week": 3,
            "preferred_days": ["Tue", "Fri", "Sun"],
            "dislikes": [],
            "notes": "Trains at a commercial gym. New to strength training.",
        },
        "equipment_available": [
            "Barbell",
            "Plate",
            "Rack",
            "Dumbbell",
            "Kettlebell",
            "Flat Bench",
            "Adjustable Bench",
            "Cable Resistance Machine",
            "Handle Attachment",
            "Pull-Up Bar",
            "Box",
            "Yoga Mat",
            "Resistance Band - Loop",
            "Seated Lat Pulldown Machine",
            "Chest Supported Row Machine",
        ],
        "injuries": [],
        "self_reported": {
            "typical_sleep_hours": 7.5,
            "typical_session_minutes": 40,
            "reported_on": iso(start),
        },
        "workout_history": sorted(hist, key=lambda w: w["date"], reverse=True),
        "adherence": {
            "weekly_completion_pct": [
                {"week_of": "2026-05-19", "pct": 100},
                {"week_of": "2026-05-26", "pct": 100},
            ],
            "trend": "stable",
        },
        "biomarkers": {"daily": []},
        "labs": {},
        "checkins": [
            {
                "ts": "2026-06-04T06:30:00-05:00",
                "sleep_hours": 7.5,
                "energy": 4,
                "note": "excited for leg day",
                "source": "self-report",
            }
        ],
        "chat_history": [
            {
                "ts": "2026-05-21T12:00:00-05:00",
                "from": "coach",
                "text": "Welcome Sam! We'll start with technique-first full body sessions.",
            },
            {
                "ts": "2026-05-22T19:00:00-05:00",
                "from": "member",
                "text": "First session done, the box squat cue really helped.",
            },
            {
                "ts": "2026-06-02T18:10:00-05:00",
                "from": "member",
                "text": "Getting the hang of it. When do we add weight?",
            },
        ],
    }


# --------------------------------------------------------------------------- Priya (established)
def priya() -> dict:
    start = d("2025-01-10")
    weeks = [100, 100, 75, 100, 100, 100, 100, 75, 100, 100, 100, 100]
    first = AS_OF - timedelta(days=AS_OF.weekday()) - timedelta(weeks=len(weeks))
    upper = [
        "Dumbbell Neutral-Grip Bench Press",
        "Single-Arm Chest-Supported Incline Row",
        "Side-Lying Dumbbell External Rotation",
    ]
    lower = [
        "Kettlebell Goblet Squat",
        "Dumbbell Romanian Deadlift",
        "Dumbbell Goblet Split Squat",
    ]
    hist = []
    for i, pct in enumerate(weeks):
        ws = first + timedelta(weeks=i)
        sessions = [
            ws,
            ws + timedelta(days=2),
            ws + timedelta(days=4),
            ws + timedelta(days=5),
        ]
        skip = set(rng.sample(sessions, round(4 * (100 - pct) / 100)))
        for k, x in enumerate(sessions):
            done = x not in skip
            hist.append(
                {
                    "date": iso(x),
                    "title": ["Upper", "Lower", "Upper", "Lower"][k],
                    "planned": True,
                    "completed": done,
                    "duration_min": 55 + rng.randint(-5, 5) if done else 0,
                    "rpe": 7 if done else None,
                    "exercises": ([upper, lower] * 2)[k] if done else [],
                }
            )
    sleep = daily_series(AS_OF, 56, [7.4], 7.3, 0.1, 0.4)
    return {
        "_note": "Synthetic, fictional member (established stage). Generated by scripts/generate_synthetic.py.",
        "as_of": iso(AS_OF),
        "profile": {
            "id": "mbr_03PRIYA",
            "name": "Priya Nair",
            "pronouns": "she/her",
            "age": 49,
            "sex": "female",
            "height_cm": 162,
            "weight_kg": 61.5,
            "timezone": "America/New_York",
            "member_since": iso(start),
            "coach_id": "coach_01HXSAM",
            "tier": "1:1 Coaching",
        },
        "goals": [
            {
                "id": "goal_bone",
                "text": "Maintain bone density and strength",
                "priority": 1,
                "target_date": None,
            },
            {
                "id": "goal_shoulder",
                "text": "Press overhead without shoulder pain",
                "priority": 1,
                "target_date": "2026-08-01",
            },
        ],
        "preferences": {
            "preferred_session_minutes": 55,
            "training_days_per_week": 4,
            "preferred_days": ["Mon", "Wed", "Fri", "Sat"],
            "dislikes": ["Burpees"],
            "notes": "Home gym. Very consistent.",
        },
        "equipment_available": [
            "Dumbbell",
            "Adjustable Bench",
            "Kettlebell",
            "Pull-Up Bar",
            "Resistance Band - With Handles",
            "Yoga Mat",
        ],
        "injuries": [
            {
                "id": "inj_shoulder_right",
                "region": "right shoulder",
                "joint": "shoulder",
                "status": "recovering",
                "severity": "mild",
                "since": "2026-04-02",
                "notes": "Rotator cuff tendinopathy. Avoid end-range loading under load; progress overhead pressing gradually.",
            },
            {
                "id": "inj_lowback_2025",
                "region": "lower back",
                "joint": "lumbar spine",
                "status": "cleared",
                "severity": "mild",
                "since": "2025-03-01",
                "notes": "Nonspecific low back pain, resolved. Cleared for all training.",
            },
        ],
        "self_reported": {
            "typical_sleep_hours": 7.25,
            "typical_session_minutes": 55,
            "reported_on": iso(start),
        },
        "workout_history": sorted(hist, key=lambda w: w["date"], reverse=True),
        "adherence": {
            "weekly_completion_pct": [
                {"week_of": iso(first + timedelta(weeks=i)), "pct": p}
                for i, p in enumerate(weeks)
            ],
            "trend": "stable",
        },
        "biomarkers": {
            "daily": [
                {"date": iso(a), "sleep_hours": s, "source": "device"} for a, s in sleep
            ]
        },
        "labs": {},
        "checkins": [],
        "chat_history": [
            {
                "ts": "2026-05-30T09:00:00-04:00",
                "from": "member",
                "text": "Shoulder is feeling better, presses below shoulder height are pain-free.",
            },
            {
                "ts": "2026-05-25T09:00:00-04:00",
                "from": "member",
                "text": "Another full week done!",
            },
            {
                "ts": "2026-05-18T09:00:00-04:00",
                "from": "member",
                "text": "Week done, shoulder a bit cranky on overhead work.",
            },
        ],
    }


if __name__ == "__main__":
    out = ROOT / "data" / "members"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("jordan", jordan), ("sam", sam), ("priya", priya)):
        (out / f"{name}.json").write_text(json.dumps(fn(), indent=2) + "\n")
        print("wrote", out / f"{name}.json")
