from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "coffee.db"
DATABASE_URL = f"sqlite:///{DB_FILE}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def create_db_and_tables():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def run_migrations():
    with engine.connect() as conn:
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


def get_session():
    with Session(engine) as session:
        yield session


if __name__ == "__main__":
    create_db_and_tables()
    print(f"Created DB: {DB_FILE}")
