"""
The invariants that shape the app, each as a test. They are written to hold for any
data, so most run twice: on a "busy" account built through every way of making
versions, cups and plans, and (where they're about data) on a copy of the reference
database. AGENTS.md ("Invariants") lists them with the reasons behind them.

When one of these fails, the code is wrong, or the design changed: then change the
test and AGENTS.md together, on purpose.
"""
import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import main
from test_accounts import GET_ATTACKS, POST_ATTACKS, PUBLIC_ROUTES
from test_flows import BASELINE, COMBO, post

FIELDS = ("dose_g", "water_ml", "temp_c", "grind_size", "recipe_text")
STEPS = "0:00 — Bloom (to 44g)\n0:45 — Pour (to 96g)\n1:30 — Pour (to 240g)\n2:45 — Done"
TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


# --- a busy account: every path that makes versions, cups and plans ------------------

@pytest.fixture
def busy(app_on):
    a = app_on()
    post(a, "/beans", {"name": "Kanake", "initial_quantity_g": "250", "flavor_notes": "blackcurrant"})   # bean 1, bag 1
    post(a, "/beans", {"name": "Akaako", "initial_quantity_g": "200"})                                   # bean 2, bag 2
    post(a, "/brewers", {"name": "Hario Switch", "method": "Switch"})                                    # brewer 1
    post(a, "/grinders", {"name": "Timemore C2"})                                                        # grinder 1
    post(a, "/grinders", {"name": "Budan"})                                                              # grinder 2
    post(a, "/recipes", {**BASELINE, "recipe_text": STEPS})                                              # line 1, v1
    post(a, "/brews", {"recipe_id": 1, "bag_id": 1, "recommended_param": "temp_c", "recommended_delta": "2",
                       "rating": "3", "curve": json.dumps({"t": [0, 1, 2], "g": [0, 40, 44], "f": [0, 40, 4]})})
    post(a, "/recipes", {**BASELINE, "recipe_text": STEPS, "previous_recipe_id": 1, "temp_c": "95",
                         "changed_param": "dose_g", "delta_amount": "-9"})                               # v2 (Try a change)
    post(a, "/brews", {"recipe_id": 2, "bag_id": 1, "recommended_param": "grind_size", "recommended_delta": "-1"})
    post(a, "/brews", {"recipe_id": 2, "bag_id": 1, "try_param": "grind_size", "try_value": "12",
                       "try_rationale": "sour"})                                                         # v3 (Brew with change)
    post(a, "/lines/1/undo", {})                                                                         # v4 (undo)
    post(a, "/recipes/4/fix", {"value": "11", "rationale": "finer still"})                               # v4 fixed
    post(a, "/four-six", {"bag_id": 1, "brewer_id": 1, "grinder_id": 2, "coffee": "20", "ratio": "15",
                          "temp_c": "93", "taste": "0.4", "pours": "3", "grind_size": "28"})            # line 2
    post(a, "/lines/1/copy", {"bean_id": 2, "brewer_id": 1, "grinder_id": 1})                            # line 3, bean 2
    post(a, "/plan", {"bag_id": 1, "line_id": 2, "suggested_param": "dose_g", "suggested_delta": "1"})  # gear from line 2
    post(a, "/plan", {"bag_id": 2, "line_id": 3})                                                        # replaces it
    r = a.client.post("/brews/1/delete", follow_redirects=False)
    post(a, "/brews/undo", {"token": r.headers["location"].split("=", 1)[1]})
    post(a, f"/brews/{a.scalar('select max(id) from brew')}/edit", {"notes": "x\nCooled: sweet", "rating": "4"})
    return a


def _conn(app):
    return sqlite3.connect(app.path)


def _same(field, a, b):
    if field in ("grind_size", "recipe_text"):
        return "\n".join(str(a or "").splitlines()).strip() == "\n".join(str(b or "").splitlines()).strip()
    return float(a) == float(b)


# --- the one-change rule ---------------------------------------------------------

