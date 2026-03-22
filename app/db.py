from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "coffee.db"
DATABASE_URL = f"sqlite:///{DB_FILE}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def create_db_and_tables():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


if __name__ == "__main__":
    create_db_and_tables()
    print(f"Created DB: {DB_FILE}")
