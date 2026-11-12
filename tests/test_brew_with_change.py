"""
"Brew with change": the Next time note (or a planned change) applied to one brew without
saving anything; logging that cup saves the change as the next version.
"""
from test_flows import BASELINE, COMBO, app, latest, post  # noqa: F401 — app is a fixture


def noted(app, param="temp_c", delta="3"):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": param, "recommended_delta": delta,
                         "recommended_rationale": "sweeter"})


def test_the_card_splits_start_when_the_change_can_be_applied(app):
    noted(app)
    html = latest(app)
    assert "<span>▶ Brew with change</span><small>Temp +3 °C</small>" in html and "/lines/1/brew?bag_id=1&amp;try=1" in html and "▶ Brew</a>" in html


def test_a_method_change_keeps_one_button(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "recipe_text"})
    assert "try=1" not in latest(app) and "Start brewing" in latest(app)


def test_brew_mode_runs_the_change_without_saving(app):
    noted(app)
    page = app.client.get("/lines/1/brew", params={"bag_id": 1, "try": 1}).text
    assert "Trying Temp 93 → 96 °C</strong> · sweeter" in page and "96<small>°C</small>" in page
    assert 'name="try_param" value="temp_c"' in page and 'name="try_value" value="96"' in page
    assert app.scalar("select count(*) from recipe") == 1  # nothing saved yet


def test_logging_the_cup_saves_the_change_as_the_next_version(app):
    noted(app)
    post(app, "/plan", {**COMBO, "line_id": 1})
    plan = app.scalar("select id from plannedbrew")
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "planned_brew_id": plan, "notes": "better",
                         "try_param": "temp_c", "try_value": "96", "try_rationale": "sweeter"})
    assert app.rows("select id, temp_c, previous_recipe_id from recipe where id = 2") == [{"id": 2, "temp_c": 96.0, "previous_recipe_id": 1}]
    assert app.rows("select changed_param, delta_amount, rationale from delta") == [{"changed_param": "temp_c", "delta_amount": 3.0, "rationale": "sweeter"}]
    assert app.scalar("select recipe_id from brew where notes = 'better'") == 2
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_a_planned_change_works_too(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "line_id": 1, "suggested_param": "grind_size", "suggested_delta": "-1"})
    plan = app.scalar("select id from plannedbrew")
    assert "<small>Grind −1</small>" in app.client.get("/").text
    page = app.client.get("/lines/1/brew", params={"bag_id": 1, "plan_id": plan, "try": 1}).text
    assert 'name="try_value" value="12"' in page


def test_a_stale_change_is_refused(app):
    noted(app)
    post(app, "/recipes", {**BASELINE, "previous_recipe_id": 1, "dose_g": "16"})  # a newer version appeared
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "try_param": "temp_c", "try_value": "96"}, status=400)
    post(app, "/brews", {"recipe_id": 2, "bag_id": 1, "try_param": "bag_id", "try_value": "9"}, status=400)
