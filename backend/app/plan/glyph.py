"""Pictogram key for a plan item, chosen deterministically from the exercise's movement patterns.

The first pattern in GLYPHS that the exercise has wins, so the most specific movement
is the one drawn (a split squat shows a split squat, not a generic squat). The frontend
draws each key from a fixed library (frontend/src/Glyph.tsx); nothing here is model output.
"""

from .catalog import Ex

GLYPHS: list[tuple[str, str]] = [
    ("cardio-plyometric", "jump"),
    ("lower-push-step-up", "stepup"),
    ("lower-push-split-squat", "lunge"),
    ("lower-push-lunge", "lunge"),
    ("lower-push-squat-box-partial", "boxsquat"),
    ("lower-pull-hinge", "hinge"),
    ("lower-push-squat", "squat"),
    ("lower-pull-hip-lift", "bridge"),
    ("lower-push-calf-raise", "calf"),
    ("upper-adduction", "fly"),
    ("upper-push-vertical", "press"),
    ("upper-push-horizontal", "pushup"),
    ("upper-pull-vertical", "pullup"),
    ("upper-pull-horizontal", "row"),
    ("core-rotation", "twist"),
    ("arms-accessory", "curl"),
    ("shoulders-accessory", "raise"),
    ("core-carry", "carry"),
    ("quadruped", "birddog"),
    ("core-anti-lateral-flexion", "sideplank"),
    ("lower-abduction", "lateralwalk"),
    ("lower-adduction", "lateralwalk"),
    ("core-anti-rotation", "antirotation"),
    ("core-flexion", "crunch"),
    ("core-anti-extension", "plank"),
    ("core-extension", "superman"),
    ("cardio-locomotion", "run"),
    ("cardio", "run"),
    ("total-body", "run"),
    ("balance", "balance"),
    ("car", "circle"),
    ("mobility-dynamic", "reach"),
    ("legs-accessory", "bridge"),
    ("isometric", "plank"),
    ("mobility-static", "stretch"),
    ("yoga", "stretch"),
    ("massage", "stretch"),
    ("regen", "stretch"),
]
FALLBACK = "stand"


def glyph(e: Ex | None) -> str:
    if e is None:
        return FALLBACK
    return next((g for p, g in GLYPHS if p in e.patterns), FALLBACK)
