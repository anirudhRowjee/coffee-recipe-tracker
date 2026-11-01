"""
"Share as text" export of a named recipe (/lines/{id}/export.md): exact
content, what is deliberately left out, per-recipe history, and responses.
"""
from test_flows import BASELINE, COMBO, app, latest, post, variation  # noqa: F401 — app is a fixture

PRIVATE = [
    "SECRET-TASTING-NOTE", "SECRET-RECOMMENDATION", "SECRET-BREW-NOTE",
    "SECRET-BEAN-NOTE", "SECRET-BAG-NOTE", "SECRET-PLAN-NOTE", "Anirudh",
]


def export(app, line_id=1, **params):
    return app.client.get(f"/lines/{line_id}/export.md", params=params)


def dial_in(app):
    """Baseline grind 13 → 11 → 10, then a method change, with brews and notes everywhere."""
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "SECRET-TASTING-NOTE",
                         "recommended_param": "grind_size", "recommended_delta": "-2",
                         "recommended_rationale": "SECRET-RECOMMENDATION"})
    post(app, "/recipes", variation(app, 1, grind_size="11", changed_param="grind_size", delta_amount="-2",
                                    rationale="sour, extract more", brew_notes="SECRET-BREW-NOTE"))
    # typed delta deliberately wrong: the export must show the real values
    post(app, "/recipes", variation(app, 2, grind_size="10", changed_param="grind_size", delta_amount="-5",
                                    rationale="still a bit thin"))
    post(app, "/recipes", variation(app, 3, grind_size="10", changed_param="recipe_text",
                                    recipe_text="Close the switch\nAdd all the water\nRelease at 3:00",
                                    rationale="longer steep"))
    post(app, "/plan", {**COMBO, "notes": "SECRET-PLAN-NOTE"})


def test_export_content(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate", "origin": "India",
                                "roast_level": "Medium", "flavor_notes": "citrus, jaggery",
                                "notes": "SECRET-BEAN-NOTE"})
    dial_in(app)
    r = export(app)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    made = app.scalar("select created_at from recipe where id = 4")
    day, month_year = int(made[8:10]), __import__("datetime").datetime.fromisoformat(made).strftime("%b %Y")
    assert r.text == f"""# Blue Tokai Baarbara Estate
Hario Switch · Timemore C2

India · Medium
Flavour notes: citrus, jaggery

- Dose: 15 g · Water: 250 ml (1:16.7) · Temp: 93 °C
- Grind: 10 on Timemore C2

## Method
Close the switch
Add all the water
Release at 3:00

## How it got here
- Grind: 13 → 11 — sour, extract more
- Grind: 11 → 10 — still a bit thin
- Changed the method — longer steep

_Version of {day} {month_year} · Coffee Recipe Tracker_
"""


def test_export_leaves_out_everything_personal(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate", "notes": "SECRET-BEAN-NOTE"})
    post(app, "/bags/1/edit", {"initial_quantity_g": 250, "notes": "SECRET-BAG-NOTE"})
    dial_in(app)
    text = export(app).text
    for secret in PRIVATE:
        assert secret not in text, secret
    assert "250 g" not in text and "remaining" not in text.lower()  # bag quantities


def test_export_minimal_recipe_has_no_empty_sections(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate"})  # no origin/roast/flavour notes
    post(app, "/recipes", {**BASELINE, "recipe_text": ""})
    text = export(app).text
    assert "## Method" not in text and "## How it got here" not in text
    assert "Flavour notes" not in text
    assert text.startswith("# Blue Tokai Baarbara Estate\nHario Switch · Timemore C2\n\n- Dose: 15 g")


def test_method_from_a_browser_textarea_is_normalised(app):
    # browsers submit textarea text with \r\n; real prod recipes have it, plus trailing spaces
    post(app, "/recipes", {**BASELINE, "recipe_text": "1. Add the grounds\r\n2. add the hot water \r\n3. Stir\r\n"})
    text = export(app).text
    assert "\r" not in text
    assert "## Method\n1. Add the grounds\n2. add the hot water\n3. Stir\n\n" in text


def test_named_recipe_exports_only_its_own_history(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "line_name": "2 cup", "dose_g": 30, "water_ml": 500, "grind_size": "14"})
    post(app, "/recipes", variation(app, 2, dose_g=30, water_ml=500, grind_size="12",
                                    changed_param="grind_size", delta_amount="-2", rationale="2 cup finer"))
    two_cup = app.scalar("select id from recipeline where name = '2 cup'")
    text = export(app, two_cup).text
    assert text.startswith("# Blue Tokai Baarbara Estate — 2 cup\n")
    assert "- Dose: 30 g · Water: 500 ml (1:16.7)" in text and "- Grind: 12 on" in text
    assert "- Grind: 14 → 12 — 2 cup finer" in text

    default = export(app, 1).text
    assert default.startswith("# Blue Tokai Baarbara Estate\n")  # "Default" is not shown
    assert "## How it got here" not in default


def test_download_is_a_named_markdown_file(app):
    post(app, "/recipes", {**BASELINE, "line_name": "2 Cup / V60!"})
    r = export(app, download=1)
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="blue-tokai-baarbara-estate-2-cup-v60.md"'
    assert r.text == export(app).text


def test_unknown_recipe_is_404_and_user_is_required(app, app_on):
    assert export(app, 999).status_code == 404
    post(app, "/recipes", BASELINE)
    app.client.cookies.clear()
    r = app.client.get("/lines/1/export.md", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"


def test_recipe_card_links_to_export(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert 'href="/lines/1/export.md"' in html and 'href="/lines/1/export.md?download=1"' in html
