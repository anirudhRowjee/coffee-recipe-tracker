"""
Per-bean colours. The browser picks an accent colour and four mesh colours
from the bag photo (app/static/bean_art.js); this turns them into CSS variables
that stay readable: --accent is dark enough for white text, --accent-soft is
pale enough to sit behind the app's dark text, and --mesh-strip / --mesh-strong
are full-colour gradients for places with no text on them.
"""
import re
from typing import List, Optional, Tuple

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


def clean_mesh(value: Optional[str]) -> Optional[str]:
    """Four comma-separated #rrggbb colours, normalised, or None."""
    parts = [clean_accent(part) for part in (value or "").split(",")]
    return ",".join(parts) if len(parts) == 4 and all(parts) else None  # type: ignore[arg-type]


def _gradient(colors: List[RGB], base: RGB) -> str:
    """A corner of colour each, fading out over a base colour."""
    corners = ("0% 0%", "100% 0%", "0% 100%", "100% 100%")
    layers = [
        "radial-gradient(at {pos},rgba({r},{g},{b},1) 0,rgba({r},{g},{b},0) 75%)".format(pos=pos, r=c[0], g=c[1], b=c[2])
        for pos, c in zip(corners, colors)
    ]
    return ",".join(layers + [_hex(base)])


def bean_mesh(mesh: Optional[str]) -> str:
    cleaned = clean_mesh(mesh)
    if not cleaned:
        return ""
    colors = [_rgb(part) for part in cleaned.split(",")]
    n = len(colors)
    average: RGB = (sum(c[0] for c in colors) // n, sum(c[1] for c in colors) // n, sum(c[2] for c in colors) // n)
    strip = "linear-gradient(90deg," + ",".join(_hex(c) for c in colors) + ")"
    return f"--mesh-strip:{strip};--mesh-strong:{_gradient(colors, average)}"


def card_colors(bean) -> dict:
    """Plain colours for the share image (drawn on a canvas, so no CSS variables):
    an accent dark enough for text on parchment, a pale tile colour, and the four
    mesh corners or None."""
    cleaned = clean_accent(bean.accent_color)
    strong = _accent_for_white_text(_rgb(cleaned)) if cleaned else (107, 61, 46)
    mesh = clean_mesh(bean.mesh_colors)
    return {"accent": _hex(strong), "soft": _hex(_mix(strong, _PARCHMENT, 0.82)),
            "mesh": mesh.split(",") if mesh else None}


def bean_style(bean) -> str:
    """Everything a bean's colours set, for a style attribute."""
    return ";".join(part for part in (bean_theme(bean.accent_color), bean_mesh(bean.mesh_colors)) if part)
