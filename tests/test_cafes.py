"""
Cafés: coffee had out, logged with a photo and a rating, shared as an image, and (only
when its owner says so) put in the friends' feed that everyone signed in can read.

The one deliberate exception to "nobody sees anyone else's things": a café cup in the
feed is readable, never changeable, by other signed-in people. Everything else stays
locked to its owner (tests/test_accounts.py attacks every café route as someone else).
"""
import json
import re

from test_accounts import JPEG, add_user
from test_flows import app, post  # noqa: F401 — app is a fixture

CUP = {"cafe": "Subko", "area": "Bandra, Mumbai", "drink_kind": "pour_over", "drink": "V60", "rating": "4",
       "notes": "Juicy, bright", "roaster": "Subko", "coffee": "Kenya Kiambu", "process": "Washed",
       "price": "350", "again": "yes", "handle": "@Anirudh.Brews"}


def log(app, photo=None, **extra):
    data = {**CUP, **extra}
    files = {"photo": ("c.jpg", photo, "image/jpeg")} if photo else None
    r = app.client.post("/cafes", data=data, files=files, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def cup(app, cup_id=1):
    rows = app.rows(f"select * from cafecup where id = {cup_id}")
    return rows[0] if rows else None


def test_a_cafe_cup_is_logged_with_everything_and_the_handle_is_remembered(app):
    cup_id = log(app, photo=JPEG, accent="#aa5500")
    c = cup(app, cup_id)
    assert (c["cafe"], c["drink_kind"], c["rating"], c["price"], c["again"]) == ("Subko", "pour_over", 4, 350.0, 1)
    assert c["handle"] == "anirudh.brews" and c["shared"] == 0  # the feed is off unless switched on
    assert c["image_version"] and app.scalar("select count(*) from cafecupimage") == 1
    assert app.scalar("select cafe_handle from user where id = 1") == "anirudh.brews"
    page = app.client.get(f"/cafes/{cup_id}").text
    assert "Subko" in page and "★★★★☆" in page and "Kenya Kiambu" in page and "Share as image" in page
    assert app.client.get(f"/cafes/{cup_id}/photo").content == JPEG
    assert 'value="anirudh.brews"' in app.client.get("/cafes/new").text  # remembered for next time


def test_only_the_cafe_what_you_had_and_the_stars_are_needed(app):
    cup_id = log(app, area="", drink="", notes="", roaster="", coffee="", process="", price="", again="", handle="")
    assert cup(app, cup_id)["area"] is None and cup(app, cup_id)["again"] is None
    for missing in ({"cafe": " "}, {"drink_kind": "tea"}, {"rating": ""}, {"rating": "6"}):
        r = app.client.post("/cafes", data={**CUP, **missing}, headers={"accept": "text/html"})
        assert r.status_code == 400, missing
    assert app.client.post("/cafes", data={**CUP, "handle": "not a handle!"}).status_code == 400
    assert app.client.post("/cafes", data={**CUP, "price": "-5"}).status_code == 400
    r = app.client.post("/cafes", data=CUP, files={"photo": ("c.png", b"\x89PNG....", "image/png")})
    assert r.status_code == 400 and app.scalar("select count(*) from cafecup") == 1


def test_a_cup_can_be_corrected_its_photo_replaced_or_removed_and_deleted(app):
    cup_id = log(app, photo=JPEG)
    first = cup(app, cup_id)["image_version"]
    post(app, f"/cafes/{cup_id}/edit", {**CUP, "rating": "5", "notes": "Even better cold"})
    assert (cup(app, cup_id)["rating"], cup(app, cup_id)["image_version"]) == (5, first)  # no new photo: kept
    app.client.post(f"/cafes/{cup_id}/edit", data={**CUP}, files={"photo": ("c.jpg", JPEG + b"2", "image/jpeg")})
    assert cup(app, cup_id)["image_version"] > first
    post(app, f"/cafes/{cup_id}/edit", {**CUP, "remove_photo": "1"})
    assert cup(app, cup_id)["image_version"] is None and app.scalar("select count(*) from cafecupimage") == 0
    assert "Delete this café cup" in app.client.get(f"/cafes/{cup_id}/edit").text
    post(app, f"/cafes/{cup_id}/delete", {})
    assert app.scalar("select count(*) from cafecup") == 0


def test_the_feed_shows_only_cups_their_owner_shared(app):
    private = log(app, cafe="Secret Spot")
    shared = log(app, cafe="Dyu Art Café", shared="1")
    friend = add_user(app, name="Meera")
    app.sign_in(friend)
    feed = app.client.get("/cafes?view=friends").text
    assert "Dyu Art Café" in feed and "Secret Spot" not in feed and "@anirudh.brews" in feed
    # a friend can look at a shared cup and its photo, never a private one
    assert app.client.get(f"/cafes/{shared}").status_code == 200
    assert "Add these beans to my coffees" in app.client.get(f"/cafes/{shared}").text
    assert app.client.get(f"/cafes/{private}").status_code == 404
    # and their own list is theirs alone
    assert "Dyu Art Café" not in app.client.get("/cafes").text


def test_a_shared_cup_is_never_changeable_by_anyone_else(app):
    shared = log(app, shared="1")
    app.sign_in(add_user(app, name="Meera"))
    before = app.rows("select * from cafecup")
    for url, data in [(f"/cafes/{shared}/edit", {**CUP, "cafe": "Hacked"}), (f"/cafes/{shared}/feed", {"shared": "0"}),
                      (f"/cafes/{shared}/delete", {})]:
        assert app.client.post(url, data=data, follow_redirects=False).status_code == 404, url
    for url in (f"/cafes/{shared}/edit", f"/cafes/{shared}/share-image"):
        assert app.client.get(url).status_code == 404, url
    assert app.rows("select * from cafecup") == before


def test_taking_a_cup_out_of_the_feed_hides_it_at_once(app):
    shared = log(app, shared="1", photo=JPEG)
    friend = add_user(app, name="Meera")
    post(app, f"/cafes/{shared}/feed", {"shared": "0"})
    app.sign_in(friend)
    assert "Subko" not in app.client.get("/cafes?view=friends").text
    assert app.client.get(f"/cafes/{shared}").status_code == 404
    assert app.client.get(f"/cafes/{shared}/photo").status_code == 404


def test_bought_the_beans_fills_in_add_coffee(app):
    cup_id = log(app)
    page = app.client.get("/browse", params={"from_cafe": cup_id}).text
    assert "data-open-now" in page and 'value="Subko · Kenya Kiambu"' in page and 'value="Juicy, bright"' in page
    assert "First had at Subko" in page and "From your cup at Subko" in page
    # a friend's shared cup does the same for them, saying whose it was; nothing is linked afterwards
    shared = log(app, cafe="Dyu Art Café", roaster="Corridor Seven", coffee="Ethiopia Guji", shared="1")
    app.sign_in(add_user(app, name="Meera"))
    page = app.client.get("/browse", params={"from_cafe": shared}).text
    assert "Corridor Seven · Ethiopia Guji" in page and "@anirudh.brews" in page


def test_the_share_card_is_built_from_the_cup_and_kept_to_its_owner(app):
    cup_id = log(app, photo=JPEG)
    page = app.client.get(f"/cafes/{cup_id}/share-image").text
    card = json.loads(re.search(r'data-card="([^"]*)"', page).group(1).replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&"))
    assert card["cafe"] == "Subko" and card["rating"] == 4 and card["handle"] == "anirudh.brews"
    assert card["photo"].startswith(f"/cafes/{cup_id}/photo")
    assert "Price" in page and 'data-show="price" />' in page  # price is offered, but off until switched on


def test_cafes_is_the_fourth_tab_and_people_are_shown_how_to_start(app):
    page = app.client.get("/cafes").text
    assert 'href="/cafes" class="on"' in page and "Log a café cup" in page and "Had a good coffee out?" in page
    assert "Nothing in the feed yet" in app.client.get("/cafes?view=friends").text
    assert 'href="/cafes"' in app.client.get("/").text


def test_deleting_an_account_deletes_its_cafe_cups(app):
    friend = add_user(app, name="Meera")
    app.sign_in(friend)
    log(app, photo=JPEG)
    app.sign_in(1)
    with app.session() as s:
        from app import crud
        crud.delete_user(s, friend)
    assert app.scalar("select count(*) from cafecup") == 0 and app.scalar("select count(*) from cafecupimage") == 0


def test_an_empty_handle_is_stored_as_none_so_a_backup_restores_it_exactly(app):
    cup_id = log(app, handle="")
    assert cup(app, cup_id)["handle"] is None
    with app.engine.begin() as conn:  # a cup saved before the fix
        conn.exec_driver_sql("UPDATE cafecup SET handle = '' WHERE id = ?", (cup_id,))
    from app import db
    db.run_migrations(app.engine)
    assert cup(app, cup_id)["handle"] is None
