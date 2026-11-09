"""
Behaviour tests for the brewing flows, run against a fresh database through
the real HTTP routes: baseline recipe → log brews → one-parameter variations,
scheduling (plan / replace / cancel / consume), browse, and delete cascades.

These were written against the single-chain-per-combination app and must keep
passing unchanged with named recipes: a combination with one recipe behaves
exactly as before.
"""
import pytest

from app import crud, models

COMBO = {"bag_id": 1, "brewer_id": 1, "grinder_id": 1}
BASELINE = {
    "bean_id": 1, "brewer_id": 1, "grinder_id": 1,
    "dose_g": 15, "water_ml": 250, "temp_c": 93, "grind_size": "13",
    "recipe_text": "Close the switch\nAdd all the water",
}


def post(app, url, data, status=303):
    r = app.client.post(url, data=data, follow_redirects=False)
    assert r.status_code == status, r.text
    return r


@pytest.fixture
def app(app_on):
    a = app_on()
    post(a, "/beans", {"name": "Blue Tokai Baarbara Estate", "flavor_notes": "citrus"})
    post(a, "/bags", {"bean_id": 1, "initial_quantity_g": 250})
    post(a, "/brewers", {"name": "Hario Switch"})
    post(a, "/grinders", {"name": "Timemore C2"})
    post(a, "/grinders", {"name": "Budan"})
    return a


def latest(app, **params):
    r = app.client.get("/recipes/latest", params={**COMBO, **params})
    assert r.status_code == 200
    return r.text


def variation(app, prev_id, **changes):
    data = {**BASELINE, "previous_recipe_id": prev_id, "bag_id": 1}
    data.update(changes)
    return data


# --- basics --------------------------------------------------------------

def test_no_user_cookie_redirects_to_select_user(app_on):
    a = app_on(user_id=None)
    r = a.client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"


def test_stale_user_cookie_redirects_and_is_cleared(app_on):
    a = app_on(user_id=999)
    r = a.client.get("/browse", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"
    assert 'session=""' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]


def test_incomplete_selection_prompts(app):
    r = app.client.get("/recipes/latest", params={"bag_id": 1})
    assert "Select a bag, brewer, and grinder" in r.text


def test_combination_without_recipe_offers_baseline(app):
    html = latest(app)
    assert "No recipe yet for this combination" in html
    assert "Save baseline recipe" in html


# --- baseline, brews, variations ------------------------------------------

def test_baseline_recipe_is_shown_for_its_combination(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert "<strong>Dose:</strong> 15.0 g" in html
    assert "<strong>Grind:</strong> 13" in html
    assert "Close the switch" in html
    assert app.rows("select previous_recipe_id from recipe") == [{"previous_recipe_id": None}]


def test_history_is_per_combination(app):
    post(app, "/recipes", BASELINE)
    assert "No recipe yet" in latest(app, grinder_id=2)


def test_history_is_shared_across_bags_of_the_same_bean(app):
    post(app, "/recipes", BASELINE)
    post(app, "/bags", {"bean_id": 1, "initial_quantity_g": 200})
    assert "<strong>Grind:</strong> 13" in latest(app, bag_id=2)


def test_log_brew_stores_signed_recommendation_and_uses_dose(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {
        "recipe_id": 1, "bag_id": 1, "notes": "sour",
        "recommended_param": "grind_size", "recommended_delta": "-1",
        "recommended_rationale": "extract more",
    })
    brew = app.rows("select notes, recommended_param, recommended_delta from brew")
    assert brew == [{"notes": "sour", "recommended_param": "grind_size", "recommended_delta": -1.0}]

    html = latest(app)
    assert "Recommended next" in html
    assert 'data-delta="-1.0"' in html  # feeds applyRecommendation()
    assert "Apply: grind size -1" in html

    with app.session() as s:
        assert crud.get_remaining_quantity(s, s.get(models.BeanBag, 1)) == 235.0


def test_variation_must_change_exactly_one_parameter(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, grind_size="12", dose_g=16), status=400)
    post(app, "/recipes", variation(app, 1), status=400)  # nothing changed
    assert app.scalar("select count(*) from recipe") == 1
    assert app.scalar("select count(*) from delta") == 0


