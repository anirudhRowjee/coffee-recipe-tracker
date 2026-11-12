"""
Scale curves saved with a brew (BrewCurve): saving from the log form, what counts as a
valid curve, the graph page with its comparison and CSV, links from the history, the
share image's opt-in curve, and that deleting anything deletes its curves.
The drawing (graphs, PNG, share image) happens in the browser and is checked by hand.
"""
import html as html_lib
import json
import re
from pathlib import Path

import pytest
from sqlmodel import select

from test_accounts import PASSWORD, add_user, set_admin_password
from test_export_import import _round_trip, _seed_one_brew
from test_flows import BASELINE, app, latest, post, variation  # noqa: F401 — app is a fixture
from app import crud, models

METHOD = "0:00 — Bloom (to 50g)\n0:40 — Pour (to 250g)\n3:00 — Done"


def curve(n=5, scale=1.0):
    return {"t": [i * 0.5 for i in range(n)], "g": [i * 10.0 * scale for i in range(n)], "f": [20.0 * scale] * n}


def log(app, recipe_id=1, samples=None, **extra):
    data = {"recipe_id": recipe_id, "bag_id": 1, **extra}
    if samples is not None:
        data["curve"] = samples if isinstance(samples, str) else json.dumps(samples)
    post(app, "/brews", data)


def stored(app):
    with app.session() as s:
        return {c.brew_id: json.loads(c.samples) for c in s.exec(select(models.BrewCurve)).all()}


def graph_data(app, brew_id, **params):
    r = app.client.get(f"/brews/{brew_id}/graph", params=params)
    assert r.status_code == 200, r.text
    return json.loads(html_lib.unescape(re.search(r'data-graph="([^"]*)"', r.text).group(1))), r.text


def test_logging_from_brew_mode_saves_the_curve(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    log(app, samples=curve(), notes="lovely")
    assert stored(app) == {1: curve()}
    data, page = graph_data(app, 1)
    assert data["brew"]["t"] == curve()["t"] and data["brew"]["g"] == curve()["g"]
    assert data["brew"]["targets"] == [[0, 50.0], [40, 250.0]]  # from the version it was brewed with
    assert data["compare"] is None and "Compare with" not in page
    assert "lovely" in page and 'href="/brews/1/curve.csv"' in page


def test_a_brew_without_a_curve_has_no_graph(app):
    post(app, "/recipes", BASELINE)
    log(app)                       # the recipe panel's form
    log(app, samples="")           # brew mode without a scale
    assert stored(app) == {}
    assert app.client.get("/brews/1/graph").status_code == 404
    assert app.client.get("/brews/2/curve.csv").status_code == 404
    assert "/graph" not in latest(app)


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps([1, 2, 3]),
    json.dumps({"t": [0, 1], "g": [0]}),                                   # no flow
    json.dumps({"t": [0, 1], "g": [0], "f": [0, 1]}),                      # lengths differ
    json.dumps({"t": [0], "g": [0], "f": [0]}),                            # one point
    json.dumps({"t": [0, 2, 1], "g": [0, 1, 2], "f": [0, 0, 0]}),          # time goes backwards
    json.dumps({"t": [-1, 1], "g": [0, 1], "f": [0, 0]}),
    json.dumps({"t": [0, 1], "g": [0, "x"], "f": [0, 0]}),
    '{"t": [0, 1], "g": [0, NaN], "f": [0, 0]}',
    json.dumps({"t": [0, 1], "g": [0, 1e9], "f": [0, 0]}),
    json.dumps({"t": list(range(20000)), "g": [0] * 20000, "f": [0] * 20000}),  # too long
])
def test_a_bad_curve_is_dropped_but_the_brew_is_still_logged(app, bad):
    post(app, "/recipes", BASELINE)
    log(app, samples=bad, notes="keep my notes")
    assert stored(app) == {}
    with app.session() as s:
        assert s.get(models.Brew, 1).notes == "keep my notes"


def test_curves_are_stored_compactly_and_rounded(app):
    post(app, "/recipes", BASELINE)
    log(app, samples={"t": [0, 0.512, 0.98], "g": [0.04, 10.06, 20.0], "f": [1.234, 2, 3]})
    assert stored(app) == {1: {"t": [0.0, 0.5, 1.0], "g": [0.0, 10.1, 20.0], "f": [1.23, 2.0, 3.0]}}
    with app.session() as s:
        assert " " not in s.get(models.BrewCurve, 1).samples


