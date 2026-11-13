"""
The step format, the editor's server side, and "Tidy into steps". Free-text
recipes must keep working exactly as before; test_brew_mode.py covers that for
brew mode, and test_reference_parity.py on real data.
"""
import html as htmllib
import json
import re

import pytest

from app import crud, models
from app.brew import is_standard, needs_tidy, parse_steps, prep_text, step_editor_data, suggest_steps
from test_flows import BASELINE, COMBO, app, latest, post, variation  # noqa: F401 — app is a fixture

STANDARD = "Prep: Add the grounds\n0:00 — Bloom (to 90g)\n0:40 — Pour (to 200g)\n2:30 — Open valve, drain\n3:30 — Done"
FREE_TEXT = "Close the switch\r\nAdd all the water \r\nRelease at 3:00"


# --- the format ---------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    STANDARD, STANDARD.replace("\n", "\r\n"), "0:00 — Pour", "1:40 - Pour (to 200g)", "  0:00 – Pour  \n\n 1:00 — Stir",
])
def test_standard_format_is_recognised(text):
    assert is_standard(text) and not needs_tidy(text)


@pytest.mark.parametrize("text", [
    FREE_TEXT, "Prep: only prep", "0:00 — Pour\nThen stir", "Swirl at 1:00", "\t•\t0:00 — bloom", "0:00 —", "0:00 Pour",
])
def test_anything_else_is_free_text(text):
    assert not is_standard(text) and needs_tidy(text)


@pytest.mark.parametrize("text", ["", "  \r\n ", None])
def test_no_method_needs_no_tidying(text):
    assert not is_standard(text) and not needs_tidy(text)


def test_parse_standard_steps():
    steps = parse_steps(STANDARD)
    assert steps[0].is_prep and steps[0].text == "Before you start: Add the grounds" and steps[0].times == []
    assert [(s.text, s.times, s.grams) for s in steps[1:]] == [
        ("0:00 — Bloom · to 90 g", [0], 90.0),
        ("0:40 — Pour · to 200 g", [40], 200.0),
        ("2:30 — Open valve, drain", [150], None),
        ("3:30 — Done", [210], None),
    ]
    assert prep_text(STANDARD) == "Add the grounds"


def test_free_text_steps_are_unchanged():
    assert [(s.text, s.times, s.is_prep) for s in parse_steps(FREE_TEXT)] == [
        ("Close the switch", [], False), ("Add all the water", [], False), ("Release at 3:00", [180], False),
    ]
    assert prep_text(FREE_TEXT) == ""


def test_editor_data():
    data = json.loads(step_editor_data(STANDARD))
    assert data["editable"] and data["prep"] == "Add the grounds"
    assert data["steps"][1] == {"time": "0:40", "action": "Pour", "grams": "200"}
    assert json.loads(step_editor_data(""))["editable"]
    assert not json.loads(step_editor_data(FREE_TEXT))["editable"]  # free text stays a text box


# --- suggestions, using real recipes --------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("45g 45s bloom\r\n75g 45s\r\n80g 45s", "0:00 — Bloom (to 45g)\n0:45 — Pour (to 120g)\n1:30 — Pour (to 200g)"),
    ("4x 60gm in 30s\r\nand drawdown for 1:00", "0:00 — Pour (to 60g)\n0:30 — Pour (to 120g)\n1:00 — Pour (to 180g)\n1:30 — Pour (to 240g)\n2:00 — Drawdown"),
    ("40g 45s\r\n40g 45s\r\n1:00 drawdown", "0:00 — Pour (to 40g)\n0:45 — Pour (to 80g)\n1:30 — Drawdown"),
    ("Add water\r\nStir\r\nSwirl at 1:00 and 2:00\r\nPlunge at 2:30", "Prep: Add water, Stir\n1:00 — Swirl\n2:00 — Swirl\n2:30 — Plunge"),
    ("Recipe:\r\n\t•\t0:00 — valve OPEN, pour to 200g\r\n\t•\t1:10 — pour to 280g", "0:00 — Valve OPEN, pour (to 200g)\n1:10 — Pour (to 280g)"),
    ("0:00: Bloom\r\n0:40: Pour to 100 g", "0:00 — Bloom\n0:40 — Pour (to 100g)"),
    ("2:30 Immersion, 30s plunge\r\n1. Add grounds\r\n2. Swirl at 1:00", "Prep: Add grounds\n1:00 — Swirl\n2:30 — Immersion, 30s plunge"),
    ("Add coffee\r\nPress and drink", "Prep: Add coffee\n0:00 — Press and drink"),
])
def test_suggestions(text, expected):
    suggestion = suggest_steps(text)
    assert suggestion.text == expected and is_standard(suggestion.text)


