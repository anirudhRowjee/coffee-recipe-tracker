"""
Bag photos and the per-bean colours derived from them. Decoding and colour
picking happen in the browser (static/bean_art.js), so the "JPEG" here is just
bytes with the right signature.
"""
import pytest

from app.theme import _rgb, bean_theme, clean_accent, contrast
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture

JPEG = b"\xff\xd8\xff\xe0" + b"fake-bag-photo" * 10
DARK_TEXT = (59, 31, 14)  # the app's text colour on highlights


def upload(app, bean_id=1, data=JPEG, accent="#d9541e", status=303):
    fields = {"accent": accent} if accent is not None else {}
    r = app.client.post(f"/beans/{bean_id}/image", files={"image": ("bag.jpg", data, "image/jpeg")},
                        data=fields, follow_redirects=False)
    assert r.status_code == status, r.text
    return r


def test_upload_then_serve_photo(app):
    upload(app)
    assert app.scalar("select accent_color from bean") == "#d9541e"
    assert app.scalar("select image_version from bean") > 0
    r = app.client.get("/beans/1/image")
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert "immutable" in r.headers["cache-control"]


def test_new_upload_replaces_photo_and_changes_url(app):
    upload(app)
    first_version = app.scalar("select image_version from bean")
    upload(app, data=JPEG + b"new", accent="#123456")
    assert app.client.get("/beans/1/image").content == JPEG + b"new"
    assert app.scalar("select count(*) from beanimage") == 1
    assert app.scalar("select accent_color from bean") == "#123456"
    assert app.scalar("select image_version from bean") > first_version


def test_rejects_non_jpeg_and_oversized(app):
    upload(app, data=b"<svg onload=alert(1)>", status=400)
    upload(app, data=b"\xff\xd8\xff" + b"x" * 3_000_001, status=400)
    assert app.scalar("select count(*) from beanimage") == 0


@pytest.mark.parametrize("bad", ["red", "#12345", "#12345g", "#123456;background:url(x)", '"><script>'])
def test_bad_accent_is_dropped_but_photo_kept(app, bad):
    upload(app, accent=bad)
    assert app.scalar("select accent_color from bean") is None
    assert app.scalar("select count(*) from beanimage") == 1


def test_upload_for_unknown_bean_is_404(app):
    upload(app, bean_id=999, status=404)
    assert app.scalar("select count(*) from beanimage") == 0


def test_remove_photo_clears_colour(app):
    upload(app)
    post(app, "/beans/1/image/delete", {})
    assert app.scalar("select count(*) from beanimage") == 0
    assert app.rows("select accent_color, image_version from bean") == [{"accent_color": None, "image_version": None}]
    assert app.client.get("/beans/1/image").status_code == 404


def test_photo_url_is_not_reused_after_remove_and_re_add(app, monkeypatch):
    monkeypatch.setattr("app.crud.time.time", lambda: 1000)
    upload(app)
    assert app.scalar("select image_version from bean") == 1000
    post(app, "/beans/1/image/delete", {})
    monkeypatch.setattr("app.crud.time.time", lambda: 2000)
    upload(app)
    assert app.scalar("select image_version from bean") == 2000


def test_deleting_bean_deletes_photo(app):
    upload(app)
    post(app, "/beans/1/delete", {})
    assert app.scalar("select count(*) from beanimage") == 0


def test_photo_requires_a_user(app):
    upload(app)
    app.client.cookies.clear()
    r = app.client.get("/beans/1/image", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/select-user"


def test_pages_show_photo_and_colours(app):
    post(app, "/recipes", BASELINE)
    upload(app)
    url = f'src="/beans/1/image?v={app.scalar("select image_version from bean")}"'
    styled = 'style="--accent:'
    panel = latest(app)
    assert url in panel and styled in panel
    brew = app.client.get("/lines/1/brew", params={"bag_id": 1}).text
    assert url in brew and styled in brew
    browse = app.client.get("/browse").text
    assert url in browse and styled in browse
    assert url in app.client.get("/").text  # bag picker
    assert url in app.client.get("/manage").text and "Change bag photo" in app.client.get("/manage").text


def test_without_photo_pages_keep_the_default_palette(app):
    post(app, "/recipes", BASELINE)
    for html in (latest(app), app.client.get("/browse").text, app.client.get("/lines/1/brew", params={"bag_id": 1}).text):
        assert "--accent:" not in html and "/beans/1/image" not in html
    assert "Add bag photo" in app.client.get("/manage").text


# --- colours -------------------------------------------------------------------

@pytest.mark.parametrize("accent", ["#ffff00", "#ffffff", "#00ff88", "#d9541e", "#101010", "#7fd4ff"])
def test_derived_colours_stay_readable(accent):
    style = dict(part.split(":") for part in bean_theme(accent).split(";"))
    assert contrast(_rgb(style["--accent"]), (255, 255, 255)) >= 4.5  # white text on buttons
    assert contrast(_rgb(style["--accent-soft"]), DARK_TEXT) >= 4.5  # dark text on highlights


def test_clean_accent():
    assert clean_accent(" #ABCDEF ") == "#abcdef"
    assert clean_accent(None) is None
    assert bean_theme(None) == "" and bean_theme("nope") == ""
