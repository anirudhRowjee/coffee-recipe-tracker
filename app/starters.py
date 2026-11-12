"""Starting recipes, so a first recipe is never a blank form. Only the numbers and steps:
the grind is the person's own (every grinder's numbers differ). Keyed by the drawing
brew mode uses for the brewer (brew.brewer_shape), with a general one for the rest."""

STARTERS = {
    "cone": [
        {"name": "Simple V60", "dose_g": 15, "water_ml": 250, "temp_c": 94,
         "recipe_text": "0:00 — Bloom (to 45g)\n0:45 — Pour (to 150g)\n1:15 — Pour (to 250g)\n1:45 — Swirl\n3:00 — Done"},
        {"name": "One-cup 4:6", "dose_g": 15, "water_ml": 240, "temp_c": 92,
         "recipe_text": "0:00 — Bloom (to 44g)\n0:45 — Pour (to 96g)\n1:30 — Pour (to 168g)\n2:15 — Pour (to 240g)\n3:30 — Done"},
    ],
    "switch": [
        {"name": "Switch hybrid", "dose_g": 15, "water_ml": 250, "temp_c": 93,
         "recipe_text": "0:00 — Valve open, bloom (to 50g)\n0:40 — Pour (to 150g)\n1:10 — Close valve, pour (to 250g)\n2:00 — Open valve\n3:00 — Done"},
    ],
    "aeropress": [
        {"name": "Classic AeroPress", "dose_g": 15, "water_ml": 230, "temp_c": 90,
         "recipe_text": "0:00 — Pour (to 230g)\n0:10 — Stir\n1:30 — Press\n2:00 — Done"},
    ],
    "flat": [
        {"name": "Simple Kalita", "dose_g": 16, "water_ml": 260, "temp_c": 94,
         "recipe_text": "0:00 — Bloom (to 50g)\n0:40 — Pour (to 150g)\n1:10 — Pour (to 260g)\n3:00 — Done"},
    ],
    None: [
        {"name": "Simple start", "dose_g": 15, "water_ml": 250, "temp_c": 93, "recipe_text": ""},
    ],
}


def for_brewer(shape):
    return STARTERS.get(shape) or STARTERS[None]
