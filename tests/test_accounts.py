"""
Accounts: passwords, sessions, admin tools, and above all that one person can
never see or change another person's coffee.
"""
import importlib.util
import re
import sqlite3

import pytest

from app import auth, crud, main, models
from conftest import ROOT
from test_flows import BASELINE, COMBO, app, post  # noqa: F401 — app is a fixture

PASSWORD = "correct horse battery"
JPEG = b"\xff\xd8\xff\xe0" + b"bag" * 50


def add_user(app, name="Friend", password=PASSWORD, must_change=False) -> int:
    with app.session() as s:
        user = crud.create_user(s, name=name, password=password)
        user.must_change_password = must_change
        s.commit()
        return user.id


def set_admin_password(app, password=PASSWORD):
    with app.session() as s:
        crud.set_user_password(s, s.get(models.User, 1), password, must_change=False)


def login(app, user_id, password=PASSWORD):
    return app.client.post("/login", data={"user_id": user_id, "password": password}, follow_redirects=False)


def snapshot(app) -> str:
    """Everything people care about, excluding who is signed in."""
    conn = sqlite3.connect(app.path)
    try:
        return "\n".join(line for line in conn.iterdump() if '"usersession"' not in line)
    finally:
        conn.close()


# --- passwords -----------------------------------------------------------------

def test_password_hash_round_trip():
    stored = auth.hash_password(PASSWORD)
    assert PASSWORD not in stored and stored.startswith("scrypt$")
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("wrong", stored)
    assert auth.hash_password(PASSWORD) != stored  # salted


@pytest.mark.parametrize("stored", ["", "nonsense", "bcrypt$1$2$3$aa$bb", "scrypt$x$8$1$zz$zz"])
def test_malformed_stored_password_never_matches(stored):
    assert not auth.verify_password(PASSWORD, stored)


# --- signing in ------------------------------------------------------------------

def test_sign_in_sets_a_protected_cookie_and_stores_only_a_hash(app):
    app.client.cookies.clear()
    uid = add_user(app)
    r = login(app, uid)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    token = re.search(r'session=([^;]+)', cookie).group(1)
    stored = [row["token_hash"] for row in app.rows("select token_hash from usersession where user_id = :u", u=uid)]
    assert stored == [auth.session_token_hash(token)] and token not in stored
    assert app.client.get("/", follow_redirects=False).status_code == 200