def test_variation_creates_version_delta_and_brew(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(
        app, 1, grind_size="12", changed_param="grind_size", delta_amount="-1",
        rationale="extract more", brew_notes="better",
        brew_recommended_param="temp_c", brew_recommended_delta="2",
    ))
    assert app.rows("select id, previous_recipe_id, grind_size from recipe order by id") == [
        {"id": 1, "previous_recipe_id": None, "grind_size": "13"},
        {"id": 2, "previous_recipe_id": 1, "grind_size": "12"},
    ]
    assert app.rows("select from_recipe_id, to_recipe_id, changed_param, delta_amount, rationale from delta") == [
        {"from_recipe_id": 1, "to_recipe_id": 2, "changed_param": "grind_size", "delta_amount": -1.0, "rationale": "extract more"},
    ]
    assert app.rows("select recipe_id, bag_id, notes, recommended_param, recommended_delta from brew") == [
        {"recipe_id": 2, "bag_id": 1, "notes": "better", "recommended_param": "temp_c", "recommended_delta": 2.0},
    ]
    html = latest(app)
    assert "<strong>Grind:</strong> 12" in html
    assert "Change history" in html and "extract more" in html
    assert 'name="previous_recipe_id" value="2"' in html


def test_recipe_text_variation_stores_zero_delta(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, recipe_text="Bloom 30s", changed_param="recipe_text"))
    assert app.scalar("select delta_amount from delta") == 0.0


# --- scheduling -------------------------------------------------------------

def test_plan_shows_scheduled_brew_on_home_page(app):
    post(app, "/recipes", BASELINE)
    assert "Scheduled brew" not in app.client.get("/").text
    post(app, "/plan", {**COMBO, "notes": "want it stronger"})
    html = app.client.get("/").text
    assert "Scheduled brew" in html
    assert "<strong>Grind:</strong> 13" in html
    assert "Planned for next time" in html and "want it stronger" in html


def test_new_plan_replaces_old_and_cancel_removes(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", COMBO)
    post(app, "/plan", {**COMBO, "grinder_id": 2})
    assert app.rows("select grinder_id from plannedbrew") == [{"grinder_id": 2}]
    plan_id = app.scalar("select id from plannedbrew")
    post(app, f"/plan/{plan_id}/cancel", {})
    assert app.scalar("select count(*) from plannedbrew") == 0
    assert "Scheduled brew" not in app.client.get("/").text


def test_plan_status_only_shown_for_the_planned_combination(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    post(app, "/plan", COMBO)
    assert "Planned for next time" in latest(app)
    other = latest(app, grinder_id=2)
    assert "Planned for next time" not in other and "Plan for next time" in other


def test_logging_planned_brew_clears_plan(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", COMBO)
    plan_id = app.scalar("select id from plannedbrew")
    assert f'name="planned_brew_id" value="{plan_id}"' in app.client.get("/").text
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "planned_brew_id": plan_id})
    assert app.scalar("select count(*) from plannedbrew") == 0
    assert app.scalar("select count(*) from brew") == 1


def test_variation_on_planned_brew_clears_plan(app):
    post(app, "/recipes", BASELINE)
    post(app, "/plan", COMBO)
    plan_id = app.scalar("select id from plannedbrew")
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size",
                                    delta_amount="-1", planned_brew_id=plan_id))
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_plan_from_browse_page_shows_on_home(app):
    post(app, "/recipes", BASELINE)
    assert "Schedule next brew" in app.client.get("/browse").text
    post(app, "/plan", {**COMBO, "notes": "from browse"})
    assert "from browse" in app.client.get("/").text


# --- browse / manage ---------------------------------------------------------

def test_browse_shows_latest_version_per_bean(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size", delta_amount="-1"))
    html = app.client.get("/browse").text
    assert "<strong>Grind:</strong> 12" in html
    assert "<strong>Grind:</strong> 13" not in html


def test_completed_bag_is_hidden_from_picker(app):
    assert 'data-id="1"' in app.client.get("/").text
    post(app, "/bags/1/complete", {})
    assert 'data-id="1"' not in app.client.get("/").text


def test_delete_bag_removes_its_brews_and_plans(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    post(app, "/plan", COMBO)
    post(app, "/bags/1/delete", {})
    assert app.scalar("select count(*) from brew") == 0
    assert app.scalar("select count(*) from plannedbrew") == 0
    assert app.scalar("select count(*) from recipe") == 1  # recipes belong to the bean


def test_delete_grinder_cascades_its_recipes_only(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size", delta_amount="-1"))
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    post(app, "/plan", COMBO)
    post(app, "/grinders/1/delete", {})
    assert app.rows("select grinder_id from recipe") == [{"grinder_id": 2}]
    assert app.scalar("select count(*) from delta") == 0
    assert app.scalar("select count(*) from brew") == 0
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_delete_bean_cascades_everything(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size", delta_amount="-1"))
    post(app, "/plan", COMBO)
    post(app, "/beans/1/delete", {})
    for table in ["bean", "beanbag", "recipe", "brew", "delta", "plannedbrew"]:
        assert app.scalar(f"select count(*) from {table}") == 0, table
