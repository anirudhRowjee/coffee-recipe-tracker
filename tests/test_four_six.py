"""
The 4:6 builder: the calculator's maths on the server, and a starting recipe saved from it.
"""
from app import four_six
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture

FORM = {"bag_id": 1, "brewer_id": 1, "grinder_id": 1, "coffee": "20", "ratio": "15", "roast": "light",
        "taste": "0", "pours": "3", "grind_size": "28"}


def test_the_maths_matches_the_calculator():
    p = four_six.plan(20, 15, 0, 3)
    assert p["water"] == 300 and [x["to"] for x in p["pours"]] == [60, 120, 180, 240, 300] and p["done"] == 210
    assert [x["to"] for x in four_six.plan(20, 15, 1, 3)["pours"]][:2] == [50, 120]    # sweeter: smaller first pour
    assert [x["to"] for x in four_six.plan(20, 15, -1, 3)["pours"]][:2] == [70, 120]   # brighter: bigger first pour
    assert len(four_six.plan(20, 15, 0, 1)["pours"]) == 3 and len(four_six.plan(20, 15, 0, 4)["pours"]) == 6


def test_the_steps_are_in_brew_modes_format():
    text = four_six.steps_text(20, 93, four_six.plan(20, 15, 0, 3), "switch")
    assert text.splitlines()[0] == "Prep: 20g coffee, ground coarse, water at 93 °C, valve open throughout"
    assert "0:45 — Pour, taste (to 120g)" in text and text.endswith("3:30 — Done")


def test_offered_for_pour_over_gear_without_a_recipe(app):
    post(app, "/beans", {"name": "New", "initial_quantity_g": "250"})
    post(app, "/brewers", {"name": "Hario Switch", "method": "Switch"})
    brewer = app.scalar("select max(id) from brewer")
    bag = app.scalar("select max(id) from beanbag")
    page = app.client.get("/", params={"bag_id": bag, "brewer_id": brewer, "grinder_id": 1}).text
    assert f"/four-six?bag_id={bag}&amp;brewer_id={brewer}&amp;grinder_id=1" in page
    assert "Light-medium" in app.client.get("/four-six", params={"bag_id": bag, "brewer_id": brewer, "grinder_id": 1}).text


def test_saving_makes_version_one_of_a_new_recipe(app):
    r = app.client.post("/four-six", data=FORM, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?bag_id=1&brewer_id=1&grinder_id=1&line_id=1"
    assert app.rows("select name from recipeline") == [{"name": "4:6"}]
    row = app.rows("select dose_g, water_ml, temp_c, grind_size, recipe_text, previous_recipe_id from recipe")[0]
    assert (row["dose_g"], row["water_ml"], row["temp_c"], row["grind_size"], row["previous_recipe_id"]) == (20.0, 300.0, 93.0, "28", None)
    assert "(to 300g)" in row["recipe_text"] and app.scalar("select count(*) from brew") == 0
    post(app, "/four-six", FORM)
    assert [r["name"] for r in app.rows("select name from recipeline order by id")] == ["4:6", "4:6 2"]


def test_bad_settings_are_refused(app):
    post(app, "/four-six", {**FORM, "coffee": "200"}, status=400)
    post(app, "/four-six", {**FORM, "pours": "9"}, status=400)
    post(app, "/four-six", {**FORM, "roast": "burnt"}, status=400)
    post(app, "/four-six", {**FORM, "grind_size": ""}, status=400)
    assert app.scalar("select count(*) from recipe") == 0
