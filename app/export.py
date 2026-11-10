"""
Plain-text / Markdown export of a named recipe, for sharing with friends.

Only what a friend needs to brew it: bean, gear, the current version's
parameters and method, and how the recipe got there. Deliberately leaves out
anything personal: tasting notes, recommendations, bags and quantities, the
bean's private notes, and who brewed it. Reads only the fields listed here,
so adding a column elsewhere never leaks into an export.
"""
import re
from typing import List, Tuple

from . import brew, db, models, theme

LABELS = {"dose_g": "Dose", "water_ml": "Water", "temp_c": "Temp", "grind_size": "Grind"}
UNITS = {"dose_g": " g", "water_ml": " ml", "temp_c": " °C", "grind_size": ""}


def _value(recipe: models.Recipe, param: str) -> str:
    value = getattr(recipe, param)
    shown = f"{value:g}" if isinstance(value, float) else str(value)
    return shown + UNITS[param]


def ratio(recipe: models.Recipe) -> str:
    """Brew ratio as "1:16.7" (or "1:15"); "" if there is no dose."""
    if not recipe.dose_g:
        return ""
    return f"1:{recipe.water_ml / recipe.dose_g:.1f}".removesuffix(".0")


def title(line: models.RecipeLine, bean: models.Bean) -> str:
    # "Default" means nothing to a friend; any other name is part of the title
    return bean.name if line.name == db.DEFAULT_LINE_NAME else f"{bean.name} — {line.name}"


def filename(line: models.RecipeLine, bean: models.Bean) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title(line, bean).lower()).strip("-")
    return f"{slug or 'recipe'}.md"


def image_filename(line: models.RecipeLine, bean: models.Bean) -> str:
    return filename(line, bean).removesuffix(".md") + ".png"


def card_data(line: models.RecipeLine, latest: models.Recipe) -> dict:
    """What the share image shows, from the same whitelist as the Markdown: the bean,
    the gear, every parameter of the current version, and its method."""
    bean, brewer, grinder = latest.bean, latest.brewer, latest.grinder
    assert bean and brewer and grinder
    standard = brew.is_standard(latest.recipe_text)
    steps = []
    for step in brew.parse_steps(latest.recipe_text):
        if standard and step.times:  # "0:40 — Pour · to 200 g" → time and action apart
            steps.append({"time": brew.mmss(step.times[0]), "text": step.text.split(" — ", 1)[1]})
        else:
            steps.append({"time": "", "text": step.text})
    params = [
        ["Dose", _value(latest, "dose_g")], ["Water", _value(latest, "water_ml")], ["Ratio", ratio(latest)],
        ["Temp", _value(latest, "temp_c")], ["Grind", _value(latest, "grind_size")],
    ]
    timed = [step.times[0] for step in brew.parse_steps(latest.recipe_text) if standard and step.times]
    if timed and max(timed) > 0:
        params.append(["Brew time", brew.mmss(max(timed))])
    made = latest.created_at
    return {
        "title": title(line, bean),
        "gear": f"{brewer.name} · {grinder.name}",
        "about": " · ".join(x for x in (bean.origin, bean.roast_level) if x),
        "flavour": bean.flavor_notes or "",
        "params": [p for p in params if p[1]],
        "steps": steps,
        "photo": f"/beans/{bean.id}/image?v={bean.image_version}" if bean.image_version else "",
        "colors": theme.card_colors(bean),
        "date": f"{made.day} {made:%b %Y}",
        "filename": image_filename(line, bean),
    }


def to_markdown(
    line: models.RecipeLine,
    latest: models.Recipe,
    history: List[Tuple[models.Delta, models.Recipe, models.Recipe]],
) -> str:
    bean, brewer, grinder = latest.bean, latest.brewer, latest.grinder
    assert bean and brewer and grinder
    out = [f"# {title(line, bean)}", f"{brewer.name} · {grinder.name}", ""]

    about = " · ".join(x for x in (bean.origin, bean.roast_level) if x)
    if about:
        out.append(about)
    if bean.flavor_notes:
        out.append(f"Flavour notes: {bean.flavor_notes}")
    if about or bean.flavor_notes:
        out.append("")

    shown_ratio = f" ({ratio(latest)})" if latest.dose_g else ""
    out += [
        f"- Dose: {_value(latest, 'dose_g')} · Water: {_value(latest, 'water_ml')}{shown_ratio} · Temp: {_value(latest, 'temp_c')}",
        f"- Grind: {_value(latest, 'grind_size')} on {grinder.name}",
        "",
    ]

    if latest.recipe_text and latest.recipe_text.strip():
        # textareas submit \r\n; normalise and drop trailing spaces per line
        method = "\n".join(step.rstrip() for step in latest.recipe_text.strip().splitlines())
        out += ["## Method", method, ""]

    if history:
        out.append("## How it got here")
        for delta, before, after in history:
            why = f" — {delta.rationale.strip()}" if delta.rationale and delta.rationale.strip() else ""
            if delta.changed_param in LABELS:
                # actual values from the two versions, not the typed delta_amount
                param = delta.changed_param
                out.append(f"- {LABELS[param]}: {_value(before, param)} → {_value(after, param)}{why}")
            else:
                out.append(f"- Changed the method{why}")
        out.append("")

    made = latest.created_at
    out.append(f"_Version of {made.day} {made:%b %Y} · Coffee Recipe Tracker_")
    return "\n".join(out) + "\n"
