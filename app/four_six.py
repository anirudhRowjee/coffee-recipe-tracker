"""Tetsu Kasuya's 4:6 method as a starting recipe: the first 40% of the water sets the
taste (two pours, split by "taste"), the last 60% the strength (1-4 equal pours). The
same rules as the 4:6 calculator, so a recipe built here matches it.

The page (four_six.html) previews with a copy of plan() in JavaScript; the recipe
itself is always built here, from the submitted settings.
"""
import math
from typing import List, Optional

INTERVAL = 45   # seconds between pours
DRAIN = 30      # after the last pour, until the dripper comes off

# Roast choices: Kasuya's temperatures (93 °C light, 88 medium, 83 dark), with the steps between
ROASTS = [
    ("light", "Light", 93),
    ("light-medium", "Light-medium", 91),
    ("medium", "Medium", 88),
    ("medium-dark", "Medium-dark", 85),
    ("dark", "Dark", 83),
]
TASTES = [(-1, "Brighter"), (0, "Balanced"), (1, "Sweeter")]
BODIES = [(1, "Lightest"), (2, "Lighter"), (3, "Standard"), (4, "Strongest")]

LIMITS = {"coffee": (5.0, 60.0), "ratio": (10.0, 20.0)}


def _round(x: float) -> int:
    """Half up, like JavaScript's Math.round (Python's round() goes to even)."""
    return math.floor(x + 0.5)


def roast_temp(roast: str) -> Optional[int]:
    return next((t for key, _, t in ROASTS if key == roast), None)


def plan(coffee: float, ratio: float, taste: float, body_pours: int) -> dict:
    """The pours: [{"at": seconds, "add": grams, "to": scale reading, "phase": "taste"|"body"}],
    the total water and when the dripper comes off. Cumulative targets are rounded, so the
    pours always add up to the total."""
    water = coffee * ratio
    first = 0.5 - taste / 12   # 50/70 sweeter, 60/60 balanced, 70/50 brighter (Kasuya's examples)
    parts = [0.4 * first, 0.4 * (1 - first)] + [0.6 / body_pours] * body_pours
    pours: List[dict] = []
    total = previous = 0.0
    for i, share in enumerate(parts):
        total += share
        target = _round(water * total)
        pours.append({"at": i * INTERVAL, "add": target - previous, "to": target, "phase": "taste" if i < 2 else "body"})
        previous = target
    return {"water": _round(water), "pours": pours, "done": (len(pours) - 1) * INTERVAL + DRAIN}


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def steps_text(coffee: float, temp: int, p: dict, brewer_shape: Optional[str] = None) -> str:
    """The method in the app's step format, ready for brew mode."""
    grams = f"{coffee:g}"
    prep = f"Prep: {grams}g coffee, ground coarse, water at {temp} °C"
    if brewer_shape == "switch":
        prep += ", valve open throughout"
    lines = [prep]
    for i, pour in enumerate(p["pours"]):
        name = "Bloom" if i == 0 else "Pour, taste" if i == 1 else "Pour, strength"
        lines.append(f"{_clock(pour['at'])} — {name} (to {pour['to']}g)")
    lines.append(f"{_clock(p['done'])} — Done")
    return "\n".join(lines)
