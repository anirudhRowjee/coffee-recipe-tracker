"""
Brew mode (/lines/{id}/brew): step-time parsing, the page, and logging a
brew (including a scheduled one) from it.
"""
import re

from app.brew import mmss, parse_steps
from test_flows import BASELINE, COMBO, app, latest, post  # noqa: F401 — app is a fixture

METHOD = "Close the switch\r\nAdd all the grounds \r\n\r\nSwirl at 1:00 and 2:00\r\nRelease at 3:00"


# --- parsing (method texts from real prod recipes) ----------------------------

def test_parse_steps_from_real_methods():
    steps = parse_steps(METHOD)
    assert [(s.text, s.times) for s in steps] == [
        ("Close the switch", []),
        ("Add all the grounds", []),
        ("Swirl at 1:00 and 2:00", [60, 120]),
        ("Release at 3:00", [180]),
    ]
    assert parse_steps("2:30 Immersion, 30s slow plunge")[0].times == [150]


def test_parse_steps_ignores_things_that_are_not_m_ss():
    for text in ["Bloom 30s", "Ratio 1:16", "ratio of 1:15", "at 12:30:00", "1:234 ml", "1:5", "Step 1: pour"]:
        assert parse_steps(text)[0].times == [], text
    assert parse_steps("Plunge at 10:05")[0].times == [605]


def test_range_counts_from_its_start():
    # real prod lines
    assert parse_steps("6.\tDrawdown finishes 3:30–4:00")[0].times == [210]
    assert parse_steps("o finish draining around 3:00–3:30.")[0].times == [180]
    assert parse_steps("•\t0:45 — to 120g")[0].times == [45]  # a dash after a time is not a range
    assert parse_steps(None) == [] and parse_steps("  \r\n ") == []


def test_mmss():
    assert [mmss(s) for s in (0, 5, 60, 185, 605)] == ["0:00", "0:05", "1:00", "3:05", "10:05"]


# --- the page -------------------------------------------------------------------

def brew_page(app, line_id=1, **params):
    return app.client.get(f"/lines/{line_id}/brew", params={"bag_id": 1, **params})


def test_brew_page_shows_recipe_large_with_timed_steps(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    r = brew_page(app)
    assert r.status_code == 200
    html = r.text
    assert '<h2 class="brew-title">Blue Tokai Baarbara Estate</h2>' in html
    assert "Hario Switch · Timemore C2" in html
    # the recipe as labelled tiles, each saying what it's for
    for label, value, use in [("Coffee", "15<small>g</small>", "beans to weigh"), ("Grind", "13", "on the Timemore C2"),
                              ("Water", "250<small>ml</small>", "in the kettle · 1:16.7"), ("Temperature", "93<small>°C</small>", "kettle set to")]:
        assert f'<dt>{label}</dt><dd>{value}</dd><dd class="brew-use">{use}</dd>' in html, label
    assert re.search(r'<p class="brew-labels" id="brew-labels" hidden>', html)  # the one-line version, once brewing
    assert re.findall(r'<li data-times="([\d,]*)">([^<]*)</li>', html) == [
        ("", "Close the switch"), ("", "Add all the grounds"),
        ("60,120", "Swirl at 1:00 and 2:00"), ("180", "Release at 3:00"),
    ]
    assert re.search(r'<div class="brew-timer" id="brew-timer"[^>]* hidden>', html)  # only shown with JavaScript
    assert html.index('id="brew-clock"') < html.index('id="brew-scale"') < html.index('id="brew-current"')  # time and weight side by side, the step under them
    assert re.search(r'<details class="brew-all-steps" id="brew-all-steps" open>', html)  # every step shows without JavaScript
    assert re.search(r'<div class="brew-controls" id="brew-controls" hidden>', html)
    assert "<h1>" not in html and "<h1>" in app.client.get("/browse").text  # no site header: it has to fit one screen


def test_recipe_without_method_has_no_steps(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": ""})
    html = brew_page(app).text
    assert 'class="brew-steps"' not in html and 'id="brew-timer"' in html


def test_named_recipe_title(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "line_name": "2 cup", "dose_g": 30, "water_ml": 500})
    html = brew_page(app, 2).text
    assert "Blue Tokai Baarbara Estate — 2 cup" in html and "in the kettle · 1:16.7" in html and "<dd>30<small>g</small></dd>" in html


def test_card_links_to_brew_mode_with_bag(app):
    post(app, "/recipes", BASELINE)
    assert 'href="/lines/1/brew?bag_id=1"' in latest(app)


# --- logging from brew mode --------------------------------------------------------

def hidden(html, name):
    m = re.search(rf'name="{name}" value="([^"]*)"', html)
    return m.group(1) if m else None


def test_log_brew_from_brew_mode(app):
    post(app, "/recipes", BASELINE)
    html = brew_page(app).text
    assert 'id="log-notes"' in html
    assert (hidden(html, "recipe_id"), hidden(html, "bag_id"), hidden(html, "planned_brew_id")) == ("1", "1", None)
    post(app, "/brews", {"recipe_id": hidden(html, "recipe_id"), "bag_id": hidden(html, "bag_id"),
                         "notes": "Brewed 3:12\nbalanced"})
    assert app.rows("select recipe_id, bag_id, notes from brew") == [
        {"recipe_id": 1, "bag_id": 1, "notes": "Brewed 3:12\nbalanced"}]


def test_scheduled_brew_is_cleared_when_logged_from_brew_mode(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", COMBO)
    plan_id = app.scalar("select id from plannedbrew")
    assert f'href="/lines/1/brew?bag_id=1&amp;plan_id={plan_id}"' in app.client.get("/").text
    html = brew_page(app, plan_id=plan_id).text
    assert hidden(html, "planned_brew_id") == str(plan_id)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "planned_brew_id": hidden(html, "planned_brew_id")})
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_plan_id_for_something_else_is_ignored(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    post(app, "/plan", {**COMBO, "grinder_id": 2})  # a plan for the other grinder
    plan_id = app.scalar("select id from plannedbrew")
    assert hidden(brew_page(app, 1, plan_id=plan_id).text, "planned_brew_id") is None


def test_no_log_form_without_a_bag_of_this_bean(app):
    post(app, "/recipes", BASELINE)
    post(app, "/beans", {"name": "Other bean"})
    post(app, "/bags", {"bean_id": 2, "initial_quantity_g": 250})
    for params in ({"bag_id": 2}, {"bag_id": 999}):
        r = app.client.get("/lines/1/brew", params=params)
        assert r.status_code == 200 and 'id="log-brew-form"' not in r.text
    assert 'id="log-brew-form"' not in app.client.get("/lines/1/brew").text


def test_unknown_recipe_is_404_and_user_is_required(app):
    assert brew_page(app, 999).status_code == 404
    post(app, "/recipes", BASELINE)
    app.client.cookies.clear()
    r = app.client.get("/lines/1/brew", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"
