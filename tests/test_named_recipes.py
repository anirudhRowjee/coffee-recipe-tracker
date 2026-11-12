"""
Named recipes: several independent recipes ("Default", "2 cup") for the same
bean/brewer/grinder, each with its own versions, brews, deltas,
recommendations and scheduling.
"""
import re

from app import crud, models
from test_flows import BASELINE, COMBO, app, latest, post, variation  # noqa: F401 — app is a fixture

TWO_CUP = {**BASELINE, "line_name": "2 cup", "dose_g": 30, "water_ml": 500, "grind_size": "14"}


def line_id(app, name):
    return app.scalar("select id from recipeline where name = :name", name=name)


def two_lines(app):
    post(app, "/recipes", BASELINE)   # recipe 1, line "Default"
    post(app, "/recipes", TWO_CUP)    # recipe 2, line "2 cup"
    return line_id(app, "Default"), line_id(app, "2 cup")


# --- creating -----------------------------------------------------------------

def test_first_recipe_is_default_line(app):
    post(app, "/recipes", BASELINE)
    assert app.rows("select name, bean_id, brewer_id, grinder_id from recipeline") == [
        {"name": "Default", "bean_id": 1, "brewer_id": 1, "grinder_id": 1}]
    assert app.scalar("select line_id from recipe") == line_id(app, "Default")


def test_further_recipes_need_a_unique_name(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "line_name": ""}, status=400)
    post(app, "/recipes", {**BASELINE, "line_name": " default "}, status=400)
    post(app, "/recipes", TWO_CUP)
    post(app, "/recipes", TWO_CUP, status=400)
    assert app.scalar("select count(*) from recipeline") == 2
    assert app.scalar("select count(*) from recipe") == 2


def test_same_name_is_fine_on_another_combination(app):
    post(app, "/recipes", TWO_CUP)
    post(app, "/recipes", {**TWO_CUP, "grinder_id": 2})
    assert app.scalar("select count(*) from recipeline where name = '2 cup'") == 2


# --- independent histories ----------------------------------------------------

def test_each_named_recipe_has_its_own_versions_and_deltas(app):
    default, two_cup = two_lines(app)
    post(app, "/recipes", variation(app, 2, dose_g=30, water_ml=500, grind_size="12",
                                    changed_param="grind_size", delta_amount="-2", rationale="2 cup finer"))
    assert app.scalar("select line_id from recipe where id = 3") == two_cup

    html = latest(app, line_id=two_cup)
    assert "<strong>Grind:</strong> 12" in html and "2 cup finer" in html

    html = latest(app, line_id=default)
    assert "<strong>Grind:</strong> 13" in html
    assert "Change history" not in html and "2 cup finer" not in html
    assert f'/lines/{default}/change' in html
    assert 'name="previous_recipe_id" value="1"' in app.client.get(f"/lines/{default}/change", params={"bag_id": 1}).text


def test_variation_stays_in_parent_line(app):
    default, two_cup = two_lines(app)
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size",
                                    delta_amount="-1", line_name="2 cup"))
    assert app.scalar("select line_id from recipe where id = 3") == default
    assert app.scalar("select count(*) from recipeline") == 2


def test_one_parameter_rule_applies_within_a_named_recipe(app):
    two_lines(app)
    # "2 cup" differs from "Default" in several params; a variation is only
    # ever checked against its own parent (recipe 2: 30 g / 500 ml / grind 14)
    post(app, "/recipes", variation(app, 2, dose_g=30, water_ml=500, grind_size="13",
                                    changed_param="grind_size", delta_amount="-1"))
    post(app, "/recipes", variation(app, 2, dose_g=31, water_ml=500, grind_size="13"), status=400)


def test_recommendations_are_per_named_recipe(app):
    default, two_cup = two_lines(app)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "grind_size", "recommended_delta": "-1"})
    assert 'data-rec="brew"' in latest(app, line_id=default)
    assert 'data-rec="brew"' not in latest(app, line_id=two_cup)


def test_bag_quantity_counts_brews_from_every_named_recipe(app):
    two_lines(app)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    post(app, "/brews", {"recipe_id": 2, "bag_id": 1})
    with app.session() as s:
        assert crud.get_remaining_quantity(s, s.get(models.BeanBag, 1)) == 250 - 15 - 30


# --- picking ------------------------------------------------------------------

def test_picker_only_appears_with_more_than_one_recipe(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert '<select name="line_id">' not in html
    assert "· Default" not in html  # a lone Default recipe looks exactly as before

    post(app, "/recipes", TWO_CUP)
    html = latest(app)
    assert '<select name="line_id">' in html
    assert ">Default</option>" in html and ">2 cup</option>" in html


def test_renamed_lone_recipe_shows_its_name(app):
    post(app, "/recipes", BASELINE)
    post(app, f"/lines/{line_id(app, 'Default')}/rename", {"name": "Coffee Chronicler"})
    assert "· Coffee Chronicler</p>" in latest(app)


def test_default_selection_is_most_recently_used(app):
    default, two_cup = two_lines(app)
    assert "<strong>Grind:</strong> 14" in latest(app)  # 2 cup was created last
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    assert "<strong>Grind:</strong> 13" in latest(app)  # then Default was brewed


def test_unknown_line_id_falls_back_to_default(app):
    two_lines(app)
    assert "<strong>Grind:</strong> 14" in latest(app, line_id=999)


# --- scheduling ---------------------------------------------------------------

def test_plan_remembers_the_named_recipe(app):
    default, two_cup = two_lines(app)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})  # make Default the most recent
    post(app, "/plan", {**COMBO, "line_id": two_cup})
    assert app.scalar("select line_id from plannedbrew") == two_cup

    home = app.client.get("/").text
    assert 'data-planned="1"' in home and "<strong>Grind:</strong> 14" in home
    assert "Planned as Up next" in home

    assert "Planned as Up next" not in latest(app, line_id=default)
    assert "Planned as Up next" in latest(app, line_id=two_cup)


