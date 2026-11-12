"""
First run: a checklist on Brew until the first recipe exists (coffee and bag, gear by
tapping, then a starting recipe), and starting recipes for the brewer picked.
"""
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

CHECKLIST = "set up your first cup"


def fresh(app):
    uid = add_user(app)
    app.sign_in(uid)
    return uid


def test_someone_new_gets_the_checklist(app):
    fresh(app)
    html = app.client.get("/").text
    assert CHECKLIST in html and "0 of 3 done" in html
    assert html.index("Add your coffee") < html.index("What do you brew with?") < html.index("Pick a starting recipe")
    assert 'data-sheet="add-coffee-sheet"' in html and 'id="add-coffee-sheet"' in html


def test_coffee_and_bag_in_one_go_then_gear_by_tapping(app):
    fresh(app)
    post(app, "/beans", {"name": "Attikan", "initial_quantity_g": "340", "flavor_notes": "Chocolate, Caramel", "next": "/"})
    assert app.rows("select initial_quantity_g from beanbag order by id desc limit 1") == [{"initial_quantity_g": 340.0}]
    html = app.client.get("/").text
    assert "1 of 3 done" in html and "Pre-ground" in html
    post(app, "/brewers", {"name": "AeroPress", "method": "AeroPress", "next": "/"})
    post(app, "/grinders", {"name": "Pre-ground", "next": "/"})
    html = app.client.get("/").text
    assert "2 of 3 done" in html and "Choose a recipe" in html


def test_starting_recipes_for_the_brewer(app):
    fresh(app)
    post(app, "/beans", {"name": "Attikan", "initial_quantity_g": "250"})
    post(app, "/brewers", {"name": "AeroPress", "method": "AeroPress"})
    post(app, "/grinders", {"name": "Pre-ground"})
    bag = app.scalar("select max(id) from beanbag")
    brewer = app.scalar("select max(id) from brewer")
    grinder = app.scalar("select max(id) from grinder")
    html = app.client.get("/", params={"bag_id": bag, "brewer_id": brewer, "grinder_id": grinder}).text
    assert "Classic AeroPress" in html and 'name="grind_size" value="pre-ground"' in html


def test_gone_once_there_is_a_recipe(app):
    post(app, "/recipes", BASELINE)
    assert CHECKLIST not in app.client.get("/").text


def test_only_on_the_brew_page(app):
    fresh(app)
    for page in ["/browse", "/manage"]:
        assert CHECKLIST not in app.client.get(page).text