def _version_problems(conn, check_amounts=True):
    """Every version with a parent: in its parent's named recipe, exactly one value
    different, and one delta that names that value (and its real amount)."""
    problems = []
    rows = conn.execute(f"SELECT id, previous_recipe_id, line_id, {', '.join(FIELDS)} FROM recipe WHERE previous_recipe_id IS NOT NULL")
    for rid, pid, line, *after in rows.fetchall():
        parent = conn.execute(f"SELECT line_id, {', '.join(FIELDS)} FROM recipe WHERE id = ?", (pid,)).fetchone()
        if parent is None:
            problems.append((rid, "parent missing"))
            continue
        if parent[0] != line:
            problems.append((rid, "left its parent's recipe"))
        changed = [f for f, a, b in zip(FIELDS, parent[1:], after) if not _same(f, a, b)]
        if len(changed) != 1:
            problems.append((rid, f"changes {changed}"))
            continue
        deltas = conn.execute("SELECT changed_param, delta_amount FROM delta WHERE to_recipe_id = ?", (rid,)).fetchall()
        if len(deltas) != 1 or deltas[0][0] != changed[0]:
            problems.append((rid, f"delta {deltas} for {changed}"))
        elif check_amounts and changed[0] != "recipe_text":
            try:
                real = float(after[FIELDS.index(changed[0])]) - float(parent[1 + FIELDS.index(changed[0])])
                if abs(real - deltas[0][1]) > 1e-6:
                    problems.append((rid, f"amount {deltas[0][1]}, really {real}"))
            except ValueError:
                pass
    return problems


def test_every_version_is_exactly_one_change_from_its_parent(busy):
    assert busy.scalar("select count(*) from recipe where previous_recipe_id is not null") >= 3
    assert _version_problems(_conn(busy)) == []


def test_real_data_keeps_the_one_change_rule(app_on, reference_db):
    # amounts typed by hand before the server derived them can be wrong (prod change #22): not checked here
    assert _version_problems(_conn(app_on(reference_db, user_id=None)), check_amounts=False) == []


def test_two_changes_at_once_are_always_refused(busy):
    latest = busy.rows(f"select {', '.join(FIELDS)} from recipe where line_id = 1 order by created_at desc limit 1")[0]
    r = busy.client.post("/recipes", data={**BASELINE, **latest, "previous_recipe_id": 4, "dose_g": "16", "temp_c": "90"})
    assert r.status_code == 400


def test_there_is_no_way_to_jump_back_to_an_older_version():
    # every way to make a version starts from the newest one; none takes "make version N current"
    paths = {r.path for r in main.app.routes if "POST" in getattr(r, "methods", set())}
    assert not any(re.search(r"revert|restore|rollback|make-current|go-back", p) for p in paths)


# --- cups, bags and what a version save does -------------------------------------

def test_saving_a_version_never_logs_a_cup_by_itself(busy):
    before = busy.scalar("select count(*) from brew")
    post(busy, "/recipes", {**BASELINE, "recipe_text": STEPS, "previous_recipe_id": 4, "temp_c": "91", "grind_size": "11"})
    post(busy, "/lines/1/undo", {})
    post(busy, "/four-six", {"bag_id": 1, "brewer_id": 1, "grinder_id": 1, "coffee": "15", "ratio": "16",
                             "temp_c": "93", "taste": "0", "pours": "2", "grind_size": "20"})
    assert busy.scalar("select count(*) from brew") == before


def _bag_problems(app):
    with app.session() as s:
        from app import crud, models
        from sqlmodel import select
        problems = []
        for bag in s.exec(select(models.BeanBag)).all():
            used = sum(b.recipe.dose_g for b in bag.brews)
            if abs(crud.get_remaining_quantity(s, bag) - (bag.initial_quantity_g - used)) > 1e-6:
                problems.append(bag.id)
        return problems


def test_a_bag_holds_what_was_bought_minus_every_cup(busy, app_on, reference_db):
    assert _bag_problems(busy) == []
    assert _bag_problems(app_on(reference_db, user_id=None)) == []


# --- a change to try belongs to the recipe, never to a plan -----------------------

def _changes(app):
    return app.rows("select id, next_param, next_delta, next_rationale from recipeline order by id")


