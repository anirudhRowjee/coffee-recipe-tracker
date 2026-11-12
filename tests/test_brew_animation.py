"""
Brew mode's animation: reading what each step is, which brewer drawing to use,
the water/valve/cup plan, and that recipes it can't animate look exactly as before.
"""
import html as html_lib
import json
import re
import sqlite3

import pytest

from app.brew import animation_data, brewer_shape, step_actions, suggest_steps
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


@pytest.mark.parametrize("action,grams,actions", [
    ("Bloom + Agitation", 60, ["bloom", "stir"]),
    ("Pour", 120, ["pour"]),
    ("Add all the hot water", None, ["pour"]),
    ("Stir NSNSEWEW", None, ["stir"]),
    ("Swirl", None, ["swirl"]),
    ("Slow plunge", None, ["plunge"]),
    ("Press and drink", None, ["plunge"]),
    ("Drawdown until 3:00", None, ["drawdown"]),
    ("Drawdown finishes", None, ["drawdown"]),
    ("Release", None, ["open"]),
    ("Open valve, drain", None, ["open", "drawdown"]),
    ("Close the switch", None, ["close"]),
    ("Add coffee", None, ["add"]),
    ("Steep", None, ["wait"]),
    ("Rinse the filter", None, ["idle"]),  # unfamiliar: nothing is drawn happening
    ("Second pulse", 180, ["pour"]),  # a target weight means water is going in
    ("Swirl gently", 180, ["pour", "swirl"]),
    ("Close valve", 50, ["close", "pour"]),
    ("Valve OPEN, 90g bloom + good swirl", None, ["open", "bloom", "swirl"]),
    ("OPEN valve, pour the rest to 500g as it drains", 500, ["open", "pour"]),  # "the rest" isn't resting
    ("When water drops to the coffee bed (~2:30) — CLOSE valve, Pour until ~1cm below the rim (expect ~420–450g), gentle swirl", 430,
     ["close", "pour", "swirl"]),  # the "water" and "coffee" setting the scene aren't actions
])
def test_step_actions(action, grams, actions):
    assert step_actions(action, grams) == actions


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


def phases(data):
    return [phase for step in data["steps"] for phase in step["phases"]]


def kinds(data):
    return [[phase["kind"] for phase in step["phases"]] for step in data["steps"]]


# Prod's first tidied recipe: the one that drew "drain" on every step
REAL = """0:00 — Valve OPEN, 90g bloom + good swirl
0:40 — Valve OPEN, pour (to 200g)
1:10 — Valve OPEN, pour (to 300g)
2:30 — When water drops to the coffee bed (~2:30) — CLOSE valve, Pour until ~1cm below the rim (expect ~420–450g), gentle swirl (to 430g)
3:15 — OPEN valve, pour the rest to 500g as it drains (to 500g)
4:00 — Drawdown target: done by ~4:00"""


def test_real_recipe_draws_what_each_step_says():
    data = plan(REAL)
    shown = kinds(data)
    assert shown[0][:2] == ["bloom", "swirl"] and set(shown[0]) == {"bloom", "swirl"}  # "Valve OPEN" draws nothing
    assert shown[1] == ["pour"] and shown[2] == ["pour"]
    assert shown[3][:3] == ["close", "pour", "swirl"] and "close" not in shown[3][3:]  # the valve moves once, the rest loops
    assert shown[4][:2] == ["open", "pour"] and "open" not in shown[4][2:]
    assert shown[5] == ["done"]  # "done by": this last step is what stops the timer


