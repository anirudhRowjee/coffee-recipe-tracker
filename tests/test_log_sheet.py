"""
Logging a cup by tapping: taste and Next time chips fill the usual fields, and
"Change steps" can go straight to the step editor with the scale's real timings.
"""
import json

from app import brew
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture

STEPS = "0:00 — Bloom (to 44g)\n0:45 — Pour (to 96g)\n1:30 — Pour (to 240g)\n2:45 — Done"


def _curve():
    t = [i * 0.5 for i in range(400)]

    def w(x):
        if x < 5:
            return x * 9
        if x < 45:
            return 44
        if x < 52:
            return 44 + (x - 45) * 7.5
        if x < 90:
            return 96
        return min(240, 96 + (x - 90) * 8)
    return {"t": t, "g": [w(x) for x in t], "f": [0] * len(t)}


def test_the_form_offers_chips_over_the_plain_fields(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert 'data-word="sour"' in html and 'data-param="grind_size" data-amount="-1"' in html
    assert 'data-param="recipe_text"' in html and 'name="recommended_param"' in html  # the real field stays
    assert 'name="rating"' in app.client.get("/lines/1/brew", params={"bag_id": 1}).text


def test_real_timings_from_a_curve():
    out = brew.actual_timings(STEPS, _curve())
    assert out[:3] == [{"start": 0, "reached": 5, "grams": 44}, {"start": 46, "reached": 52, "grams": 96},
                       {"start": 90, "reached": 108, "grams": 240}]
    assert brew.actual_timings("45g 40s", _curve()) == []  # free text: nothing to line up


def test_save_and_edit_the_steps_now(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STEPS})
    r = app.client.post("/brews", data={"recipe_id": 1, "bag_id": 1, "notes": "rushed bloom", "recommended_param": "recipe_text",
                                        "then": "change", "curve": json.dumps(_curve())}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/lines/1/change?bag_id=1&method=1&actual=1"
    page = app.client.get(r.headers["location"]).text
    assert "Change the steps" in page and "Cup saved to version 1" in page and 'data-start-method="1"' in page
    assert "&#34;reached&#34;: 52" in page  # the real timings, for the step rows
    assert app.scalar("select count(*) from brew") == 1


def test_someone_elses_timings_are_not_shown(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": STEPS})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "curve": json.dumps(_curve())})
    page = app.client.get("/lines/1/change", params={"bag_id": 1, "actual": 999}).text
    assert 'data-actuals=""' in page
