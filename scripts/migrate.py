"""
Bring the app's database up to the current schema, apply one-off data fixes,
and check the result. Exits non-zero if anything looks wrong.

Usage: python scripts/migrate.py

App startup runs the same schema migrations (db.run_migrations), but deploy
runs this first with the app stopped, so failures surface before restart.
Data fixes live here rather than in run_migrations: each is guarded to match
exactly one known-bad row, so it is a no-op on any other database.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app import db

# (description, UPDATE ... guarded so that it only matches the bad row)
DATA_FIXES = [
    (
        "brew 64: grind recommendation lost its minus sign (iOS keypad bug)",
        """
        UPDATE brew SET recommended_delta = -1.0
        WHERE id = 64
          AND recommended_param = 'grind_size'
          AND recommended_delta = 1.0
          AND trim(recommended_rationale) = 'Extract more'
          AND recipe_id IN (
              SELECT r.id FROM recipe r JOIN bean b ON b.id = r.bean_id
              WHERE b.name = 'Market Lane Coffee Mutura')
        """,
    ),
]


def main() -> None:
    print(f"Migrating {db.DB_FILE}")
    db.create_db_and_tables()
    db.run_migrations()

    with db.engine.begin() as conn:
        for description, sql in DATA_FIXES:
            n = conn.execute(text(sql)).rowcount
            print(f"  data fix ({n} row{'s' if n != 1 else ''}): {description}")

    with db.engine.connect() as conn:
        problems = []
        integrity = conn.execute(text("PRAGMA integrity_check")).scalar()
        if integrity != "ok":
            problems.append(f"integrity_check: {integrity}")
        unassigned = conn.execute(text("SELECT COUNT(*) FROM recipe WHERE line_id IS NULL")).scalar()
        if unassigned:
            problems.append(f"{unassigned} recipe(s) without a named recipe")
        mismatched = conn.execute(text("""
            SELECT COUNT(*) FROM recipe r JOIN recipeline l ON l.id = r.line_id
            WHERE l.bean_id != r.bean_id OR l.brewer_id != r.brewer_id OR l.grinder_id != r.grinder_id
        """)).scalar()
        if mismatched:
            problems.append(f"{mismatched} recipe(s) in a named recipe for a different combination")
        lines = conn.execute(text("SELECT COUNT(*) FROM recipeline")).scalar()
        recipes = conn.execute(text("SELECT COUNT(*) FROM recipe")).scalar()

    if problems:
        print("FAILED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print(f"OK: {recipes} recipe versions in {lines} named recipes")


if __name__ == "__main__":
    main()