def test_state_carries_through_a_looping_step():
    steps = plan(REAL)["steps"]
    all_phases = phases({"steps": steps})
    for earlier, later in zip(all_phases, all_phases[1:-1]):
        assert earlier["to"] == pytest.approx(later["from"], abs=0.002)  # water never jumps
        assert earlier["cup_to"] == pytest.approx(later["cup_from"], abs=0.002)
        assert later["at"] >= earlier["at"]
    assert steps[0]["phases"][-1]["to"] == 0.18  # "90g bloom" of 500g, reached across the bloom phases
    assert steps[1]["phases"][-1]["to"] == 0.4
    assert steps[3]["phases"][-1]["to"] == 0.86
    for phase in steps[3]["phases"]:
        assert phase["valve"] == "closed" and not phase["flow"]  # closed from its first moment, and it stays closed
    assert [p["flip"] for p in steps[3]["phases"]] == [True] + [False] * (len(steps[3]["phases"]) - 1)
    swirls = [p for p in steps[3]["phases"] if p["kind"] == "swirl"]
    assert all(p["from"] == p["to"] for p in swirls)  # water only moves while pouring
    assert steps[4]["phases"][0]["flip"] and steps[4]["phases"][0]["valve"] == "open"
    assert all(p["bloomed"] for p in all_phases[len(steps[0]["phases"]):])  # the bed stays swollen


def test_phases_fill_their_step():
    for step, following in zip(plan(REAL)["steps"], plan(REAL)["steps"][1:]):
        last = step["phases"][-1]
        assert last["at"] + last["seconds"] == pytest.approx(following["at"], abs=0.1)


def test_switch_plan_tracks_water_valve_and_cup():
    data = plan(HYBRID)
    assert data["shape"] == "switch"
    assert [s["at"] for s in data["steps"]] == [0, 40, 70, 100, 150, 210]
    shown = kinds(data)
    assert shown[1:4] == [["pour"], ["swirl"], ["wait"]] and shown[5] == ["done"]
    assert shown[0][:2] == ["close", "bloom"] and shown[4][:2] == ["open", "drawdown"]
    ends = [step["phases"][-1] for step in data["steps"]]
    assert [p["to"] for p in ends] == [0.25, 1, 1, 1, 0, 0]
    assert [p["valve"] for p in ends] == ["closed"] * 4 + ["open"] * 2
    assert not any(p["flow"] for s in data["steps"][:4] for p in s["phases"])  # nothing drips while closed
    assert ends[3]["cup_to"] == 0 and ends[4]["cup_to"] == 1 and ends[5]["cup_to"] == 1


def test_open_brewer_drips_from_the_first_pour():
    data = plan("0:00 — Bloom (to 50g)\n0:30 — Pour (to 200g)\n1:30 — Drawdown\n2:30 — Done", "Kalita Mino")
    steps = phases(data)
    assert [s["flow"] for s in steps] == [True, True, True, False]
    assert steps[1]["cup_to"] == pytest.approx(0.6)
    assert steps[-1]["cup_to"] == 1


def test_aeropress_only_flows_on_the_plunge():
    steps = phases(plan("0:00 — Add all the hot water\n0:15 — Stir\n2:30 — Slow plunge\n3:00 — Done", "Office Aeropress"))
    assert steps[0]["to"] == 1  # no weight written: filled to the top
    assert [s["flow"] for s in steps] == [False, False, True, False]
    assert steps[2]["cup_to"] == 1


def test_a_last_step_without_done_still_plays():
    assert plan("0:00 — Pour (to 200g)\n2:00 — Slow plunge", "Aeropress")["steps"][-1]["phases"][0]["seconds"] == 30


def test_steps_follow_the_timers_order():
    assert [s["at"] for s in plan("1:00 — Swirl\n0:00 — Pour (to 200g)")["steps"]] == [0, 60]


def test_valve_words_mean_nothing_without_a_valve():
    data = plan("0:00 — Close valve, pour (to 200g)\n1:00 — Done", "Pink Hario v60")
    assert kinds(data)[0] == ["pour"]


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
            for step in (phases(json.loads(raw)) if raw else []):
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
    assert html.index('src="/static/brew_animation.js?v=') < html.index("window.BrewAnimation(timer)")


def test_free_text_page_has_no_plan(app):
    post(app, "/recipes", BASELINE)
    assert "data-animation" not in brew_page(app).text
