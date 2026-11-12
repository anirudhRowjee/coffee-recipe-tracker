"""
Brew opens on "Up next": the planned brew, else the coffee brewed most recently with
the gear and recipe used, else a choice of coffees. Picking a coffee brings back its
gear; a recipe can be copied onto a coffee and gear that has none.
"""
from test_flows import BASELINE, COMBO, app, post  # noqa: F401 — app is a fixture


def home(app, **params):
    r = app.client.get("/", params=params)
    assert r.status_code == 200
    return r.text


def test_nothing_brewed_yet_asks_what_to_brew(app):
    post(app, "/recipes", BASELINE)
    page = home(app)
    assert "What are we brewing?" in page and 'href="/?bag_id=1"' in page and "Start brewing" not in page


def test_the_last_coffee_brewed_is_up_next(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    page = home(app)
    assert "Start brewing" in page and "/lines/1/brew?bag_id=1" in page and 'data-planned="1"' not in page
    assert "What are we brewing?" in home(app, pick=1)


def test_a_plan_wins(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    post(app, "/plan", COMBO)
    assert 'data-planned="1"' in home(app) and "Planned as Up next" in home(app)


def test_picking_a_coffee_brings_back_its_gear(app):
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    page = home(app, bag_id=1)
    assert "/lines/1/brew?bag_id=1" in page  # brewer 1 and grinder 2 came from its recipe


def test_a_coffee_never_brewed_asks_for_gear(app):
    post(app, "/beans", {"name": "New one"})
    bean = app.scalar("select max(id) from bean")
    post(app, "/bags", {"bean_id": bean, "initial_quantity_g": 250})
    bag = app.scalar("select max(id) from beanbag")
    page = home(app, bag_id=bag)
    assert "What are you brewing it with?" in page and f"/?bag_id={bag}&amp;brewer_id=1" in page
    page = home(app, bag_id=bag, brewer_id=1, grinder_id=1)
    assert "No recipe yet for this coffee" in page and "Copy one of your recipes" not in page


def test_copy_a_recipe_onto_another_coffee(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": "0:00 — Bloom (to 40g)"})
    post(app, "/beans", {"name": "New one"})
    bean = app.scalar("select max(id) from bean")
    post(app, "/bags", {"bean_id": bean, "initial_quantity_g": 250})
    bag = app.scalar("select max(id) from beanbag")
    page = home(app, bag_id=bag, brewer_id=1, grinder_id=1)
    assert "Copy one of your recipes" in page and 'action="/lines/1/copy"' in page
    r = app.client.post("/lines/1/copy", data={"bean_id": bean, "brewer_id": 1, "grinder_id": 1, "bag_id": bag}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/?bag_id={bag}&brewer_id=1&grinder_id=1&line_id=2"
    assert app.rows("select bean_id, dose_g, grind_size, recipe_text, previous_recipe_id from recipe where line_id = 2") == [
        {"bean_id": bean, "dose_g": 15.0, "grind_size": "13", "recipe_text": "0:00 — Bloom (to 40g)", "previous_recipe_id": None}]
    # copying again onto the same coffee and gear gets a free name
    post(app, "/lines/1/copy", {"bean_id": bean, "brewer_id": 1, "grinder_id": 1})
    names = [r["name"] for r in app.rows(f"select name from recipeline where bean_id = {bean} order by id")]
    assert names[0] == "Default" and names[1] != "Default"


def test_the_oldest_open_bag_is_used_first(app):
    post(app, "/recipes", BASELINE)
    post(app, "/bags", {"bean_id": 1, "initial_quantity_g": 250, "roast_date": "2020-01-01"})
    older = app.scalar("select max(id) from beanbag")
    assert f'href="/?bag_id={older}"' in home(app)
    post(app, "/bags", {"bean_id": 1, "initial_quantity_g": 250, "roast_date": "2019-01-01", "is_frozen": "true"})
    assert f'href="/?bag_id={older}"' in home(app)  # a frozen bag waits
