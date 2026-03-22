"""
Restore all data from a CSV snapshot produced by scripts/export.py.

Usage:
    python scripts/import.py                  # reads from export/
    python scripts/import.py path/to/snapshot # reads from a custom directory

The target database must be empty (all tables have zero rows). Run
scripts/drop_tables.py first if you need to wipe an existing database.

Import order respects foreign-key dependencies:
    Bean → BeanBag
    Brewer
    Grinder
    Recipe (self-referential previous_recipe_id handled in two passes)
    Brew → Recipe + BeanBag
    Delta → Recipe
"""

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select, text
from app import db
from app.models import Bean, BeanBag, Brewer, Grinder, Recipe, Brew, Delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(val: str) -> str | None:
    return val.strip() or None

def _int(val: str) -> int | None:
    v = val.strip()
    return int(v) if v else None

def _float(val: str) -> float | None:
    v = val.strip()
    return float(v) if v else None

def _date(val: str) -> date | None:
    v = val.strip()
    if not v:
        return None
    # export writes date objects as YYYY-MM-DD
    return date.fromisoformat(v[:10])

def _datetime(val: str) -> datetime | None:
    v = val.strip()
    if not v:
        return None
    # export writes datetime with possible timezone suffix
    v = v[:26]  # trim microseconds beyond 6 digits if any
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        dt = datetime.strptime(v, "%Y-%m-%d %H:%M:%S.%f")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")

def abort(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        abort(f"{path} not found. Are you pointing at the right snapshot directory?")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Preflight check
# ---------------------------------------------------------------------------

def check_empty(session: Session) -> None:
    for model, name in [(Bean, "bean"), (BeanBag, "beanbag"), (Brewer, "brewer"),
                        (Grinder, "grinder"), (Recipe, "recipe"), (Brew, "brew"), (Delta, "delta")]:
        count = session.exec(select(model)).all()
        if count:
            abort(
                f'Table "{name}" already has {len(count)} row(s). '
                "Run scripts/drop_tables.py first, or point at an empty database."
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("export")
    if not src.is_dir():
        abort(f'Snapshot directory "{src}" does not exist.')

    print(f"Importing from {src.resolve()}/")

    db.create_db_and_tables()

    with Session(db.engine) as session:
        check_empty(session)

        # 1. Beans
        rows = read_csv(src / "beans.csv")
        for r in rows:
            session.add(Bean(
                id=_int(r["id"]),
                name=r["name"],
                origin=_str(r["origin"]),
                roast_level=_str(r["roast_level"]),
                flavor_notes=_str(r["flavor_notes"]),
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  beans:    {len(rows)}")

        # 2. Brewers
        rows = read_csv(src / "brewers.csv")
        for r in rows:
            session.add(Brewer(
                id=_int(r["id"]),
                name=r["name"],
                method=_str(r["method"]),
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  brewers:  {len(rows)}")

        # 3. Grinders
        rows = read_csv(src / "grinders.csv")
        for r in rows:
            session.add(Grinder(
                id=_int(r["id"]),
                name=r["name"],
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  grinders: {len(rows)}")

        # 4. Bags
        rows = read_csv(src / "bags.csv")
        for r in rows:
            session.add(BeanBag(
                id=_int(r["id"]),
                bean_id=_int(r["bean_id"]),
                roast_date=_date(r["roast_date"]),
                purchase_date=_date(r["purchase_date"]),
                initial_quantity_g=float(r["initial_quantity_g"]),
                low_threshold_g=float(r["low_threshold_g"]),
                is_frozen=_bool(r["is_frozen"]),
                frozen_date=_date(r["frozen_date"]),
                is_completed=_bool(r.get("is_completed", "")),
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  bags:     {len(rows)}")

        # 5. Recipes — two passes to handle self-referential previous_recipe_id
        rows = read_csv(src / "recipes.csv")

        # Pass 1: insert all recipes without previous_recipe_id
        for r in rows:
            session.add(Recipe(
                id=_int(r["id"]),
                bean_id=_int(r["bean_id"]),
                brewer_id=_int(r["brewer_id"]),
                grinder_id=_int(r["grinder_id"]),
                dose_g=float(r["dose_g"]),
                water_ml=float(r["water_ml"]),
                temp_c=float(r["temp_c"]),
                grind_size=r["grind_size"],
                recipe_text=_str(r["recipe_text"]),
                previous_recipe_id=None,
                created_at=_datetime(r["created_at"]) or datetime.now(timezone.utc),
            ))
        session.commit()

        # Pass 2: set previous_recipe_id where applicable
        for r in rows:
            prev_id = _int(r["previous_recipe_id"])
            if prev_id is not None:
                recipe = session.get(Recipe, _int(r["id"]))
                recipe.previous_recipe_id = prev_id
        session.commit()
        print(f"  recipes:  {len(rows)}")

        # 6. Brews
        rows = read_csv(src / "brews.csv")
        for r in rows:
            session.add(Brew(
                id=_int(r["id"]),
                recipe_id=_int(r["recipe_id"]),
                bag_id=_int(r["bag_id"]),
                notes=_str(r["notes"]),
                recommended_param=_str(r["recommended_param"]),
                recommended_delta=_float(r["recommended_delta"]),
                recommended_rationale=_str(r["recommended_rationale"]),
                brewed_at=_datetime(r["brewed_at"]) or datetime.now(timezone.utc),
            ))
        session.commit()
        print(f"  brews:    {len(rows)}")

        # 7. Deltas
        rows = read_csv(src / "deltas.csv")
        for r in rows:
            session.add(Delta(
                id=_int(r["id"]),
                from_recipe_id=_int(r["from_recipe_id"]),
                to_recipe_id=_int(r["to_recipe_id"]),
                changed_param=r["changed_param"],
                delta_amount=float(r["delta_amount"]),
                rationale=_str(r["rationale"]),
                created_at=_datetime(r["created_at"]) or datetime.now(timezone.utc),
            ))
        session.commit()
        print(f"  deltas:   {len(rows)}")

    print("Done.")


if __name__ == "__main__":
    main()
