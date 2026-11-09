import os
from pathlib import Path

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# COFFEE_DB overrides the location (used by tests that run scripts as subprocesses)
DB_FILE = Path(os.environ.get("COFFEE_DB") or Path(__file__).resolve().parent.parent / "data" / "coffee.db")
DATABASE_URL = f"sqlite:///{DB_FILE}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def _create_tables(target: Engine) -> None:
    # create_all only knows the tables whose models have been imported; a
    # script that imports just this module would otherwise create nothing
    from . import models  # noqa: F401
    SQLModel.metadata.create_all(target)


def create_db_and_tables():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    _create_tables(engine)


def run_migrations(target: Optional[Engine] = None):
    """Bring an existing database up to the current schema. Runs on app
    startup and from scripts/migrate.py; the export/import scripts pass their
    own engine. Creates any missing tables first, so it never depends on the
    caller having done so."""
    target = target or engine
    _create_tables(target)
    with target.connect() as conn:
        for table in ["bean", "brewer", "grinder"]:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES user(id)"))
                conn.commit()
            except Exception:
                pass  # column already exists

        try:
            conn.execute(text("ALTER TABLE beanbag ADD COLUMN is_completed BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
        except Exception:
            pass  # column already exists

        result = conn.execute(text("SELECT COUNT(*) FROM user")).scalar()
        if result == 0:
            conn.execute(text("INSERT INTO user (id, name) VALUES (1, 'Anirudh')"))
            conn.commit()

        for table in ["bean", "brewer", "grinder"]:
            conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))
        conn.commit()

    with target.begin() as conn:
        _migrate_recipe_lines(conn)
        _migrate_brew_ratings(conn)
        _migrate_bean_art(conn)


def _columns(conn, table: str) -> set:
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _migrate_brew_ratings(conn) -> None:
    if "rating" not in _columns(conn, "brew"):
        conn.execute(text("ALTER TABLE brew ADD COLUMN rating INTEGER"))


def _migrate_bean_art(conn) -> None:
    """Accent colour and photo version on beans. The beanimage table itself
    comes from create_all."""
    bean_columns = _columns(conn, "bean")
    if "accent_color" not in bean_columns:
        conn.execute(text("ALTER TABLE bean ADD COLUMN accent_color VARCHAR"))
    if "image_version" not in bean_columns:
        conn.execute(text("ALTER TABLE bean ADD COLUMN image_version INTEGER"))


DEFAULT_LINE_NAME = "Default"


def _migrate_recipe_lines(conn) -> None:
    """Named recipes: add line_id columns and put every recipe without a line
    into its combination's "Default" line (created if missing).

    Idempotent, and also covers recipes restored from pre-line snapshots. The
    recipeline table itself is created by create_db_and_tables().
    """
    if "line_id" not in _columns(conn, "recipe"):
        conn.execute(text("ALTER TABLE recipe ADD COLUMN line_id INTEGER REFERENCES recipeline(id)"))
    if "line_id" not in _columns(conn, "plannedbrew"):
        conn.execute(text("ALTER TABLE plannedbrew ADD COLUMN line_id INTEGER REFERENCES recipeline(id)"))

    combos = conn.execute(text("""
        SELECT bean_id, brewer_id, grinder_id, MIN(created_at)
        FROM recipe WHERE line_id IS NULL
        GROUP BY bean_id, brewer_id, grinder_id
    """)).all()
    for bean_id, brewer_id, grinder_id, first_created in combos:
        combo = {"bean": bean_id, "brewer": brewer_id, "grinder": grinder_id}
        line_id = conn.execute(text("""
            SELECT id FROM recipeline
            WHERE bean_id = :bean AND brewer_id = :brewer AND grinder_id = :grinder AND name = :name
            ORDER BY id LIMIT 1
        """), {**combo, "name": DEFAULT_LINE_NAME}).scalar()
        if line_id is None:
            line_id = conn.execute(text("""
                INSERT INTO recipeline (bean_id, brewer_id, grinder_id, name, created_at)
                VALUES (:bean, :brewer, :grinder, :name, :created)
            """), {**combo, "name": DEFAULT_LINE_NAME, "created": first_created}).lastrowid
        conn.execute(text("""
            UPDATE recipe SET line_id = :line
            WHERE line_id IS NULL AND bean_id = :bean AND brewer_id = :brewer AND grinder_id = :grinder
        """), {**combo, "line": line_id})


def get_session():
    with Session(engine) as session:
        yield session


if __name__ == "__main__":
    create_db_and_tables()
    print(f"Created DB: {DB_FILE}")
