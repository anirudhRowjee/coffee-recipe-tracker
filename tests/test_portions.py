"""
Frozen portions: a bag split into vacuum-sealed portions, each a bag of its own with a
short code, labels as a PDF made in the browser, and the code page at /b, the one page
outside the site password, which shows only coffee, dates and the best recipe, and is
for people (bots turned away, a human's number of lookups per address).
"""
import json
import re
import shutil
import subprocess

import pytest

from app import crud, main
from conftest import ROOT
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

BROWSER = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"}
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node isn't installed")


@pytest.fixture(autouse=True)
def fresh_limits():
    main._HITS.clear()
    yield
    main._HITS.clear()


def freeze(app, bag=1, grams="60", count="3"):
    r = app.client.post(f"/bags/{bag}/freeze", data={"grams": grams, "count": count}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"].split("new=", 1)[1].split(",")


def remaining(app, bag_id):
    with app.session() as s:
        from app import models
        return crud.get_remaining_quantity(s, s.get(models.BeanBag, bag_id))


def anonymous(app):
    app.client.cookies.clear()
    return app


def test_freezing_splits_portions_off_the_bag_each_with_its_own_code(app):
    codes = freeze(app)
    assert len(codes) == 3 and len(set(codes)) == 3
    assert all(re.fullmatch(f"[{crud.PORTION_ALPHABET}]{{5}}", c) for c in codes)
    rows = app.rows("select code, initial_quantity_g, is_frozen, frozen_date, parent_bag_id from beanbag where code is not null order by id")
    assert [r["code"] for r in rows] == codes
    assert all(r["initial_quantity_g"] == 60 and r["is_frozen"] == 1 and r["frozen_date"] and r["parent_bag_id"] == 1 for r in rows)
    assert remaining(app, 1) == 250 - 180  # worked out from what was frozen out of it, never stored
    page = app.client.get("/browse?bean=1").text
    assert "In the freezer" in page and all(c in page for c in codes)


def test_you_cant_freeze_more_than_is_left_or_split_a_portion(app):
    for data in ({"grams": "60", "count": "5"}, {"grams": "2", "count": "1"}, {"grams": "60", "count": "0"}):
        assert app.client.post("/bags/1/freeze", data=data, headers={"accept": "text/html"}).status_code in (400, 422), data
    freeze(app, count="1")
    portion = app.scalar("select max(id) from beanbag")
    assert app.client.post(f"/bags/{portion}/freeze", data={"grams": "10", "count": "1"}).status_code == 400
    assert app.scalar("select count(*) from beanbag") == 2


def test_the_labels_page_has_each_code_and_a_pdf_with_nothing_private(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": "0:00 — Bloom (to 50g)\n0:45 — Pour (to 250g)"})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "SECRET-NOTE", "rating": "5"})
    codes = freeze(app, count="2")
    page = app.client.get(f"/beans/1/labels?new={','.join(codes)}").text
    assert "2 portions frozen" in page and all(c in page for c in codes)
    raw = re.search(r'data-labels="([^"]*)"', page).group(1)
    labels = json.loads(raw.replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&").replace("&#39;", "'"))
    assert [l["code"] for l in labels] == codes
    assert labels[0]["url"].endswith(f"/b/{codes[0]}") and labels[0]["cups"] == 4
    assert labels[0]["recipe_short"].startswith("15 g · 250 ml · 93 °C")
    assert "SECRET-NOTE" not in page and "recipe" not in labels[0]  # the method stays on the code page


def test_take_it_out_and_gave_it_away(app):
    codes = freeze(app, count="2")
    first, second = app.rows("select id from beanbag where code is not null order by id")
    post(app, f"/bags/{first['id']}/take-out", {})
    post(app, f"/bags/{second['id']}/give-away", {})
    a, b = app.rows("select is_frozen, thaw_date, is_completed, given_date from beanbag where code is not null order by id")
    assert a["is_frozen"] == 0 and a["thaw_date"] and not a["is_completed"]
    assert b["is_completed"] == 1 and b["given_date"]
    assert remaining(app, 1) == 130  # giving one away doesn't put its grams back in the bag
    page = app.client.get("/browse?bean=1").text
    assert "In the freezer" not in page  # neither is frozen any more
    # a portion out of the freezer is brewed from like any bag, and the code page still works
    assert anonymous(app).client.get(f"/b/{codes[1]}", headers=BROWSER).status_code == 200


def test_the_code_page_shows_the_coffee_and_best_recipe_and_nothing_private(app):
    post(app, "/beans/1/edit", {"name": "Blue Tokai Baarbara Estate", "origin": "India", "roast_level": "Medium",
                                "notes": "SECRET-BEAN-NOTE"})
    post(app, "/recipes", {**BASELINE, "recipe_text": "0:00 — Bloom (to 50g)\n0:45 — Pour (to 250g)"})
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1, "notes": "SECRET-TASTING", "rating": "4",
                         "recommended_param": "temp_c", "recommended_delta": "2", "recommended_rationale": "SECRET-REC"})
    code = freeze(app, count="1")[0]
    anonymous(app)
    r = app.client.get(f"/b/{code}", headers=BROWSER)
    page = r.text
    assert r.status_code == 200 and "Blue Tokai Baarbara Estate" in page and "India · Medium roast" in page
    assert "60 g, about 4 cups" in page and "Frozen" in page and "Bloom (to 50g)" not in page  # steps are split up
    assert "<b>0:45</b><span>Pour · to 250 g</span>" in page and "Timemore C2" in page
    for secret in ("SECRET-BEAN-NOTE", "SECRET-TASTING", "SECRET-REC", "Anirudh", "★"):
        assert secret not in page, secret
    assert "Take it out" not in page  # only for its owner
    assert r.headers["x-robots-tag"].startswith("noindex")
    # self-contained: nothing else from the site, which still asks for its password
    assert "/static/" not in page and 'rel="icon" href="data:,"' in page and "<script" not in page


def test_its_owner_gets_take_it_out_there_and_nobody_else_does(app):
    code = freeze(app, count="1")[0]
    assert "Take it out" in app.client.get(f"/b/{code}").text
    app.sign_in(add_user(app, name="Meera"))
    page = app.client.get(f"/b/{code}").text
    assert "Take it out" not in page and "Gave it away" not in page
    bag = app.scalar("select max(id) from beanbag")
    assert app.client.post(f"/bags/{bag}/take-out", follow_redirects=False).status_code == 404


def test_typing_a_code_finds_it_however_its_written(app):
    code = freeze(app, count="1")[0]
    anonymous(app)
    typed = f" {code[:3].lower()}-{code[3:].lower()} "
    r = app.client.get("/b", params={"code": typed}, headers=BROWSER, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/b/{code}"
    assert "Type the code on its label" in app.client.get("/b", headers=BROWSER).text
    r = app.client.get("/b/ZZZZZ", headers=BROWSER)
    assert r.status_code == 404 and "No bag has the code" in r.text


def test_bots_and_scripts_are_turned_away(app):
    code = freeze(app, count="1")[0]
    anonymous(app)
    for ua in ("", "curl/8.4.0", "python-requests/2.32", "Mozilla/5.0 (compatible; Googlebot/2.1)",
               "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2)", "ClaudeBot/1.0",
               "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/120.0"):
        r = app.client.get(f"/b/{code}", headers={"user-agent": ua})
        assert r.status_code == 403 and "Blue Tokai" not in r.text, ua


def test_a_human_number_of_lookups_per_address(app):
    code = freeze(app, count="1")[0]
    anonymous(app)
    events = main._LIMITS["look"][0]
    for _ in range(events):
        assert app.client.get(f"/b/{code}", headers=BROWSER).status_code == 200
    r = app.client.get(f"/b/{code}", headers=BROWSER)
    assert r.status_code == 429 and "Blue Tokai" not in r.text
    # another address is counted apart (Caddy passes the real one on)
    other = {**BROWSER, "x-forwarded-for": "203.0.113.9"}
    assert app.client.get(f"/b/{code}", headers=other).status_code == 200


def test_guessing_codes_runs_out_quickly(app):
    anonymous(app)
    misses = main._LIMITS["miss"][0]
    for i in range(misses):
        assert app.client.get(f"/b/ZZZZ{crud.PORTION_ALPHABET[i]}", headers=BROWSER).status_code == 404
    assert app.client.get("/b/ZZZZZ", headers=BROWSER).status_code == 429


def test_looking_at_the_code_page_changes_nothing(app):
    code = freeze(app, count="1")[0]
    before = app.rows("select * from beanbag")
    app.client.get(f"/b/{code}")
    anonymous(app).client.get(f"/b/{code}", headers=BROWSER)
    app.client.get("/b", params={"code": code}, headers=BROWSER)
    assert app.rows("select * from beanbag") == before


def test_deleting_bags_keeps_the_sums_right(app):
    freeze(app, count="2")
    portion = app.scalar("select max(id) from beanbag")
    post(app, f"/bags/{portion}/delete", {})
    assert remaining(app, 1) == 190  # a deleted portion's grams go back to its bag
    post(app, "/bags/1/delete", {})
    assert app.rows("select parent_bag_id from beanbag") == [{"parent_bag_id": None}]  # the other portion stays


def test_portions_survive_export_and_import(app, tmp_path):
    from test_export_import import _engine, export_script, import_script
    freeze(app, count="2")
    export_script.export_all(app.engine, tmp_path / "out")
    target = _engine(tmp_path / "new.db")
    import_script.import_all(target, tmp_path / "out")
    with target.connect() as conn:
        rows = conn.exec_driver_sql("select code, parent_bag_id, is_frozen, frozen_date, given_date from beanbag order by id").fetchall()
    assert rows == [tuple(r.values()) for r in app.rows("select code, parent_bag_id, is_frozen, frozen_date, given_date from beanbag order by id")]


@needs_node
def test_the_qr_code_and_pdf_are_well_formed():
    js = f"""
    const QR = require({json.dumps(str(ROOT / 'app' / 'static' / 'qr.js'))});
    const L = require({json.dumps(str(ROOT / 'app' / 'static' / 'labels_pdf.js'))});
    const label = {{code: 'K7M2P', url: 'https://coffee.rowjee.com/b/K7M2P', name: 'Attikan Estate · Café', grams: '60', cups: 4,
                   roasted_short: '8 Nov', frozen_short: '17 Nov', recipe_short: '15 g · 250 ml · 92 °C'}};
    const labels = Array.from({{length: 11}}, () => label);
    console.log(JSON.stringify({{size: QR.matrix(label.url).length, pdf: L.build(labels, 'coffee.rowjee.com/b')}}));
    """
    out = json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out["size"] == 29  # version 3: a /b address fits comfortably
    pdf = out["pdf"]
    assert pdf.startswith("%PDF-1.4") and pdf.rstrip().endswith("%%EOF")
    assert "/Count 2" in pdf  # 11 labels: two A4 pages of ten
    assert "(K7M2P) Tj" in pdf and "Caf\\351" in pdf and "\\267" in pdf  # é and · in the PDF's own encoding
    # every object is where the cross-reference table says it is
    xref = int(pdf.rsplit("startxref\n", 1)[1].split()[0])
    offsets = [int(line[:10]) for line in pdf[xref:].split("\n")[3:] if re.fullmatch(r"\d{10} 00000 n ", line)]
    for number, offset in enumerate(offsets, start=1):
        assert pdf[offset:].startswith(f"{number} 0 obj"), number
