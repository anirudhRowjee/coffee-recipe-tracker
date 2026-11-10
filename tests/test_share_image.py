"""
"Share as image" (/lines/{id}/share-image): the data the card is drawn from,
that it keeps to the same privacy whitelist as the text export, and the link to it.
The drawing itself happens in the browser and is checked by hand.
"""
import html as html_lib
import json
import re

from test_export_recipe import PRIVATE, dial_in
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture


def card(app, line_id=1):
    r = app.client.get(f"/lines/{line_id}/share-image")
    assert r.status_code == 200
    return json.loads(html_lib.unescape(re.search(r'data-card="([^"]*)"', r.text).group(1)))


def test_card_has_every_parameter(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate", "origin": "India",
                                "roast_level": "Medium", "flavor_notes": "citrus, jaggery"})
    post(app, "/recipes", {**BASELINE, "recipe_text": "Prep: Add the grounds\n0:00 — Bloom (to 50g)\n0:40 — Pour (to 250g)\n3:00 — Done"})
    data = card(app)
    assert data["title"] == "Blue Tokai Baarbara Estate"
    assert data["gear"] == "Hario Switch · Timemore C2"
    assert (data["about"], data["flavour"]) == ("India · Medium", "citrus, jaggery")
    assert data["params"] == [["Dose", "15 g"], ["Water", "250 ml"], ["Ratio", "1:16.7"],
                              ["Temp", "93 °C"], ["Grind", "13"], ["Brew time", "3:00"]]
    assert data["steps"] == [
        {"time": "", "text": "Before you start: Add the grounds"},
        {"time": "0:00", "text": "Bloom · to 50 g"},
        {"time": "0:40", "text": "Pour · to 250 g"},
        {"time": "3:00", "text": "Done"},
    ]
    assert data["filename"] == "blue-tokai-baarbara-estate.png"
    assert data["photo"] == "" and data["colors"]["mesh"] is None
    assert data["colors"]["accent"] == "#6b3d2e"  # the app's brown without a bag photo


def test_free_text_method_and_named_recipe(app):
    post(app, "/recipes", BASELINE)
    post(app, "/recipes", {**BASELINE, "line_name": "2 cup", "dose_g": 30, "water_ml": 500})
    data = card(app)
    assert [s["text"] for s in data["steps"]] == ["Close the switch", "Add all the water"]
    assert not any(s["time"] for s in data["steps"])
    assert [p[0] for p in data["params"]] == ["Dose", "Water", "Ratio", "Temp", "Grind"]  # no brew time to show
    assert card(app, 2)["title"] == "Blue Tokai Baarbara Estate — 2 cup"


def test_bag_colours_and_photo(app):
    post(app, "/recipes", BASELINE)
    post(app, "/beans/1/colors", {"accent": "#e16e35", "mesh1": "#112233", "mesh2": "#445566", "mesh3": "#778899", "mesh4": "#aabbcc"})
    data = card(app)
    assert data["colors"]["mesh"] == ["#112233", "#445566", "#778899", "#aabbcc"]
    assert data["colors"]["accent"] != "#e16e35"  # darkened until text on it is readable


def test_nothing_private_on_the_card(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate", "notes": "SECRET-BEAN-NOTE"})
    post(app, "/bags/1/edit", {"initial_quantity_g": 250, "notes": "SECRET-BAG-NOTE"})
    dial_in(app)
    raw = json.dumps(card(app))
    for marker in PRIVATE:
        assert marker not in raw, marker


def test_recipe_card_links_to_it(app):
    post(app, "/recipes", BASELINE)
    assert 'href="/lines/1/share-image">Share as image</a>' in latest(app)
