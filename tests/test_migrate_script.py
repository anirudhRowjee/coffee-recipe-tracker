"""
scripts/migrate.py exactly as deploy runs it: a separate process that imports
only what the script imports, pointed at a copy of the reference DB via
COFFEE_DB. (Running inside pytest would hide import-order bugs, because the
test process has already imported every model.)
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

from conftest import ROOT, copy_db


def run_migrate(db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/migrate.py"], cwd=ROOT, capture_output=True, text=True,
        env={"COFFEE_DB": str(db_path), "PATH": "/usr/bin:/bin"},
    )


def test_migrate_script_on_reference_db(reference_db: Path, tmp_path: Path):
    db = tmp_path / "ref.db"
    copy_db(reference_db, db)

    first = run_migrate(db)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "OK:" in first.stdout

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM recipe WHERE line_id IS NULL").fetchone()[0] == 0
        dump = list(conn.iterdump())
    finally:
        conn.close()

    second = run_migrate(db)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "data fix (0 rows)" in second.stdout
    conn = sqlite3.connect(db)
    try:
        assert list(conn.iterdump()) == dump, "second run changed the database"
    finally:
        conn.close()


def test_migrate_script_fixes_only_the_known_bad_recommendation(app_on, tmp_path: Path):
    app = app_on()
    for url, data in [
        ("/beans", {"name": "Market Lane Coffee Mutura"}),
        ("/beans", {"name": "Some Other Bean"}),
        ("/bags", {"bean_id": 1, "initial_quantity_g": 250}),
        ("/bags", {"bean_id": 2, "initial_quantity_g": 250}),
        ("/brewers", {"name": "Switch"}),
        ("/grinders", {"name": "C2"}),
        ("/recipes", {"bean_id": 1, "brewer_id": 1, "grinder_id": 1, "dose_g": 15, "water_ml": 250, "temp_c": 93, "grind_size": "21"}),
        ("/recipes", {"bean_id": 2, "brewer_id": 1, "grinder_id": 1, "dose_g": 15, "water_ml": 250, "temp_c": 93, "grind_size": "21"}),
    ]:
        assert app.client.post(url, data=data, follow_redirects=False).status_code == 303
    bad = {"recommended_param": "grind_size", "recommended_delta": "1", "recommended_rationale": "Extract more "}
    with app.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO brew (id, recipe_id, bag_id, recommended_param, recommended_delta, recommended_rationale, brewed_at) "
            "VALUES (64, 1, 1, ?, 1.0, ?, '2026-10-01 10:39:35'), (65, 2, 2, ?, 1.0, ?, '2026-10-02 10:00:00')",
            (bad["recommended_param"], bad["recommended_rationale"]) * 2,
        )

    result = run_migrate(app.path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "data fix (1 row)" in result.stdout
    assert app.rows("SELECT id, recommended_delta FROM brew ORDER BY id") == [
        {"id": 64, "recommended_delta": -1.0},
        {"id": 65, "recommended_delta": 1.0},  # same text, different bean: untouched
    ]