def test_plans_never_carry_or_drop_a_change(busy):
    kept = _changes(busy)
    assert [c["id"] for c in kept if c["next_param"] == "dose_g"] == [2]  # set while planning line 2, kept after being replaced
    plan = busy.scalar("select id from plannedbrew")
    post(busy, f"/plan/{plan}/cancel", {})
    post(busy, "/plan", {"bag_id": 1, "line_id": 2})
    post(busy, "/plan", {"bag_id": 2, "line_id": 3})
    assert _changes(busy) == kept
    assert busy.rows("select suggested_param from plannedbrew") == [{"suggested_param": None}]


def test_only_the_recipes_next_version_clears_its_change(busy):
    assert busy.scalar("select next_param from recipeline where id = 2") == "dose_g"
    post(busy, "/brews", {"recipe_id": busy.scalar("select max(id) from recipe where line_id = 2"), "bag_id": 1})
    assert busy.scalar("select next_param from recipeline where id = 2") == "dose_g"  # a cup that didn't try it
    v = busy.rows(f"select id, {', '.join(FIELDS)} from recipe where line_id = 2")[0]
    post(busy, "/recipes", {**{f: v[f] for f in FIELDS}, "bean_id": 1, "brewer_id": 1, "grinder_id": 2,
                            "previous_recipe_id": v["id"], "dose_g": v["dose_g"] + 1})
    assert busy.scalar("select next_param from recipeline where id = 2") is None


def test_a_cups_own_note_wins_over_the_planned_change(busy):
    post(busy, "/lines/1/next", {"suggested_param": "water_ml", "suggested_delta": "10"})
    post(busy, "/brews", {"recipe_id": 4, "bag_id": 1, "recommended_param": "temp_c", "recommended_delta": "1"})
    html = busy.client.get("/recipes/latest", params={**COMBO, "line_id": 1}).text
    assert 'data-rec="brew"' in html and "Temp +1 °C" in html and "Water +10 ml" not in html


def test_there_is_at_most_one_plan_per_person(busy):
    for line in (1, 2, 1):
        post(busy, "/plan", {**COMBO, "line_id": line})
    assert busy.rows("select user_id, count(*) n from plannedbrew group by user_id having n > 1") == []


# --- nobody else's data, and nothing changes by looking ----------------------------

def test_every_route_that_takes_an_id_is_attacked_as_someone_else():
    """test_accounts attacks each route as a second user; a new route with an id must join it."""
    attacked = {re.sub(r"\d+", "{}", url) for url, _ in GET_ATTACKS + POST_ATTACKS}
    attacked |= {"/recipes/latest", "/four-six", "/"}
    missing = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if "{" not in path or path.startswith("/static") or path in PUBLIC_ROUTES:
            continue
        if path in ("/{kind}/{item_id}/archive",):  # attacked as /brewers/1/archive and /grinders/1/archive
            continue
        if path.startswith("/users/"):  # admin-only: test_accounts checks a non-admin can't use them
            continue
        if re.sub(r"\{[^}]+\}", "{}", path) not in attacked:
            missing.append(path)
    assert missing == []


def _dump(app):
    conn = _conn(app)
    try:
        return [line for line in conn.iterdump() if not line.startswith("INSERT INTO \"usersession\"")]
    finally:
        conn.close()


PAGES = [
    "/", "/?pick=1", "/?bag_id=1", "/?bag_id=1&gear=pick", "/?bag_id=2&brewer_id=1&grinder_id=2",
    "/browse", "/browse?bean=1", "/manage", "/help", "/account",
    "/lines/1/change?bag_id=1", "/lines/1/change?bag_id=1&method=1&actual=1", "/lines/1/versions?bag_id=1",
    "/lines/1/versions?compare=1", "/lines/1/brew?bag_id=1", "/lines/1/brew?bag_id=1&try=1",
    "/lines/1/brew?bag_id=1&recipe_id=1", "/lines/1/share-image", "/lines/1/export.md",
    "/four-six?bag_id=1&brewer_id=1&grinder_id=1", "/brews/2/edit", "/brews/2/edit?cooled=1",
    "/recipes/latest?bag_id=1&brewer_id=1&grinder_id=1",
]