def test_guesses_are_marked():
    assert suggest_steps("Swirl at 1:00\r\nPlunge at 2:30").checks == []
    assert suggest_steps("45g 45s bloom\r\n75g 45s").checks == [0, 1]
    assert suggest_steps("Wait for 3:00").checks == [0]


# --- pages ------------------------------------------------------------------------------

def test_forms_keep_a_plain_text_box_for_no_javascript(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    html = latest(app)
    assert html.count('<textarea name="recipe_text"') == 1  # new named recipe
    change = app.client.get("/lines/1/change", params={"bag_id": 1}).text
    assert change.count('<textarea name="recipe_text"') == 2  # the editor, and its original kept in a <template>
    assert html.count("data-step-editor=") == 1
    assert "Add the grounds" in html


def test_empty_form_offers_the_editor(app):
    assert "data-step-editor=" in latest(app)


def test_free_text_keeps_its_exact_text_and_is_offered_tidying(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    html = latest(app)
    assert "Close the switch" in html and "/lines/1/tidy?bag_id=1" in html
    assert app.scalar("select recipe_text from recipe where id = 1") == FREE_TEXT


def test_standard_recipe_is_not_offered_tidying(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    assert "/tidy" not in latest(app)
    assert app.client.get("/lines/1/tidy", follow_redirects=False).status_code == 303


def test_brew_mode_uses_prep_and_never_stops_by_itself(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    html = app.client.get("/lines/1/brew", params={"bag_id": 1}).text
    # a last step called "Done" no longer stops the clock: you stop it when the drawdown ends
    assert 'data-prep="Add the grounds"' in html and 'data-auto-stop' not in html
    assert "0:40 — Pour · to 200 g" in html


def test_brew_mode_for_free_text_is_as_before(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    html = app.client.get("/lines/1/brew", params={"bag_id": 1}).text
    assert 'data-prep=""' in html
    assert re.search(r'<li data-times="180">Release at 3:00</li>', html)


def test_variation_can_change_steps_and_keeps_the_one_parameter_rule(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    post(app, "/recipes", variation(app, 1, recipe_text=STANDARD.replace("0:40", "0:45"), changed_param="recipe_text"))
    assert "0:45 — Pour" in app.scalar("select recipe_text from recipe where id = 2")
    post(app, "/recipes", variation(app, 2, recipe_text=STANDARD, dose_g=16), status=400)


def test_textarea_newlines_do_not_count_as_a_method_change(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})  # stored with \\n
    post(app, "/recipes", variation(app, 1, recipe_text=STANDARD.replace("\n", "\r\n"), grind_size="12",
                                    changed_param="grind_size", delta_amount="-1"))
    assert app.scalar("select count(*) from recipe") == 2


# --- tidying ----------------------------------------------------------------------------

def tidy_page(app, line=1, **params):
    return app.client.get(f"/lines/{line}/tidy", params=params)


def test_tidy_page_shows_method_and_prefilled_suggestion(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": "Add water\r\nSwirl for 1:00"})
    html = tidy_page(app, bag_id=1).text
    assert "Add water" in html and "Save as a new version" in html
    assert 'data-free-text="0"' in html
    data = json.loads(htmllib.unescape(re.search(r'data-step-editor="([^"]+)"', html).group(1)))
    assert data["editable"] and data["steps"]


def test_saving_tidy_records_a_recipe_text_change(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    r = app.client.post("/lines/1/tidy", data={"recipe_text": STANDARD.replace("\n", "\r\n"), "bag_id": 1}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/lines/1/brew?bag_id=1"
    rows = app.rows("select id, line_id, dose_g, water_ml, temp_c, grind_size, previous_recipe_id, recipe_text from recipe order by id")
    assert len(rows) == 2 and rows[1]["previous_recipe_id"] == 1 and rows[1]["line_id"] == 1
    assert rows[1]["recipe_text"] == STANDARD and rows[0]["recipe_text"] == FREE_TEXT  # the old version is kept
    assert {k: rows[1][k] for k in ("dose_g", "water_ml", "temp_c", "grind_size")} == {k: rows[0][k] for k in ("dose_g", "water_ml", "temp_c", "grind_size")}
    assert app.rows("select from_recipe_id, to_recipe_id, changed_param, delta_amount, rationale from delta") == [
        {"from_recipe_id": 1, "to_recipe_id": 2, "changed_param": "recipe_text", "delta_amount": 0.0, "rationale": "Tidied into steps"}]


def test_tidying_logs_no_brew_and_uses_no_beans(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    post(app, "/lines/1/tidy", {"recipe_text": STANDARD, "bag_id": 1})
    assert app.scalar("select count(*) from brew") == 1
    with app.session() as s:
        assert crud.get_remaining_quantity(s, s.get(models.BeanBag, 1)) == 235.0


def test_tidied_version_keeps_showing_brews_and_recommendation(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "sour one", "recommended_param": "grind_size", "recommended_delta": "-1"})
    post(app, "/lines/1/tidy", {"recipe_text": STANDARD})
    html = latest(app)
    assert 'data-rec="brew"' in html and "sour one" in html
    assert "Tidied into steps" in html  # in the change history
    assert 'name="recipe_id" value="2"' in html  # new brews log against the new version


def test_a_normal_new_version_still_starts_with_no_brews(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "sour one", "recommended_param": "grind_size", "recommended_delta": "-1"})
    post(app, "/recipes", {**variation(app, 1, grind_size="12", changed_param="grind_size", delta_amount="-1", recipe_text=FREE_TEXT), "bag_id": ""})
    assert "sour one" not in latest(app)


@pytest.mark.parametrize("bad", ["", "still free text", "0:00 — Pour\nThen stir"])
def test_tidy_must_be_in_the_step_format(app, bad):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    post(app, "/lines/1/tidy", {"recipe_text": bad}, status=400)
    assert app.scalar("select count(*) from recipe") == 1 and app.scalar("select count(*) from delta") == 0


def test_tidy_with_nothing_changed_adds_no_version(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    post(app, "/lines/1/tidy", {"recipe_text": STANDARD})
    assert app.scalar("select count(*) from recipe") == 1


def test_tidy_stays_in_its_named_recipe(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    post(app, "/recipes", {**BASELINE, "line_name": "2 cup", "recipe_text": FREE_TEXT, "dose_g": 30, "water_ml": 500})
    post(app, "/lines/2/tidy", {"recipe_text": STANDARD})
    assert app.scalar("select recipe_text from recipe where line_id = 1") == FREE_TEXT
    assert app.scalar("select count(*) from recipe where line_id = 2") == 2


def test_cannot_tidy_someone_elses_recipe(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": FREE_TEXT})
    with app.session() as s:
        other = crud.create_user(s, name="Friend", password="correct horse battery")
        other.must_change_password = False
        s.commit()
        other_id = other.id
    app.sign_in(other_id)
    assert tidy_page(app).status_code == 404
    post(app, "/lines/1/tidy", {"recipe_text": STANDARD}, status=404)
    assert app.scalar("select count(*) from recipe") == 1


def test_shared_recipe_includes_the_steps(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STANDARD})
    text = app.client.get("/lines/1/export.md").text
    assert "0:40 — Pour (to 200g)" in text
