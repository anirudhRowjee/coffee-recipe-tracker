"""
Shared fixtures: run the real FastAPI app against a throwaway SQLite file.

`app_on` points app.db.engine at a temp DB (empty, or a copy of a reference
DB), starts the app so its startup migrations run, and returns a TestClient
plus helpers for inspecting the DB. Real database files are only ever read
(via the sqlite backup API), never written.
"""
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# app.main mounts app/static and loads app/templates relative to the cwd
os.chdir(ROOT)

from app import crud, db, main, models  # noqa: E402

REFERENCE_DB = Path(os.environ.get("COFFEE_REFERENCE_DB", ROOT / "data" / "coffee.db")).expanduser()


def copy_db(src: Path, dst: Path) -> None:
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()


@dataclass
class App:
    client: TestClient
    engine: Engine
    path: Path

    def rows(self, sql: str, **params) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(sql), params)]

    def scalar(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def session(self) -> Session:
        return Session(self.engine)

    def sign_in(self, user_id: int) -> None:
        with self.session() as s:
            self.client.cookies.set("session", crud.create_user_session(s, user_id))


@pytest.fixture
def app_on(tmp_path: Path, monkeypatch):
    started: list[TestClient] = []

    def _start(source: Path | None = None, user_id: int | None = 1) -> App:
        path = tmp_path / f"app-{len(started)}.db"
        if source is not None:
            copy_db(source, path)
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        monkeypatch.setattr(db, "engine", engine)
        client = TestClient(main.app)
        client.__enter__()  # runs the startup hook (create tables + migrations)
        started.append(client)
        app = App(client=client, engine=engine, path=path)
        if user_id is not None:
            with app.session() as s:
                if s.get(models.User, user_id):
                    app.sign_in(user_id)
                else:
                    client.cookies.set("session", "not-a-real-session")
        return app

    yield _start
    for client in started:
        client.__exit__(None, None, None)


@pytest.fixture
def reference_db() -> Path:
    if not REFERENCE_DB.exists():
        pytest.skip(f"reference database {REFERENCE_DB} not present")
    return REFERENCE_DB
