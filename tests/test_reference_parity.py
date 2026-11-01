"""
Parity against real data: start the app on a copy of the reference DB (local
data/coffee.db, or prod via COFFEE_REFERENCE_DB) and check that the brew page
shows exactly what plain SQL on an untouched copy says it should.

For a combination with one history (every combination in a DB from before
named recipes, and any combination with a single named recipe), that is the
original rule, so migrating must change nothing:

  latest recipe   = newest recipe for (bean, brewer, grinder)
  recent brews    = 5 newest brews of that recipe
  change history  = 10 newest deltas into that combination

For a combination with several named recipes, the same rule applies per named
recipe, and the one opened by default is the most recently used (newest
version or brew). Browse shows the newest recipe per bean.

Also checks that startup migrations keep every existing row intact and are
idempotent.
"""
import sqlite3
from pathlib import Path

import pytest

from app import crud, main
from conftest import copy_db

ORIGINAL_TABLES = ["user", "bean", "beanbag", "brewer", "grinder", "recipe", "brew", "plannedbrew", "delta"]


@pytest.fixture
def original(reference_db: Path, tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "original.db"
    copy_db(reference_db, path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _combos(original: sqlite3.Connection) -> list[sqlite3.Row]:
    # one bag per bean is enough: history is per bean, not per bag
    return original.execute("""
        SELECT DISTINCT r.bean_id, r.brewer_id, r.grinder_id, b.user_id,
               (SELECT MIN(id) FROM beanbag WHERE bean_id = r.bean_id) AS bag_id
        FROM recipe r JOIN bean b ON b.id = r.bean_id
        ORDER BY 1, 2, 3
    """).fetchall()


def _lines(original: sqlite3.Connection, c: sqlite3.Row) -> list[int]:
    """Named recipes of a combination, most recently used first ([] if the DB predates them)."""
    if not original.execute("SELECT 1 FROM sqlite_master WHERE name = 'recipeline'").fetchone():
        return []
    return [r["id"] for r in original.execute("""
        SELECT l.id,
               MAX(COALESCE((SELECT MAX(created_at) FROM recipe WHERE line_id = l.id), ''),
                   COALESCE((SELECT MAX(b.brewed_at) FROM brew b JOIN recipe r ON r.id = b.recipe_id
                             WHERE r.line_id = l.id), ''),
                   l.created_at) AS last_used
        FROM recipeline l
        WHERE l.bean_id = ? AND l.brewer_id = ? AND l.grinder_id = ?
        ORDER BY last_used DESC, l.id DESC
    """, (c["bean_id"], c["brewer_id"], c["grinder_id"]))]


def _expected(original: sqlite3.Connection, where: str, params: tuple) -> dict:
    """Latest recipe, its recent brews and the recent deltas among the recipes matching `where`."""
    latest = original.execute(
        f"SELECT id FROM recipe r WHERE {where} ORDER BY created_at DESC LIMIT 1", params).fetchone()["id"]
    brews = [r["id"] for r in original.execute(
        "SELECT id FROM brew WHERE recipe_id=? ORDER BY brewed_at DESC LIMIT 5", (latest,))]
    deltas = [r["id"] for r in original.execute(f"""
        SELECT d.id FROM delta d JOIN recipe r ON r.id = d.to_recipe_id
        WHERE {where} ORDER BY d.created_at DESC LIMIT 10""", params)]
    return {"latest": latest, "brews": brews, "deltas": deltas}


def _expected_for(original: sqlite3.Connection, c: sqlite3.Row, line_id: int | None = None) -> dict:
    """What the brew page should show for combination c (its default recipe, or line_id)."""
    lines = _lines(original, c)
    if len(lines) <= 1:  # the original single-history rule
        return _expected(original, "r.bean_id=? AND r.brewer_id=? AND r.grinder_id=?",
                         (c["bean_id"], c["brewer_id"], c["grinder_id"]))
    return _expected(original, "r.line_id=?", (line_id or lines[0],))


def _actual(session, c: sqlite3.Row, line_id: int | None = None) -> dict:
    ctx = main._latest_recipe_context(session, c["bag_id"], c["brewer_id"], c["grinder_id"], c["user_id"], line_id)
    return {
        "latest": ctx["latest"].id,
        "brews": [b.id for b in ctx["recent_brews"]],
        "deltas": [d.id for d in ctx["recent_deltas"]],
    }


def test_every_combination_shows_the_same_recipe_history(app_on, reference_db, original):
    app = app_on(reference_db)
    combos = [c for c in _combos(original) if c["bag_id"] is not None]
    assert combos, "reference DB has no recipes"
    with app.session() as session:
        for c in combos:
            assert _actual(session, c) == _expected_for(original, c), dict(c)


def test_each_named_recipe_shows_its_own_history(app_on, reference_db, original):
    app = app_on(reference_db)
    with app.session() as session:
        for c in _combos(original):
            lines = _lines(original, c)
            if c["bag_id"] is None or len(lines) <= 1:
                continue
            for line_id in lines:
                assert _actual(session, c, line_id) == _expected_for(original, c, line_id), (dict(c), line_id)


def test_every_combination_renders(app_on, reference_db, original):
    app = app_on(reference_db)
    for c in _combos(original):
        if c["bag_id"] is None:
            continue
        app.client.cookies.set("user_id", str(c["user_id"]))
        r = app.client.get("/recipes/latest", params={
            "bag_id": c["bag_id"], "brewer_id": c["brewer_id"], "grinder_id": c["grinder_id"]})
        assert r.status_code == 200
        grind = original.execute("SELECT grind_size FROM recipe WHERE id=?",
                                 (_expected_for(original, c)["latest"],)).fetchone()[0]
        assert f"<strong>Grind:</strong> {grind}" in r.text, dict(c)


def test_browse_shows_newest_recipe_per_bean(app_on, reference_db, original):
    app = app_on(reference_db)
    users = [r["id"] for r in original.execute("SELECT id FROM user")]
    with app.session() as session:
        for user_id in users:
            for bean, recipe, *_ in crud.get_latest_recipe_per_bean(session, user_id):
                expected = original.execute(
                    "SELECT id FROM recipe WHERE bean_id=? ORDER BY created_at DESC LIMIT 1", (bean.id,)).fetchone()
                assert (recipe.id if recipe else None) == (expected["id"] if expected else None), bean.name


def test_every_page_renders_for_every_user(app_on, reference_db, original):
    app = app_on(reference_db)
    for user in original.execute("SELECT id FROM user"):
        app.client.cookies.set("user_id", str(user["id"]))
        for page in ["/", "/browse", "/manage"]:
            assert app.client.get(page).status_code == 200, (page, user["id"])


def test_every_named_recipe_exports(app_on, reference_db):
    app = app_on(reference_db)
    lines = app.rows("""
        SELECT l.id, b.user_id,
               (SELECT grind_size FROM recipe WHERE line_id = l.id ORDER BY created_at DESC LIMIT 1) AS grind
        FROM recipeline l JOIN bean b ON b.id = l.bean_id
    """)
    assert lines
    for line in lines:
        app.client.cookies.set("user_id", str(line["user_id"]))
        r = app.client.get(f"/lines/{line['id']}/export.md")
        assert r.status_code == 200, line
        assert f"\n- Grind: {line['grind']} on " in r.text, line
        r = app.client.get(f"/lines/{line['id']}/brew")
        assert r.status_code == 200, line
        assert f"<dt>Grind</dt>\n            <dd>{line['grind']}</dd>" in r.text, line


def test_startup_keeps_existing_rows_intact(app_on, reference_db, original):
    app = app_on(reference_db)
    migrated = sqlite3.connect(app.path)
    try:
        for table in ORIGINAL_TABLES:
            cols = [r[1] for r in original.execute(f'PRAGMA table_info("{table}")')]
            select = f'SELECT {", ".join(cols)} FROM "{table}" ORDER BY id'
            assert migrated.execute(select).fetchall() == [tuple(r) for r in original.execute(select)], table
        assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        migrated.close()


def test_startup_migrations_are_idempotent(app_on, reference_db):
    once = app_on(reference_db)
    twice = app_on(once.path)  # copy of the migrated DB, migrated again
    dump = lambda p: list(sqlite3.connect(p).iterdump())  # noqa: E731
    assert dump(once.path) == dump(twice.path)
