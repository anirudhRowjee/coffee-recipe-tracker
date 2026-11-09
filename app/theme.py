"""
Per-bean colours. The browser picks one accent colour from the bag photo
(app/static/bean_art.js); this turns it into CSS variables that stay readable:
--accent is dark enough for white text, and --accent-soft is a pale tint for
highlights behind the app's dark text.
"""
import re
from typing import Optional, Tuple

RGB = Tuple[int, int, int]

_HEX = re.compile(r"#[0-9a-f]{6}")
_WHITE: RGB = (255, 255, 255)
_PARCHMENT: RGB = (255, 252, 247)  # the card background
_MIN_CONTRAST = 4.5  # WCAG AA for normal text


def clean_accent(value: Optional[str]) -> Optional[str]:
    """A lowercase #rrggbb, or None. Anything else never reaches a style attribute."""
    candidate = (value or "").strip().lower()
    return candidate if _HEX.fullmatch(candidate) else None


def _rgb(value: str) -> RGB:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _luminance(rgb: RGB) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _accent_for_white_text(rgb: RGB) -> RGB:
    while contrast(rgb, _WHITE) < _MIN_CONTRAST:
        rgb = (int(rgb[0] * 0.92), int(rgb[1] * 0.92), int(rgb[2] * 0.92))
    return rgb


def _mix(rgb: RGB, other: RGB, amount: float) -> RGB:
    r, g, b = (round(c + (o - c) * amount) for c, o in zip(rgb, other))
    return r, g, b


def bean_theme(accent: Optional[str]) -> str:
    """CSS variables for a style attribute; empty (so the default palette applies) without an accent."""
    cleaned = clean_accent(accent)
    if not cleaned:
        return ""
    strong = _accent_for_white_text(_rgb(cleaned))
    soft = _mix(strong, _PARCHMENT, 0.82)
    return f"--accent:{_hex(strong)};--accent-soft:{_hex(soft)}"
