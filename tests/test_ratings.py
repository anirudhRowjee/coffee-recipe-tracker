"""
Star ratings on brews: logging, validation, display, and privacy.
"""
import re

import pytest

from test_flows import BASELINE, app, latest, post, variation  # noqa: F401 — app is a fixture


def test_log_brew_with_rating_shows_stars(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "lovely", "rating": "4"})
    assert app.scalar("select rating from brew") == 4
    assert "★★★★☆" in latest(app)
    assert "★★★★☆" in app.client.get("/browse").text


@pytest.mark.parametrize("value", ["", "0", "6", "-1", "four", "4.5"])
def test_invalid_rating_is_stored_as_unrated(app, value):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "rating": value})
    assert app.scalar("select rating from brew") is None


def test_unrated_brew_shows_no_stars(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    assert 'class="brew-stars"' not in latest(app)


def test_variation_can_rate_its_brew(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", variation(app, 1, grind_size="12", changed_param="grind_size",
                                    delta_amount="-1", brew_rating="5"))
    assert app.rows("select recipe_id, rating from brew") == [{"recipe_id": 2, "rating": 5}]


def test_each_form_has_its_own_star_field(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert len(re.findall(r'type="radio" id="rating-\d" name="rating"', html)) == 5
    change = app.client.get("/lines/1/change", params={"bag_id": 1}).text
    assert len(re.findall(r'type="radio" id="brew_rating-\d" name="brew_rating"', change)) == 5
    assert 'name="rating"' in app.client.get("/lines/1/brew", params={"bag_id": 1}).text


def test_rating_is_not_in_the_shared_recipe(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "rating": "2"})
    text = app.client.get("/lines/1/export.md").text
    assert "★" not in text and "rating" not in text.lower()
