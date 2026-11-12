"""
Brew mode's switches on Manage (per user): the brewer animation, and the graph drawn
while brewing. Also what brew mode is handed for the graph after Stop: this recipe's
last saved curve, to lay under the new one. The drawing itself is checked by hand.
"""
import csv
import html as html_lib
import json
import re
from pathlib import Path

from test_accounts import add_user, set_admin_password
from test_export_import import _engine, export_script, import_script
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture
from app import models

METHOD = "0:00 — Bloom (to 50g)\n0:40 — Pour (to 250g)\n3:00 — Done"


def brew_page(app):
    return app.client.get("/lines/1/brew", params={"bag_id": 1}).text


def settings(app, **on):
    post(app, "/settings/brew-mode", {k: "1" for k, v in on.items() if v})


def test_by_default_the_animation_is_on_and_the_live_graph_off(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    page = brew_page(app)
    assert "data-animation=" in page and 'data-live-graph="0"' in page
    manage = app.client.get("/manage").text
    assert re.search(r'name="show_brew_animation" value="1"[^>]* checked', manage)
    assert not re.search(r'name="show_live_graph" value="1"[^>]* checked', manage)


def test_switching_them(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    settings(app, show_live_graph=True)  # the animation's box left unticked
    page = brew_page(app)
    assert "data-animation=" not in page and 'data-live-graph="1"' in page
    assert re.search(r'name="show_live_graph" value="1"[^>]* checked', app.client.get("/manage").text)
    settings(app, show_brew_animation=True)
    page = brew_page(app)
    assert "data-animation=" in page and 'data-live-graph="0"' in page


def test_the_form_goes_back_to_manage(app):
    r = app.client.post("/settings/brew-mode", data={}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/manage#brew-mode"


def test_each_person_has_their_own(app):
    set_admin_password(app)
    friend = add_user(app)
    settings(app)  # user 1: both off
    with app.session() as s:
        assert not s.get(models.User, 1).show_brew_animation
        assert s.get(models.User, friend).show_brew_animation and not s.get(models.User, friend).show_live_graph


def test_existing_people_get_the_defaults(app):
    # the migration's column defaults: what everyone on prod gets on deploy
    assert app.scalar("select show_brew_animation from user where id = 1") == 1
    assert app.scalar("select show_live_graph from user where id = 1") == 0


def test_an_older_snapshot_without_them_imports_with_the_defaults(app, tmp_path: Path):
    settings(app, show_live_graph=True)
    snapshot = tmp_path / "snapshot"
    export_script.export_all(app.engine, snapshot)
    users = snapshot / "users.csv"
    rows = list(csv.DictReader(users.open()))
    assert rows[0]["show_brew_animation"] in ("False", "0") and rows[0]["show_live_graph"] in ("True", "1")
    with users.open("w", newline="") as f:  # as a snapshot from before these columns
        w = csv.DictWriter(f, fieldnames=["id", "name", "password_hash", "is_admin", "must_change_password"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})
    restored = _engine(tmp_path / "restored.db")
    import_script.import_all(restored, snapshot)
    with restored.connect() as conn:
        assert conn.exec_driver_sql("select show_brew_animation, show_live_graph from user").all() == [(1, 0)]


def compare_data(page):
    found = re.search(r'data-compare="([^"]*)"', page)
    return json.loads(html_lib.unescape(found.group(1))) if found else None


def test_the_graph_after_stop_is_laid_over_the_last_saved_brew(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    assert compare_data(brew_page(app)) is None
    assert "This brew, and the last one in grey" not in brew_page(app)
    curve = {"t": [0, 0.5, 1], "g": [0, 10, 20], "f": [0, 20, 20]}
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "curve": json.dumps(curve)})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})  # newer, but no curve
    data = compare_data(brew_page(app))
    assert {k: data[k] for k in "tgf"} == curve
    assert data["label"].startswith("Last brew, ")
    assert "This brew, and the last one in grey" in brew_page(app)
