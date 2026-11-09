"""
Brew mode's animation: reading what each step is, which brewer drawing to use,
the water/valve/cup plan, and that recipes it can't animate look exactly as before.
"""
import html as html_lib
import json
import re
import sqlite3

import pytest

from app.brew import action_kind, animation_data, brewer_shape, suggest_steps
from conftest import REFERENCE_DB
from test_brew_mode import brew_page
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

HYBRID = """Prep: Add the grounds
0:00 — Close valve, bloom (to 50g)
0:40 — Pour (to 200g)
1:10 — Swirl
1:40 — Wait
2:30 — Open valve, drain
3:30 — Done"""


def plan(text, brewer="Hario Switch v60", method=None):
    return json.loads(animation_data(text, brewer, method))


@pytest.mark.parametrize("action,grams,kind", [
    ("Bloom + Agitation", 60, "bloom"),
    ("Pour", 120, "pour"),
    ("Add all the hot water", None, "pour"),
    ("Stir NSNSEWEW", None, "stir"),
    ("Swirl", None, "swirl"),
    ("Slow plunge", None, "plunge"),
    ("Press and drink", None, "plunge"),
    ("Drawdown until 3:00", None, "drawdown"),
    ("Drawdown finishes", None, "drawdown"),
    ("Release", None, "open"),
    ("Open valve, drain", None, "open"),
    ("Close the switch", None, "close"),
    ("Add coffee", None, "add"),
    ("Steep", None, "wait"),
    ("Done", None, "done"),
    ("Rinse the filter", None, "idle"),  # unfamiliar: nothing is drawn happening
    ("Second pulse", 180, "pour"),  # a target weight means water is going in
    ("Swirl gently", 180, "pour"),
])
def test_action_kind(action, grams, kind):
    assert action_kind(action, grams) == kind


@pytest.mark.parametrize("name,method,shape", [  # the real brewers in prod
    ("Aeropress with Flow Control Cap", None, "aeropress"),
    ("Office Aeropress", "Immersion percolation hybrid ", "aeropress"),
    ("Aeropress go", "Aeropress", "aeropress"),
    ("Kalita Mino", "Pour Over", "flat"),
    ("Hario Switch v60", "Pour Over", "switch"),
    ("Pink Hario v60", "Pour Over", "cone"),
    ("Something New", "Pour Over", "cone"),
    ("Morphy Richards Espresso", "Espresso", None),
    ("No Brewer", "No Method", None),
])
def test_brewer_shape(name, method, shape):
    assert brewer_shape(name, method) == shape


def test_switch_plan_tracks_water_valve_and_cup():
    data = plan(HYBRID)
    assert data["shape"] == "switch"
    steps = data["steps"]
    assert [s["kind"] for s in steps] == ["bloom", "pour", "swirl", "wait", "open", "done"]
    assert [(s["from"], s["to"]) for s in steps] == [(0, 0.25), (0.25, 1), (1, 1), (1, 1), (1, 0), (0, 0)]
    assert [s["valve"] for s in steps] == ["closed"] * 4 + ["open"] * 2
    assert [s["flip"] for s in steps] == [True, False, False, False, True, False]
    assert [s["flow"] for s in steps] == [False, False, False, False, True, False]  # nothing drips while closed
    assert [(s["at"], s["seconds"]) for s in steps] == [(0, 40), (40, 30), (70, 30), (100, 50), (150, 60), (210, 0)]
    assert [(s["cup_from"], s["cup_to"]) for s in steps[3:]] == [(0, 0), (0, 1), (1, 1)]


def test_open_brewer_drips_from_the_first_pour():
    steps = plan("0:00 — Bloom (to 50g)\n0:30 — Pour (to 200g)\n1:30 — Drawdown\n2:30 — Done", "Kalita Mino")["steps"]
    assert [s["flow"] for s in steps] == [True, True, True, False]
    assert steps[1]["cup_to"] == pytest.approx(0.6)
    assert steps[-1]["cup_to"] == 1


def test_aeropress_only_flows_on_the_plunge():
    steps = plan("0:00 — Add all the hot water\n0:15 — Stir\n2:30 — Slow plunge\n3:00 — Done", "Office Aeropress")["steps"]
    assert steps[0]["to"] == 1  # no weight written: filled to the top
    assert [s["flow"] for s in steps] == [False, False, True, False]
    assert steps[2]["cup_to"] == 1


def test_a_last_step_without_done_still_plays():
    assert plan("0:00 — Pour (to 200g)\n2:00 — Slow plunge", "Aeropress")["steps"][-1]["seconds"] == 30


def test_steps_follow_the_timers_order():
    steps = plan("1:00 — Swirl\n0:00 — Pour (to 200g)")["steps"]
    assert [s["at"] for s in steps] == [0, 60]


def test_nothing_to_animate():
    assert animation_data("Pour slowly\nSwirl at 1:00", "Hario Switch") == ""  # free text
    assert animation_data(None, "Hario Switch") == ""
    assert animation_data("0:00 — Pour (to 200g)", "No Brewer", "No Method") == ""
    assert animation_data("0:00 — Pour (to 200g)", "Morphy Richards Espresso", "Espresso") == ""


def test_real_methods_plan_sensibly():
    if not REFERENCE_DB.exists():
        pytest.skip("no reference database")
    con = sqlite3.connect(f"file:{REFERENCE_DB}?mode=ro", uri=True)
    rows = con.execute("select r.recipe_text, b.name, b.method from recipe r join brewer b on b.id = r.brewer_id").fetchall()
    con.close()
    for text, name, method in rows:
        for method_text in (text, suggest_steps(text).text):
            raw = animation_data(method_text, name, method)
            for step in (json.loads(raw)["steps"] if raw else []):
                assert 0 <= step["from"] <= 1 and 0 <= step["to"] <= 1, method_text
                assert 0 <= step["cup_from"] <= step["cup_to"] <= 1, method_text
                assert step["seconds"] >= 0, method_text


def test_page_carries_the_plan(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": HYBRID})
    html = brew_page(app).text
    raw = re.search(r'data-animation="([^"]+)"', html).group(1)
    assert json.loads(html_lib.unescape(raw)) == plan(HYBRID, "Hario Switch")
    assert re.search(r'<div class="brew-anim" id="brew-anim" hidden>', html)  # only shown with JavaScript
    assert re.search(r'id="brew-anim-toggle"[^>]* hidden>', html)
    assert re.search(r'id="brew-anim-on" type="checkbox" checked', html)  # on by default
    assert html.index('src="/static/brew_animation.js"') < html.index("window.BrewAnimation(timer)")


def test_free_text_page_has_no_plan(app):
    post(app, "/recipes", BASELINE)
    assert "data-animation" not in brew_page(app).text
