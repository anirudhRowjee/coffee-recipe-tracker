"""
A change to try on a scheduled brew: offered when scheduling a recipe that has no
recommendation yet, shown like one ('data-rec="plan"') on the planned combination,
and gone once the plan is used. A brew's own recommendation always wins.
"""
import csv
from pathlib import Path

from test_accounts import add_user, set_admin_password
from test_export_import import _engine, export_script, import_script
from test_flows import BASELINE, COMBO, app, latest, post  # noqa: F401 — app is a fixture

SUGGEST = {"suggested_param": "grind_size", "suggested_delta": "-1", "suggested_rationale": "a bit sour, try finer"}


def plan_row(app):
    return app.rows("select suggested_param, suggested_delta, suggested_rationale from plannedbrew")


def test_offered_on_the_panel_when_there_is_no_recommendation(app):
    post(app, "/recipes", BASELINE)
    assert 'name="suggested_param"' in latest(app)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "dose_g", "recommended_delta": "1"})
    panel = latest(app)
    assert 'data-rec="brew"' in panel and 'name="suggested_param"' not in panel


def test_scheduling_with_a_suggestion_shows_it_as_the_next_change(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "line_id": 1, **SUGGEST})
    assert plan_row(app) == [{"suggested_param": "grind_size", "suggested_delta": -1.0,
                              "suggested_rationale": "a bit sour, try finer"}]
    home = app.client.get("/").text
    assert 'data-rec="plan"' in home and "a bit sour, try finer" in home
    # Try a change starts from it, like a recommendation
    plan_id = app.scalar("select id from plannedbrew")
    change = app.client.get("/lines/1/change", params={"bag_id": 1, "plan_id": plan_id}).text
    assert 'data-rec-param="grind_size"' in change and 'data-rec-delta="-1.0"' in change and 'data-rec="plan"' in change


def test_only_on_the_planned_combination(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    post(app, "/plan", {**COMBO, **SUGGEST})
    assert 'data-rec="plan"' in latest(app)
    assert 'data-rec="plan"' not in latest(app, grinder_id=2)


def test_ignored_when_the_recipe_already_has_a_recommendation(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "dose_g", "recommended_delta": "1"})
    post(app, "/plan", {**COMBO, "line_id": 1, **SUGGEST})
    assert plan_row(app) == [{"suggested_param": None, "suggested_delta": None, "suggested_rationale": None}]
    home = app.client.get("/").text
    assert 'data-rec="brew"' in home and 'data-rec="plan"' not in home


def test_a_newer_brew_recommendation_wins(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "line_id": 1, **SUGGEST})
    # a brew logged without using the plan (so the plan stays) brings its own
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "temp_c", "recommended_delta": "2"})
    panel = latest(app)
    assert 'data-rec="brew"' in panel and 'data-rec="plan"' not in panel


def test_nothing_chosen_means_no_suggestion(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "suggested_param": "", "suggested_delta": "-1", "suggested_rationale": "x"})
    assert plan_row(app) == [{"suggested_param": None, "suggested_delta": None, "suggested_rationale": None}]
    assert 'data-rec="plan"' not in app.client.get("/").text


def test_recipe_text_has_no_amount_and_a_minus_sign_is_read(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "suggested_param": "recipe_text", "suggested_delta": "3"})
    assert plan_row(app)[0]["suggested_delta"] is None
    post(app, "/plan", {**COMBO, "suggested_param": "dose_g", "suggested_delta": "−0.5"})
    assert plan_row(app)[0]["suggested_delta"] == -0.5


def test_bad_values_are_refused(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, "suggested_param": "bag_id"}, status=400)
    post(app, "/plan", {**COMBO, "suggested_param": "dose_g", "suggested_delta": "lots"}, status=400)
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_using_the_plan_clears_it(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, **SUGGEST})
    plan_id = app.scalar("select id from plannedbrew")
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "planned_brew_id": plan_id})
    assert 'data-rec="plan"' not in latest(app)


def test_browse_marks_recipes_that_already_have_a_recommendation(app):
    post(app, "/recipes", BASELINE)
    page = app.client.get("/browse").text
    assert 'name="suggested_param"' in page and 'data-has-rec="1"' not in page
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "dose_g", "recommended_delta": "1"})
    assert 'data-has-rec="1"' in app.client.get("/browse").text


def test_someone_else_cannot_see_it(app):
    set_admin_password(app)
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, **SUGGEST})
    friend = add_user(app)
    app.sign_in(friend)
    assert "a bit sour" not in app.client.get("/").text


def test_round_trips_and_older_snapshots_import(app, tmp_path: Path):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", {**COMBO, **SUGGEST})
    snapshot = tmp_path / "snapshot"
    export_script.export_all(app.engine, snapshot)
    restored = _engine(tmp_path / "restored.db")
    import_script.import_all(restored, snapshot)
    with restored.connect() as conn:
        assert conn.exec_driver_sql(
            "select suggested_param, suggested_delta, suggested_rationale from plannedbrew"
        ).all() == [("grind_size", -1.0, "a bit sour, try finer")]

    plans = snapshot / "planned_brews.csv"
    rows = list(csv.DictReader(plans.open()))
    with plans.open("w", newline="") as f:  # as a snapshot from before these columns
        w = csv.DictWriter(f, fieldnames=["id", "user_id", "bag_id", "brewer_id", "grinder_id", "line_id", "notes", "created_at"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})
    older = _engine(tmp_path / "older.db")
    import_script.import_all(older, snapshot)
    with older.connect() as conn:
        assert conn.exec_driver_sql("select suggested_param from plannedbrew").all() == [(None,)]
