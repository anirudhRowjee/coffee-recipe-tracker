"""
Drop all tables and recreate the schema (wipes all data).
Usage: python scripts/drop_tables.py
Prompts for confirmation before proceeding.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import SQLModel
from app import db
from app.models import Bean, BeanBag, Brewer, Grinder, Recipe, Brew, Delta  # noqa: F401 — registers models

confirm = input("This will DELETE ALL DATA. Type 'yes' to continue: ")
if confirm.strip().lower() != "yes":
    print("Aborted.")
    sys.exit(0)

SQLModel.metadata.drop_all(db.engine)
db.create_db_and_tables()
print("All tables dropped and recreated.")
