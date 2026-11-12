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


def card(app, line_id=1, **params):
    r = app.client.get(f"/lines/{line_id}/share-image", params=params)
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


def test_tasting_notes_only_when_asked_for(app):
    dial_in(app)
    page = app.client.get("/lines/1/share-image").text
    assert "SECRET-TASTING-NOTE" not in page and "SECRET-BREW-NOTE" not in page
    assert 'href="/lines/1/share-image?notes=1">Add one of my tasting notes' in page
    assert "No tasting notes or ratings are on it." in page
    data = card(app, notes=1)
    # the brew's tasting notes, newest first; still nothing else private
    assert [n["text"] for n in data["notes"]] == ["SECRET-BREW-NOTE", "SECRET-TASTING-NOTE"]
    raw = json.dumps(data)
    for marker in ("SECRET-RECOMMENDATION", "SECRET-BEAN-NOTE", "SECRET-PLAN-NOTE", "Anirudh"):
        assert marker not in raw, marker
    assert "(grind 13" in data["notes"][1]["when"]  # says which version it was about
    page = app.client.get("/lines/1/share-image", params={"notes": 1}).text
    assert 'id="share-note-text"' in page and 'href="/lines/1/share-image">Remove the tasting note' in page


def test_brew_mode_lines_are_left_out_of_notes(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "Brewed 3:54 · 500 g\r\nLots of chocolate", "rating": 4})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "Brewed 3:10 · 480 g"})  # nothing to share
    assert card(app, notes=1)["notes"] == [{"when": card(app, notes=1)["notes"][0]["when"], "text": "Lots of chocolate", "rating": 4}]


def test_no_notes_no_offer(app):
    post(app, "/recipes", BASELINE)
    page = app.client.get("/lines/1/share-image").text
    assert "Add one of my tasting notes" not in page
    assert "notes" not in card(app, notes=1)


def test_story_format_and_links_keep_the_other_switches(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "nice"})
    assert card(app)["story"] is False and card(app, format="story")["story"] is True
    page = app.client.get("/lines/1/share-image", params={"notes": 1, "format": "story"}).text
    assert 'href="/lines/1/share-image?notes=1">Post (4:5)' in page
    assert 'href="/lines/1/share-image?format=story">Remove the tasting note' in page