def test_cookie_is_secure_over_https(app):
    uid = add_user(app)
    r = app.client.post("https://testserver/login", data={"user_id": uid, "password": PASSWORD}, follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


@pytest.mark.parametrize("password", ["wrong", ""])
def test_wrong_password_is_refused(app, password):
    app.client.cookies.clear()
    uid = add_user(app)
    r = login(app, uid, password)
    assert r.status_code in (401, 422) and "set-cookie" not in r.headers
    assert app.scalar("select count(*) from usersession where user_id = :u", u=uid) == 0


def test_account_with_no_password_cannot_sign_in(app):
    app.client.cookies.clear()
    assert login(app, 1, "").status_code in (401, 422)
    assert login(app, 1, "anything").status_code == 401


def test_cannot_become_someone_by_setting_the_old_cookie(app):
    app.client.cookies.clear()
    app.client.cookies.set("user_id", "1")
    r = app.client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"


def test_sign_out_ends_the_session(app):
    post(app, "/logout", {})
    assert app.scalar("select count(*) from usersession") == 0
    assert app.client.get("/", follow_redirects=False).headers["location"] == "/select-user"


def test_sign_in_page_lists_people_but_no_secrets(app):
    app.client.cookies.clear()
    html = app.client.get("/select-user").text
    assert 'type="password"' in html and "Anirudh" in html and "scrypt" not in html


# --- changing a password ---------------------------------------------------------

def test_temporary_password_forces_a_change_first(app):
    app.client.cookies.clear()
    uid = add_user(app, must_change=True)
    assert login(app, uid).headers["location"] == "/account"
    for page in ("/", "/browse", "/manage"):
        assert app.client.get(page, follow_redirects=False).headers["location"] == "/account"
    assert "choose your own password" in app.client.get("/account").text
    post(app, "/account/password", {"new_password": "brand new password", "confirm_password": "brand new password"})
    assert app.client.get("/", follow_redirects=False).status_code == 200
    with app.session() as s:
        user = s.get(models.User, uid)
        assert auth.verify_password("brand new password", user.password_hash) and not user.must_change_password


@pytest.mark.parametrize("fields, message", [
    ({"current_password": "wrong", "new_password": "long enough pw", "confirm_password": "long enough pw"}, "current password"),
    ({"current_password": PASSWORD, "new_password": "short", "confirm_password": "short"}, "at least"),
    ({"current_password": PASSWORD, "new_password": "long enough pw", "confirm_password": "different pw!!"}, "didn"),
])
def test_bad_password_changes_are_refused(app, fields, message):
    app.client.cookies.clear()
    uid = add_user(app)
    login(app, uid)
    r = app.client.post("/account/password", data=fields, follow_redirects=False)
    assert r.status_code == 400 and message in r.text
    with app.session() as s:
        assert auth.verify_password(PASSWORD, s.get(models.User, uid).password_hash)


def test_changing_password_signs_out_other_browsers(app):
    app.client.cookies.clear()
    uid = add_user(app)
    login(app, uid)
    with app.session() as s:
        crud.create_user_session(s, uid)  # another phone
    assert app.scalar("select count(*) from usersession where user_id = :u", u=uid) == 2
    post(app, "/account/password", {"current_password": PASSWORD, "new_password": "long enough pw", "confirm_password": "long enough pw"})
    assert app.scalar("select count(*) from usersession where user_id = :u", u=uid) == 1
    assert app.client.get("/", follow_redirects=False).status_code == 200


# --- admin -----------------------------------------------------------------------

def temporary_password_in(html: str) -> str:
    return re.search(r'temporary-password">([^<]+)<', html).group(1)


def test_first_user_is_the_admin(app):
    assert app.rows("select id from user where is_admin = 1") == [{"id": 1}]


def test_admin_creates_account_with_a_temporary_password(app):
    r = app.client.post("/users", data={"name": "Priya"}, follow_redirects=False)
    assert r.status_code == 200
    temp = temporary_password_in(r.text)
    uid = app.scalar("select id from user where name = 'Priya'")
    assert app.scalar("select must_change_password from user where id = :u", u=uid) == 1
    app.client.cookies.clear()
    assert login(app, uid, temp).headers["location"] == "/account"


def test_new_account_starts_empty_and_sees_nothing_of_anyone_elses(app):
    uid = add_user(app, "Priya")
    app.sign_in(uid)
    for page in ("/browse", "/manage", "/"):
        assert "Blue Tokai Baarbara Estate" not in app.client.get(page).text, page


@pytest.mark.parametrize("name", ["", "   ", "anirudh", " ANIRUDH "])
def test_account_names_must_be_present_and_unique(app, name):
    post(app, "/users", {"name": name}, status=400)
    assert app.scalar("select count(*) from user") == 1


def test_reset_replaces_password_and_signs_them_out(app):
    uid = add_user(app)
    with app.session() as s:
        crud.create_user_session(s, uid)
    r = app.client.post(f"/users/{uid}/reset-password", follow_redirects=False)
    temp = temporary_password_in(r.text)
    assert app.scalar("select count(*) from usersession where user_id = :u", u=uid) == 0
    app.client.cookies.clear()
    assert login(app, uid).status_code == 401
    assert login(app, uid, temp).headers["location"] == "/account"


def test_delete_needs_the_admins_own_password(app):
    set_admin_password(app)
    uid = add_user(app)
    before = snapshot(app)
    post(app, f"/users/{uid}/delete", {}, status=403)
    post(app, f"/users/{uid}/delete", {"admin_password": "wrong"}, status=403)
    assert snapshot(app) == before
    post(app, f"/users/{uid}/delete", {"admin_password": PASSWORD})
    assert app.scalar("select count(*) from user where id = :u", u=uid) == 0


def test_admin_cannot_delete_or_reset_themselves(app):
    set_admin_password(app)
    post(app, "/users/1/delete", {"admin_password": PASSWORD}, status=400)
    post(app, "/users/1/reset-password", {}, status=400)
    assert app.scalar("select count(*) from user") == 1


def test_deleting_someone_removes_their_data_and_sessions_only(app):
    set_admin_password(app)
    post(app, "/recipes", BASELINE)
    before_admin = app.rows("select id from bean")
    uid = add_user(app)
    app.sign_in(uid)
    post(app, "/beans", {"name": "Friend bean"})
    post(app, "/brewers", {"name": "Friend brewer"})
    app.sign_in(1)
    post(app, f"/users/{uid}/delete", {"admin_password": PASSWORD})
    assert app.rows("select id from bean") == before_admin
    assert app.scalar("select count(*) from brewer where user_id = :u", u=uid) == 0
    assert app.scalar("select count(*) from usersession where user_id = :u", u=uid) == 0


@pytest.mark.parametrize("url, data", [
    ("/users", {"name": "Sneaky"}),
    ("/users/1/reset-password", {}),
    ("/users/1/delete", {"admin_password": PASSWORD}),
])
def test_only_the_admin_can_manage_accounts(app, url, data):
    set_admin_password(app)
    app.sign_in(add_user(app))
    before = snapshot(app)
    post(app, url, data, status=403)
    assert snapshot(app) == before


def test_accounts_section_is_admin_only(app):
    uid = add_user(app)
    html = app.client.get("/manage").text
    assert "Reset password" in html and f"/users/{uid}/delete" in html
    app.sign_in(uid)
    html = app.client.get("/manage").text
    assert "Reset password" not in html and "/users/" not in html


# --- one person can't touch another's coffee ---------------------------------------

@pytest.fixture
def owned(app):
    """User 1's coffee, with a signed-in second user looking at it."""
    post(app, "/recipes", BASELINE)                          # recipe 1, line 1
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1,
                         "curve": '{"t": [0, 1], "g": [0, 10], "f": [0, 10]}'})  # brew 1, with a graph
    post(app, "/plan", COMBO)
    app.client.post("/beans/1/image", files={"image": ("b.jpg", JPEG, "image/jpeg")}, data={"accent": "#123456"})
    uid = add_user(app)
    app.sign_in(uid)
    post(app, "/beans", {"name": "Mine"})                    # bean 2
    post(app, "/bags", {"bean_id": 2, "initial_quantity_g": 100})  # bag 2
    post(app, "/brewers", {"name": "My brewer"})             # brewer 2
    post(app, "/grinders", {"name": "My grinder"})           # grinder 3
    return app


