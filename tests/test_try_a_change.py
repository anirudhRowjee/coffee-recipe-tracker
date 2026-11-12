"""
Try a change: one tile at a time. The server works out what changed and by how much
from the values; saving doesn't log a cup unless "I already brewed it" is ticked.
"""
from test_flows import BASELINE, COMBO, app, latest, post  # noqa: F401 — app is a fixture

CHANGE = {**BASELINE, "previous_recipe_id": 1}


def test_the_page_offers_each_setting_as_a_tile(app):
    post(app, "/recipes", BASELINE)
    page = app.client.get("/lines/1/change", params={"bag_id": 1}).text
    for param in ("dose_g", "grind_size", "water_ml", "temp_c", "recipe_text"):
        assert f'name="changed_param" value="{param}"' in page
    assert 'min="70" max="100"' in page  # temperature can't be set to something silly
    assert 'data-step="-1"' in page  # grind "13" moves in steps of 1
    assert "Save as version 2" in page


def test_what_changed_comes_from_the_values(app):
    post(app, "/recipes", BASELINE)
    # the form says dose and -9, but only the temperature really changed
    post(app, "/recipes", {**CHANGE, "temp_c": "96", "changed_param": "dose_g", "delta_amount": "-9", "rationale": "sweeter"})
    assert app.rows("select changed_param, delta_amount, rationale from delta") == [
        {"changed_param": "temp_c", "delta_amount": 3.0, "rationale": "sweeter"}]
    post(app, "/recipes", {**CHANGE, "previous_recipe_id": 2, "temp_c": "96", "grind_size": "12"})
    assert app.rows("select changed_param, delta_amount from delta where id = 2") == [{"changed_param": "grind_size", "delta_amount": -1.0}]


def test_saving_a_change_logs_no_cup_and_says_what_changed(app):
    post(app, "/recipes", BASELINE)
    r = app.client.post("/recipes", data={**CHANGE, "temp_c": "96", "rationale": "sweeter"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?saved=2"
    assert app.scalar("select count(*) from brew") == 0
    home = app.client.get("/?saved=2").text
    assert "Version 2 saved." in home and "Temp 93 → 96 °C, sweeter" in home and "/lines/1/brew?bag_id=1" in home


def test_already_brewed_logs_the_cup_and_uses_the_plan(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", COMBO)
    plan = app.scalar("select id from plannedbrew")
    post(app, "/recipes", {**CHANGE, "temp_c": "96", "planned_brew_id": plan})  # not brewed: the plan stays
    assert app.scalar("select count(*) from plannedbrew") == 1 and app.scalar("select count(*) from brew") == 0
    post(app, "/recipes", {**CHANGE, "previous_recipe_id": 2, "temp_c": "97", "planned_brew_id": plan,
                           "bag_id": 1, "brew_notes": "lovely", "brew_rating": "5"})
    assert app.scalar("select count(*) from plannedbrew") == 0
    assert app.rows("select recipe_id, notes, rating from brew") == [{"recipe_id": 3, "notes": "lovely", "rating": 5}]


def test_two_changes_are_refused_in_words(app):
    post(app, "/recipes", BASELINE)
    r = app.client.post("/recipes", data={**CHANGE, "temp_c": "96", "dose_g": "16"})
    assert r.status_code == 400 and "Coffee and Temp" in r.text


def test_the_card_links_to_it_with_the_next_time_note(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "temp_c", "recommended_delta": "2"})
    assert "Try a change · Temp +2 °C" in latest(app)