def test_csv_download(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve(3))
    r = app.client.get("/brews/1/curve.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="brew-1-')
    assert r.text == "seconds,grams,grams_per_second\n0,0,20\n0.5,10,20\n1,20,20\n"


def test_compares_with_the_brew_before_it_by_default(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())                  # brew 1
    log(app)                                   # brew 2, no curve
    post(app, "/recipes", variation(app, 1, grind_size="12"))         # recipe 2: one change
    log(app, recipe_id=2, samples=curve(scale=2))
    newest = max(stored(app))  # saving a variation can log a brew too, so don't assume ids
    data, page = graph_data(app, newest)
    assert data["compare"]["g"] == curve()["g"]
    assert "(grind 13)" in data["compare"]["label"]  # what differed from the version being viewed
    assert "Compare with" in page
    assert graph_data(app, newest, compare=0)[0]["compare"] is None
    assert graph_data(app, 1)[0]["compare"] is None     # nothing older
    assert graph_data(app, 1, compare=newest)[0]["compare"]["g"] == curve(scale=2)["g"]


def test_only_brews_of_the_same_named_recipe_can_be_compared(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())
    post(app, "/recipes", {**BASELINE, "line_name": "2 cup", "dose_g": 30, "water_ml": 500})  # recipe 2, line 2
    log(app, recipe_id=2, samples=curve())
    assert app.client.get("/brews/2/graph", params={"compare": 1}).status_code == 404
    assert "Compare with" not in graph_data(app, 2)[1]


def test_history_links_to_graphs(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())
    log(app)
    panel = latest(app)
    assert 'href="/brews/1/graph">Graph</a>' in panel and "/brews/2/graph" not in panel
    browse = app.client.get("/browse").text
    assert 'href="/brews/1/graph">Graph</a>' in browse and "/brews/2/graph" not in browse


def test_brew_mode_has_the_field_and_the_save_button(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    page = app.client.get("/lines/1/brew", params={"bag_id": 1}).text
    assert 'name="curve" id="log-curve" value=""' in page
    assert 'id="brew-graphs-png"' in page


def share_card(app, **params):
    r = app.client.get("/lines/1/share-image", params=params)
    assert r.status_code == 200
    return json.loads(html_lib.unescape(re.search(r'data-card="([^"]*)"', r.text).group(1))), r.text


def test_share_image_curve_is_opt_in(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    card, page = share_card(app)
    assert "curve" not in card and "weight curve" not in page   # nothing to offer yet
    log(app, samples=curve())
    card, page = share_card(app)
    assert "curve" not in card                                  # off unless asked for
    assert 'href="/lines/1/share-image?curve=1">Add the weight curve' in page
    card, page = share_card(app, curve=1)
    assert card["curve"] == {**curve(), "targets": [[0, 50.0], [40, 250.0]]}   # weight and flow, but no date
    assert "Remove the weight curve" in page


def test_share_image_curve_comes_from_the_current_version(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())
    post(app, "/recipes", variation(app, 1, grind_size="12"))
    card, page = share_card(app, curve=1)
    assert "curve" not in card and "weight curve" not in page  # the old grind's curve isn't this recipe


def test_markdown_export_never_has_curves(app):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())
    text = app.client.get("/lines/1/export.md").text
    assert '"t"' not in text and "curve" not in text.lower()


@pytest.mark.parametrize("delete", [
    lambda app: post(app, "/lines/1/delete", {}),
    lambda app: post(app, "/bags/1/delete", {}),
    lambda app: post(app, "/beans/1/delete", {}),
    lambda app: post(app, "/brewers/1/delete", {}),
    lambda app: post(app, "/grinders/1/delete", {}),
])
def test_deleting_takes_the_curves_with_it(app, delete):
    post(app, "/recipes", BASELINE)
    log(app, samples=curve())
    assert stored(app)
    delete(app)
    assert stored(app) == {}


def test_deleting_a_user_takes_their_curves(app):
    set_admin_password(app)
    uid = add_user(app)
    app.sign_in(uid)
    post(app, "/beans", {"name": "Mine"})
    post(app, "/bags", {"bean_id": 2, "initial_quantity_g": 100})
    post(app, "/brewers", {"name": "Mine"})
    post(app, "/grinders", {"name": "Mine"})
    post(app, "/recipes", {**BASELINE, "bean_id": 2, "brewer_id": 2, "grinder_id": 3})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 2, "curve": json.dumps(curve())})
    assert stored(app)
    app.sign_in(1)
    post(app, f"/users/{uid}/delete", {"admin_password": PASSWORD})
    assert stored(app) == {}


def test_round_trip_keeps_curves(app_on, tmp_path: Path):
    a = app_on()
    _seed_one_brew(a)
    with a.session() as s:
        crud.save_curve(s, 1, crud.parse_curve(json.dumps(curve())))
    assert json.loads(_round_trip(a, tmp_path)["brewcurve"][0]["samples"]) == curve()