GET_ATTACKS = [
    ("/recipes/latest", {"bag_id": 1, "brewer_id": 2, "grinder_id": 3}),
    ("/recipes/latest", {"bag_id": 2, "brewer_id": 1, "grinder_id": 3}),
    ("/recipes/latest", {"bag_id": 2, "brewer_id": 2, "grinder_id": 1}),
    ("/lines/1/brew", {}),
    ("/lines/1/export.md", {}),
    ("/lines/1/share-image", {}),
    ("/lines/1/tidy", {}),
    ("/beans/1/image", {}),
    ("/brews/1/graph", {}),
    ("/brews/1/curve.csv", {}),
    ("/brews/1/edit", {}),
    ("/lines/1/change", {}),
    ("/", {"bag_id": 1}),
    ("/lines/1/versions", {}),
    ("/four-six", {"bag_id": 1, "brewer_id": 2, "grinder_id": 3}),
]

RECIPE = {"dose_g": 15, "water_ml": 250, "temp_c": 93, "grind_size": "13"}
POST_ATTACKS = [
    ("/beans/1/edit", {"name": "Hacked"}),
    ("/beans/1/delete", {}),
    ("/beans/1/image/delete", {}),
    ("/beans/1/colors", {"accent": "#000000"}),
    ("/bags", {"bean_id": 1, "initial_quantity_g": 1}),
    ("/bags/1/edit", {"initial_quantity_g": 1}),
    ("/bags/1/complete", {}),
    ("/bags/1/delete", {}),
    ("/brewers/1/edit", {"name": "Hacked"}),
    ("/brewers/1/delete", {}),
    ("/grinders/1/edit", {"name": "Hacked"}),
    ("/grinders/1/delete", {}),
    ("/lines/1/rename", {"name": "Hacked"}),
    ("/lines/1/delete", {}),
    ("/lines/1/tidy", {"recipe_text": "0:00 — Pour"}),
    ("/plan/1/cancel", {}),
    ("/plan", {"bag_id": 1, "brewer_id": 2, "grinder_id": 3}),
    ("/plan", {"bag_id": 2, "brewer_id": 1, "grinder_id": 3}),
    ("/plan", {"bag_id": 2, "brewer_id": 2, "grinder_id": 1}),
    ("/brews", {"recipe_id": 1, "bag_id": 2}),
    ("/brews", {"recipe_id": 1, "bag_id": 1}),
    ("/brews/1/edit", {"notes": "Hacked"}),
    ("/brews/1/delete", {}),
    ("/lines/1/copy", {"bean_id": 2, "brewer_id": 2, "grinder_id": 3}),
    ("/lines/1/copy", {"bean_id": 1, "brewer_id": 1, "grinder_id": 1}),
    ("/lines/1/undo", {}),
    ("/four-six", {"bag_id": 1, "brewer_id": 2, "grinder_id": 3, "coffee": "15", "ratio": "16", "grind_size": "1"}),
    ("/brewers/1/archive", {}),
    ("/grinders/1/archive", {}),
    ("/recipes/1/fix", {"dose_g": "1", "water_ml": "1", "temp_c": "90", "grind_size": "1"}),
    ("/recipes/1/reason", {"rationale": "x"}),
    ("/recipes/1/delete", {}),
    ("/recipes", {**RECIPE, "bean_id": 1, "brewer_id": 2, "grinder_id": 3}),
    ("/recipes", {**RECIPE, "bean_id": 2, "brewer_id": 1, "grinder_id": 3}),
    ("/recipes", {**RECIPE, "bean_id": 2, "brewer_id": 2, "grinder_id": 1}),
    ("/recipes", {**RECIPE, "bean_id": 2, "brewer_id": 2, "grinder_id": 3, "previous_recipe_id": 1, "dose_g": 16}),
    ("/recipes", {**RECIPE, "bean_id": 2, "brewer_id": 2, "grinder_id": 3, "bag_id": 1, "line_name": "x"}),
]


