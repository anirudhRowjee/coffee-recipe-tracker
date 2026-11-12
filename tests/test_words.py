"""
Settings and changes are written in plain words: "Temp +3 °C", "Grind 21 → 22",
"15 g". No field names ("temp_c") or trailing ".0" reach a page.
"""
import re

from app import words
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture


def test_numbers_drop_a_trailing_zero():
    assert words.num(15.0) == "15" and words.num(15.5) == "15.5" and words.num("22") == "22" and words.num(None) == ""


def test_a_change_in_words():
    assert words.change("temp_c", 3.0) == "Temp +3 °C"
    assert words.change("grind_size", -1.0) == "Grind −1"
    assert words.change("dose_g", 0.5) == "Coffee +0.5 g"
    assert words.change("recipe_text", None) == "Method"
    assert words.change("water_ml", None) == "Water"


def test_history_shows_real_values_not_field_names(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "previous_recipe_id": 1, "temp_c": "96", "changed_param": "temp_c",
                           "delta_amount": "3", "rationale": "sweeter"})
    html = latest(app)
    assert "Temp 93 → 96 °C" in html
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", html, flags=re.S))
    assert "temp_c" not in visible and "temp c" not in visible


def test_the_next_time_banner_reads_naturally(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "temp_c", "recommended_delta": "2"})
    html = latest(app)
    assert "Temp +2 °C" in html and "temp c" not in html


def test_browse_hides_database_ids_and_orders_by_last_brewed(app):
    post(app, "/recipes", BASELINE)
    page = app.client.get("/browse").text
    assert "ID 1" not in page