def test_looking_never_changes_anything(busy):
    before = _dump(busy)
    for page in PAGES:
        assert busy.client.get(page).status_code == 200, page
    assert _dump(busy) == before


# --- pages: words, structure, touch --------------------------------------------------

class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.sheets_opened, self.dialogs, self.forms, self.text = [], set(), set(), [], []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if "data-sheet" in a:
            self.sheets_opened.add(a["data-sheet"])
        if tag == "dialog" and "id" in a:
            self.dialogs.add(a["id"])
        if tag == "form":
            self.forms.append(a)
        if tag in ("script", "style", "template", "textarea", "option", "select"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template", "textarea", "option", "select"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def _parse(app, url):
    p = _Page()
    p.feed(app.client.get(url).text)
    return p


HTML_PAGES = [p for p in PAGES if not p.endswith(".md")]
FULL_PAGES = [p for p in HTML_PAGES if not p.startswith("/recipes/latest")]  # the card on its own is a fragment


@pytest.mark.parametrize("url", HTML_PAGES)
def test_pages_speak_in_words_not_field_names(busy, url):
    text = " ".join(_parse(busy, url).text)
    assert not re.search(r"\b(dose_g|water_ml|temp_c|grind_size|recipe_text|temp c|dose g)\b", text), url
    assert not re.search(r"\b\d+\.0 ?(g|ml|°C)\b", text), url  # "15.0 g": numbers go through words.num


@pytest.mark.parametrize("url", HTML_PAGES)
def test_every_id_on_a_page_is_unique(busy, url):
    ids = _parse(busy, url).ids
    assert sorted({i for i in ids if ids.count(i) > 1}) == [], url


@pytest.mark.parametrize("url", FULL_PAGES)
def test_every_sheet_a_page_opens_is_on_that_page(busy, url):
    page = _parse(busy, url)
    assert page.sheets_opened <= page.dialogs, url


def _route_matches(path):
    for route in main.app.routes:
        if "POST" in getattr(route, "methods", set()) and re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", route.path), path):
            return True
    return False


@pytest.mark.parametrize("url", HTML_PAGES)
def test_every_form_posts_to_a_real_route_and_deletes_are_guarded(busy, url):
    for form in _parse(busy, url).forms:
        if (form.get("method") or "get").lower() != "post":
            continue
        action = form.get("action", "")
        assert _route_matches(action), (url, action)
        if action.endswith("/delete") and not action.startswith("/brews/"):  # a cup has Undo instead
            assert "confirm(" in (form.get("onsubmit") or ""), (url, action)


@pytest.mark.parametrize("url", [p for p in FULL_PAGES if "/brew?" not in p])
def test_every_page_but_brew_mode_has_the_tab_bar(busy, url):
    assert 'class="tabbar"' in busy.client.get(url).text, url


def test_brew_mode_is_the_screen_and_nothing_else(busy):
    html = busy.client.get("/lines/1/brew", params={"bag_id": 1}).text
    assert 'class="tabbar"' not in html and 'class="site-header"' not in html


def test_static_files_always_carry_their_content_hash():
    for path in TEMPLATES.rglob("*.html"):
        assert not re.search(r"""(src|href)=["']/static/""", path.read_text()), path


def test_back_links_go_back():
    for path in TEMPLATES.rglob("*.html"):
        for link in re.findall(r"<a[^>]*>\s*(?:‹|←) Back\s*</a>", path.read_text()):
            assert "data-back" in link, (path, link)


def test_touch_targets_are_at_least_44px():
    css = (TEMPLATES.parent / "static" / "styles.css").read_text()
    assert re.search(r"button, \.btn-brew, select, input:not\(\[type=radio\]\):not\(\[type=checkbox\]\) \{ min-height: 44px; \}", css)
    # small round buttons keep a 44 px hit area around them
    assert ".tip-btn::after" in css and ".plan-x::after" in css


def test_every_tip_in_a_template_has_words():
    from app.tips import TIPS
    used = set()
    for path in TEMPLATES.rglob("*.html"):
        used |= set(re.findall(r"tip\('([a-z_]+)'", path.read_text()))
    assert used and used <= set(TIPS)