@pytest.mark.parametrize("url, params", GET_ATTACKS)
def test_cannot_read_someone_elses_things(owned, url, params):
    assert owned.client.get(url, params=params, follow_redirects=False).status_code == 404


@pytest.mark.parametrize("url, data", POST_ATTACKS)
def test_cannot_change_someone_elses_things(owned, url, data):
    before = snapshot(owned)
    assert owned.client.post(url, data=data, follow_redirects=False).status_code == 404
    assert snapshot(owned) == before


def test_cannot_upload_a_photo_to_someone_elses_bean(owned):
    before = snapshot(owned)
    r = owned.client.post("/beans/1/image", files={"image": ("b.jpg", JPEG + b"x", "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 404 and snapshot(owned) == before


def test_cannot_consume_someone_elses_plan_when_logging(owned):
    post(owned, "/recipes", {**RECIPE, "bean_id": 2, "brewer_id": 2, "grinder_id": 3})
    recipe = owned.scalar("select max(id) from recipe")
    before = owned.scalar("select count(*) from plannedbrew")
    post(owned, "/brews", {"recipe_id": recipe, "bag_id": 2, "planned_brew_id": 1}, status=404)
    assert owned.scalar("select count(*) from plannedbrew") == before


def test_owners_keep_working_normally(owned):
    owned.sign_in(1)
    assert owned.client.get("/lines/1/brew", params={"bag_id": 1}).status_code == 200
    assert owned.client.get("/beans/1/image").content == JPEG
    post(owned, "/beans/1/edit", {"name": "Renamed"})
    assert owned.scalar("select name from bean where id = 1") == "Renamed"


PUBLIC_ROUTES = {"/select-user", "/login", "/logout"}


def test_every_route_turns_away_anyone_not_signed_in(app):
    """A safety net for routes added later: nothing but sign-in works without a session."""
    app.client.cookies.clear()
    checked = 0
    for route in main.app.routes:
        methods = getattr(route, "methods", None) or set()
        if route.path in PUBLIC_ROUTES or route.path.startswith("/static"):
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in methods & {"GET", "POST"}:
            r = app.client.request(method, path, follow_redirects=False)
            assert r.status_code in (302, 422), (method, route.path, r.status_code)  # 422: the form is missing, so nothing ran
            checked += 1
    assert checked > 25


# --- the Caddy password script ------------------------------------------------------

spec = importlib.util.spec_from_file_location("set_gate_login", ROOT / "scripts" / "remote" / "set_gate_login.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

CADDYFILE = """:80 {
	root * /usr/share/caddy
	file_server
}
coffee.rowjee.com {
    basicauth {
        anirudh $2a$14$oldhashone
	anu $2a$14$oldhashtwo
    }
    reverse_proxy localhost:8000
}
"""


def test_gate_rewrite_replaces_only_that_sites_logins():
    out = gate.with_single_login(CADDYFILE, "coffee", "$2a$14$newhash")
    assert "oldhash" not in out and "coffee $2a$14$newhash" in out
    assert out.count("basicauth") == 1 and "reverse_proxy localhost:8000" in out and "file_server" in out


def test_gate_rewrite_refuses_an_unexpected_caddyfile():
    with pytest.raises(ValueError):
        gate.with_single_login(":80 {\n  file_server\n}\n", "coffee", "$2a$14$newhash")
