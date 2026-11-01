"""
Round-trip tests for scripts/export.py and scripts/import.py.

The reference database is data/coffee.db, or the file named by the
COFFEE_REFERENCE_DB environment variable (e.g. a downloaded prod backup). It is
copied into a temp directory first, so the file is only ever read, never written.

Run with: .venv/bin/pytest tests/
     or:  COFFEE_REFERENCE_DB=~/coffee.db .venv/bin/pytest tests/
"""
import importlib.util
import os
import sqlite3
from pathlib import Path

import pytest
from sqlmodel import SQLModel, create_engine

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DB = Path(os.environ.get("COFFEE_REFERENCE_DB", ROOT / "data" / "coffee.db")).expanduser()
LEGACY_SNAPSHOT = ROOT / "export"

TABLES = ["user", "bean", "beanbag", "brewer", "grinder", "recipeline", "recipe", "brew", "plannedbrew", "delta"]


def _load_script(name: str):
    # import.py can't be imported normally ("import" is a keyword)
    spec = importlib.util.spec_from_file_location(f"coffee_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_script = _load_script("export")
import_script = _load_script("import")


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def _dump(path: Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            t: [dict(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY id')]
            for t in TABLES
        }
    finally:
        conn.close()


@pytest.fixture
def reference_db(tmp_path: Path) -> Path:
    if not REFERENCE_DB.exists():
        pytest.skip(f"reference database {REFERENCE_DB} not present")
    copy = tmp_path / "reference.db"
    # sqlite backup API rather than a file copy, so a DB that is in use
    # (or has a -wal file) is copied consistently
    src, dst = sqlite3.connect(REFERENCE_DB), sqlite3.connect(copy)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return copy


def test_round_trip_matches_reference(reference_db: Path, tmp_path: Path):
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored.db"

    export_script.export_all(_engine(reference_db), snapshot)
    import_script.import_all(_engine(restored), snapshot)

    expected = _dump(reference_db)
    actual = _dump(restored)
    for table in TABLES:
        assert actual[table] == expected[table], f"table {table!r} differs after round trip"


def test_round_trip_is_stable(reference_db: Path, tmp_path: Path):
    # Exporting the restored DB must produce byte-identical CSVs.
    first, second = tmp_path / "first", tmp_path / "second"
    restored = tmp_path / "restored.db"

    export_script.export_all(_engine(reference_db), first)
    import_script.import_all(_engine(restored), first)
    export_script.export_all(_engine(restored), second)

    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(p.name for p in second.iterdir())
    for name in names:
        assert (first / name).read_text() == (second / name).read_text(), name


def test_reference_owner_columns_survive(reference_db: Path, tmp_path: Path):
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored.db"
    export_script.export_all(_engine(reference_db), snapshot)
    import_script.import_all(_engine(restored), snapshot)

    conn = sqlite3.connect(restored)
    try:
        for table in ["bean", "brewer", "grinder"]:
            nulls = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL").fetchone()[0]
            assert nulls == 0, f"{table} rows lost their user_id"
    finally:
        conn.close()


def test_legacy_snapshot_still_imports(tmp_path: Path):
    if not (LEGACY_SNAPSHOT / "beans.csv").exists():
        pytest.skip("legacy export/ snapshot not present")
    assert not (LEGACY_SNAPSHOT / "users.csv").exists(), "export/ is no longer a legacy snapshot"

    restored = tmp_path / "legacy.db"
    import_script.import_all(_engine(restored), LEGACY_SNAPSHOT)

    dump = _dump(restored)
    assert dump["bean"], "no beans imported"
    assert all(b["thaw_date"] is None for b in dump["beanbag"])
    assert dump["plannedbrew"] == []
    # gaps are filled exactly as app startup would fill them
    assert [u["id"] for u in dump["user"]] == [1]
    assert all(b["user_id"] == 1 for b in dump["bean"])
    combos = {(r["bean_id"], r["brewer_id"], r["grinder_id"]) for r in dump["recipe"]}
    assert len(dump["recipeline"]) == len(combos)
    assert all(ln["name"] == "Default" for ln in dump["recipeline"])
    line_of = {ln["id"]: (ln["bean_id"], ln["brewer_id"], ln["grinder_id"]) for ln in dump["recipeline"]}
    assert all(line_of[r["line_id"]] == (r["bean_id"], r["brewer_id"], r["grinder_id"]) for r in dump["recipe"])


def test_import_refuses_non_empty_database(reference_db: Path, tmp_path: Path):
    snapshot = tmp_path / "snapshot"
    export_script.export_all(_engine(reference_db), snapshot)

    with pytest.raises(SystemExit):
        import_script.import_all(_engine(reference_db), snapshot)


def test_import_refuses_when_only_users_exist(tmp_path: Path):
    # e.g. the app started on an empty DB and run_migrations seeded user 1
    target = tmp_path / "seeded.db"
    engine = _engine(target)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO user (id, name) VALUES (1, 'seed')")

    snapshot = tmp_path / "snapshot"
    export_script.export_all(_engine(tmp_path / "empty.db"), snapshot)
    with pytest.raises(SystemExit):
        import_script.import_all(engine, snapshot)


def test_round_trip_keeps_named_recipes_and_plans(app_on, tmp_path: Path):
    app = app_on()
    for url, data in [
        ("/beans", {"name": "Blue Tokai Baarbara Estate"}),
        ("/bags", {"bean_id": 1, "initial_quantity_g": 250}),
        ("/brewers", {"name": "Hario Switch"}),
        ("/grinders", {"name": "Timemore C2"}),
        ("/recipes", {"bean_id": 1, "brewer_id": 1, "grinder_id": 1, "dose_g": 15, "water_ml": 250,
                      "temp_c": 93, "grind_size": "13"}),
        ("/recipes", {"bean_id": 1, "brewer_id": 1, "grinder_id": 1, "dose_g": 30, "water_ml": 500,
                      "temp_c": 93, "grind_size": "14", "line_name": "2 cup"}),
        ("/recipes", {"bean_id": 1, "brewer_id": 1, "grinder_id": 1, "dose_g": 30, "water_ml": 500,
                      "temp_c": 93, "grind_size": "12", "previous_recipe_id": 2,
                      "changed_param": "grind_size", "delta_amount": "-2", "bag_id": 1}),
        ("/plan", {"bag_id": 1, "brewer_id": 1, "grinder_id": 1, "line_id": 2}),
    ]:
        assert app.client.post(url, data=data, follow_redirects=False).status_code == 303, url

    snapshot, restored = tmp_path / "snapshot", tmp_path / "restored.db"
    export_script.export_all(app.engine, snapshot)
    import_script.import_all(_engine(restored), snapshot)

    expected, actual = _dump(app.path), _dump(restored)
    assert [ln["name"] for ln in actual["recipeline"]] == ["Default", "2 cup"]
    assert actual["plannedbrew"][0]["line_id"] == 2
    for table in TABLES:
        assert actual[table] == expected[table], table
