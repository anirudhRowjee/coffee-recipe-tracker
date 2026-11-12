"""
Versions: list with cups and ratings, compare, brew an older one once, undo the last
change (one change at a time, never a jump back), fix or delete the newest.
"""
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

V = {**BASELINE, "previous_recipe_id": 1}


def three_versions(app):
    post(app, "/recipes", BASELINE)                                                    # v1: 93 °C, grind 13
    post(app, "/recipes", {**V, "temp_c": "95", "rationale": "flat"})                  # v2: temp
    post(app, "/recipes", {**V, "previous_recipe_id": 2, "temp_c": "95", "grind_size": "12", "rationale": "sour"})  # v3: grind
    post(app, "/brews", {"recipe_id": 2, "bag_id": 1, "rating": "5", "notes": "great"})


def test_the_page_lists_versions_newest_first(app):
    three_versions(app)
    page = app.client.get("/lines/1/versions", params={"bag_id": 1}).text
    assert page.index("Grind 13 → 12") < page.index("Temp 93 → 95 °C") < page.index("Started")
    assert "best rated" in page and "★ 5" in page and "great" in page
    assert "/lines/1/brew?bag_id=1&amp;recipe_id=2" in page  # brew version 2 once


def test_compare_with_now(app):
    three_versions(app)
    page = app.client.get("/lines/1/versions", params={"compare": 1}).text
    assert "Version 1 and version 3" in page and "93 → 95" in page and "13 → 12" in page


def test_brew_an_older_version_once(app):
    three_versions(app)
    page = app.client.get("/lines/1/brew", params={"bag_id": 1, "recipe_id": 2}).text
    assert "Version 2, once · the current version is 3" in page and 'name="recipe_id" value="2"' in page
    assert app.client.get("/lines/1/brew", params={"bag_id": 1, "recipe_id": 999}).status_code == 404


def test_undo_puts_one_value_back_as_a_new_version(app):
    three_versions(app)
    post(app, "/lines/1/undo", {})
    v4 = app.rows("select temp_c, grind_size, previous_recipe_id from recipe where id = 4")[0]
    assert v4 == {"temp_c": 95.0, "grind_size": "13", "previous_recipe_id": 3}
    assert app.rows("select changed_param, delta_amount from delta where to_recipe_id = 4") == [{"changed_param": "grind_size", "delta_amount": 1.0}]


def test_undo_needs_a_change(app):
    post(app, "/recipes", BASELINE)
    post(app, "/lines/1/undo", {}, status=400)


def test_fix_the_newest_versions_own_change(app):
    three_versions(app)
    post(app, "/recipes/3/fix", {"value": "11", "rationale": "quite sour"})
    assert app.scalar("select grind_size from recipe where id = 3") == "11"
    assert app.rows("select changed_param, delta_amount, rationale from delta where to_recipe_id = 3") == [
        {"changed_param": "grind_size", "delta_amount": -2.0, "rationale": "quite sour"}]
    post(app, "/recipes/3/fix", {"value": "13"}, status=400)  # would equal version 2
    post(app, "/recipes/2/fix", {"value": "96"}, status=400)  # not the newest


def test_reword_an_older_reason(app):
    three_versions(app)
    post(app, "/recipes/2/reason", {"rationale": "a bit flat"})
    assert app.scalar("select rationale from delta where to_recipe_id = 2") == "a bit flat"


def test_delete_only_the_newest_without_cups(app):
    three_versions(app)
    post(app, "/recipes/3/delete", {})
    assert app.scalar("select count(*) from recipe where line_id = 1") == 2
    post(app, "/recipes/2/delete", {}, status=400)  # has a cup
    post(app, "/recipes/1/delete", {}, status=400)  # not the newest
