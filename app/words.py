"""How recipe settings are named and written on screen.

One place for the words, so "temp_c" or "15.0" never reaches a page: a setting is
"Temp", an amount is "+3 °C", a change is "Temp 91 → 93 °C".
"""
from typing import Optional

PARAMS = ("dose_g", "water_ml", "temp_c", "grind_size", "recipe_text")
LABELS = {"dose_g": "Coffee", "water_ml": "Water", "temp_c": "Temp", "grind_size": "Grind", "recipe_text": "Method"}
UNITS = {"dose_g": " g", "water_ml": " ml", "temp_c": " °C", "grind_size": "", "recipe_text": ""}


def num(value) -> str:
    """15.0 → "15", 15.5 → "15.5"; anything else as it is."""
    if isinstance(value, float):
        return f"{value:g}"
    return "" if value is None else str(value)


def label(param: Optional[str]) -> str:
    return LABELS.get(param or "", (param or "").replace("_", " "))


def amount(param: Optional[str], delta: Optional[float]) -> str:
    """"+3 °C", "−1", "+0.5 g"; "" for no amount (or the method)."""
    if delta is None or param == "recipe_text":
        return ""
    sign = "+" if delta > 0 else "−" if delta < 0 else "±"
    return f"{sign}{abs(delta):g}{UNITS.get(param or '', '')}"


def change(param: Optional[str], delta: Optional[float]) -> str:
    """A suggested change in words: "Temp +3 °C", "Grind −1", "Method"."""
    return " ".join(p for p in (label(param), amount(param, delta)) if p)


def before_after(param: str, before, after) -> str:
    """What a version changed, from the real values: "Temp 91 → 93 °C"."""
    if param == "recipe_text":
        return "Method changed"
    if before is None or after is None:
        return label(param)
    return f"{label(param)} {num(getattr(before, param))} → {num(getattr(after, param))}{UNITS.get(param, '')}"
