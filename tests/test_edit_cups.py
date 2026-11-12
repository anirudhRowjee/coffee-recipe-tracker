"""
Fixing a logged cup: notes (including how it tasted once cooled), rating, Next time
and bag can all be changed later; a deleted cup can be brought back with Undo.
"""
import re

from app import main
from test_accounts import add_user, set_admin_password
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture

CURVE = '{"t": [0, 1], "g": [0, 10], "f": [0, 10]}'


def logged(app, **extra):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "warm, a bit sour", "rating": "3", **extra})
    return app.scalar("select max(id) from brew")


def brew_row(app, brew_id=1):
    rows = app.rows(f"select notes, rating, recommended_param, recommended_delta, recommended_rationale, bag_id from brew where id = {brew_id}")
    return rows[0] if rows else None


def test_every_field_can_be_corrected(app):
    brew = logged(app, recommended_param="temp_c", recommended_delta="3")
    post(app, f"/brews/{brew}/edit", {"notes": "warm, a bit sour\nCooled: sweet", "rating": "4",
                                      "recommended_param": "grind_size", "recommended_delta": "−1", "recommended_rationale": "fine"})
    assert brew_row(app) == {"notes": "warm, a bit sour\nCooled: sweet", "rating": 4, "recommended_param": "grind_size",
                             "recommended_delta": -1.0, "recommended_rationale": "fine", "bag_id": 1}
    # the Next time banner follows the edit
    assert "Grind −1" in latest(app)


def test_same_again_clears_next_time(app):
    brew = logged(app, recommended_param="temp_c", recommended_delta="3", recommended_rationale="sweeter")
    post(app, f"/brews/{brew}/edit", {"notes": "fine", "rating": "", "recommended_param": "", "recommended_delta": "3",
                                      "recommended_rationale": "sweeter"})
    assert brew_row(app)["recommended_param"] is None and brew_row(app)["recommended_rationale"] is None
    assert brew_row(app)["rating"] is None
    assert 'data-rec="brew"' not in latest(app)


def test_the_edit_page_and_cooled_note(app):
    brew = logged(app)
    page = app.client.get(f"/brews/{brew}/edit").text
    assert "warm, a bit sour</textarea>" in page and 'value="3" checked' in page
    cooled = app.client.get(f"/brews/{brew}/edit?cooled=1").text
    assert "warm, a bit sour\nCooled: </textarea>" in cooled


def test_a_fresh_cup_offers_the_cooled_note(app):
    brew = logged(app)
    assert f"/brews/{brew}/edit?cooled=1" in latest(app)
    app.execute("update brew set brewed_at = datetime('now', '-2 hours')")
    assert "edit?cooled=1" not in latest(app)


def test_moving_a_cup_to_another_bag_moves_its_coffee(app):
    brew = logged(app)
    post(app, "/bags", {"bean_id": 1, "initial_quantity_g": 250})
    new_bag = app.scalar("select max(id) from beanbag")
    post(app, f"/brews/{brew}/edit", {"notes": "x", "bag_id": new_bag})
    assert brew_row(app)["bag_id"] == new_bag


def test_a_bag_of_another_coffee_is_refused(app):
    brew = logged(app)
    post(app, "/beans", {"name": "Other"})
    other_bean = app.scalar("select max(id) from bean")
    post(app, "/bags", {"bean_id": other_bean, "initial_quantity_g": 250})
    other_bag = app.scalar("select max(id) from beanbag")
    post(app, f"/brews/{brew}/edit", {"notes": "x", "bag_id": other_bag}, status=400)
    assert brew_row(app)["bag_id"] == 1


def test_bad_values_are_refused(app):
    brew = logged(app)
    post(app, f"/brews/{brew}/edit", {"recommended_param": "bag_id"}, status=400)
    post(app, f"/brews/{brew}/edit", {"recommended_param": "temp_c", "recommended_delta": "lots"}, status=400)
    assert brew_row(app)["notes"] == "warm, a bit sour"


def test_delete_then_undo_brings_it_back_with_its_graph(app):
    brew = logged(app, curve=CURVE, recommended_param="temp_c", recommended_delta="2")
    brewed_at = app.scalar(f"select brewed_at from brew where id = {brew}")
    r = app.client.post(f"/brews/{brew}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?undo=")
    assert app.scalar("select count(*) from brew") == 0 and app.scalar("select count(*) from brewcurve") == 0
    token = r.headers["location"].split("=", 1)[1]
    home = app.client.get(r.headers["location"]).text
    assert 'action="/brews/undo"' in home and token in home
    post(app, "/brews/undo", {"token": token})
    assert app.scalar("select count(*) from brew") == 1 and app.scalar("select count(*) from brewcurve") == 1
    restored = app.rows("select notes, rating, recommended_param, brewed_at from brew")[0]
    assert restored == {"notes": "warm, a bit sour", "rating": 3, "recommended_param": "temp_c", "brewed_at": brewed_at}
    post(app, "/brews/undo", {"token": token}, status=400)  # only once


def test_undo_runs_out(app, monkeypatch):
    brew = logged(app)
    r = app.client.post(f"/brews/{brew}/delete", follow_redirects=False)
    token = r.headers["location"].split("=", 1)[1]
    monkeypatch.setattr(main.time, "time", lambda: 10 ** 12)
    post(app, "/brews/undo", {"token": token}, status=400)


def test_nobody_else_can_undo_or_edit(app):
    set_admin_password(app)
    brew = logged(app)
    r = app.client.post(f"/brews/{brew}/delete", follow_redirects=False)
    token = r.headers["location"].split("=", 1)[1]
    friend = add_user(app)
    app.sign_in(friend)
    post(app, "/brews/undo", {"token": token}, status=400)
    app.sign_in(1)
    post(app, "/brews/undo", {"token": token})
    app.sign_in(friend)
    assert app.client.get("/brews/1/edit").status_code == 404
    assert app.client.post("/brews/1/edit", data={"notes": "x"}).status_code == 404
    assert app.client.post("/brews/1/delete").status_code == 404
    assert re.search("warm, a bit sour", app.client.get("/").text) is None