def test_plan_without_line_uses_the_default_recipe(app):
    default, two_cup = two_lines(app)
    post(app, "/plan", COMBO)  # like the browse page's form
    home = app.client.get("/").text
    assert "<strong>Grind:</strong> 14" in home and "Planned as Up next" in home
    assert "Planned as Up next" not in latest(app, line_id=default)


def test_plan_ignores_a_line_from_another_combination(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    other = app.scalar("select id from recipeline where grinder_id = 2")
    post(app, "/plan", {**COMBO, "line_id": other})
    assert app.scalar("select line_id from plannedbrew") is None


def test_logging_planned_named_recipe_clears_plan(app):
    default, two_cup = two_lines(app)
    post(app, "/plan", {**COMBO, "line_id": two_cup})
    plan_id = app.scalar("select id from plannedbrew")
    post(app, "/brews", {"recipe_id": 2, "bag_id": 1, "planned_brew_id": plan_id})
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_browse_schedule_form_offers_each_recipe_with_its_gear(app):
    two_lines(app)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2, "line_name": "Budan one"})
    html = app.client.get("/browse").text
    assert '<select name="line_id" required>' in html
    for label in ("Default · Hario Switch · Timemore C2", "2 cup · Hario Switch · Timemore C2", "Budan one · Hario Switch · Budan"):
        assert label in html, label


def test_plan_takes_gear_from_the_chosen_recipe(app):
    default, two_cup = two_lines(app)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2, "line_name": "Budan one"})
    budan = line_id(app, "Budan one")
    # blank selects, exactly what the browse form posts
    post(app, "/plan", {"bag_id": 1, "brewer_id": "", "grinder_id": "", "line_id": budan})
    assert app.rows("select brewer_id, grinder_id, line_id from plannedbrew") == [
        {"brewer_id": 1, "grinder_id": 2, "line_id": budan}]
    assert "<strong>Grind:</strong> 13" in app.client.get("/").text


def test_plan_with_other_gear_uses_that_combinations_default(app):
    default, two_cup = two_lines(app)
    post(app, "/plan", {"bag_id": 1, "brewer_id": "", "grinder_id": 2, "line_id": two_cup})
    assert app.rows("select brewer_id, grinder_id, line_id from plannedbrew") == [
        {"brewer_id": 1, "grinder_id": 2, "line_id": None}]


def test_plan_with_neither_recipe_nor_gear_is_rejected(app):
    post(app, "/plan", {"bag_id": 1}, status=400)
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_plan_ignores_a_recipe_for_another_bean(app):
    post(app, "/recipes", BASELINE)
    post(app, "/beans", {"name": "Other bean"})
    post(app, "/bags", {"bean_id": 2, "initial_quantity_g": 250})
    post(app, "/plan", {"bag_id": 2, "line_id": line_id(app, "Default")}, status=400)


def test_browse_history_shows_recipe_and_grinder(app):
    two_lines(app)
    post(app, "/brews", {"recipe_id": 2, "bag_id": 1, "notes": "two cups"})
    entry = re.search(r'<span class="brew-date">(.*?)</span>', app.client.get("/browse").text, re.S).group(1)
    assert "2 cup" in entry and "Timemore C2" in entry and "30 g · grind" in entry and "grind 14" in entry


# --- rename / delete ------------------------------------------------------------

def test_rename_rejects_duplicates_and_blanks(app):
    default, two_cup = two_lines(app)
    post(app, f"/lines/{two_cup}/rename", {"name": "DEFAULT"}, status=400)
    post(app, f"/lines/{two_cup}/rename", {"name": "   "}, status=400)
    post(app, f"/lines/{two_cup}/rename", {"name": "Coffee Chronicler"})
    post(app, f"/lines/{two_cup}/rename", {"name": "Coffee Chronicler"})  # renaming to itself is fine
    assert app.scalar("select name from recipeline where id = :i", i=two_cup) == "Coffee Chronicler"


def test_delete_named_recipe_removes_only_its_history(app):
    default, two_cup = two_lines(app)
    post(app, "/recipes", variation(app, 2, dose_g=30, water_ml=500, grind_size="12",
                                    changed_param="grind_size", delta_amount="-2"))
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    post(app, "/plan", {**COMBO, "line_id": two_cup})

    post(app, f"/lines/{two_cup}/delete", {})
    assert app.rows("select id, name from recipeline") == [{"id": default, "name": "Default"}]
    assert app.rows("select id from recipe") == [{"id": 1}]
    assert app.rows("select recipe_id from brew") == [{"recipe_id": 1}]
    assert app.scalar("select count(*) from delta") == 0
    assert app.scalar("select count(*) from plannedbrew") == 0


def test_deleting_grinder_or_bean_removes_their_named_recipes(app):
    two_lines(app)
    post(app, "/recipes", {**BASELINE, "grinder_id": 2})
    post(app, "/grinders/1/delete", {})
    assert app.rows("select grinder_id from recipeline") == [{"grinder_id": 2}]
    post(app, "/beans/1/delete", {})
    assert app.scalar("select count(*) from recipeline") == 0


# --- browse ---------------------------------------------------------------------

def test_browse_names_the_latest_recipe_when_not_default(app):
    post(app, "/recipes", BASELINE)
    assert "Current recipe</h4>" in app.client.get("/browse").text
    post(app, "/recipes", TWO_CUP)
    assert "Current recipe · 2 cup</h4>" in app.client.get("/browse").text
