"""
Restore all data from a CSV snapshot produced by scripts/export.py.

Usage:
    python scripts/import.py                  # reads from export/
    python scripts/import.py path/to/snapshot # reads from a custom directory

The target database must be empty (all tables have zero rows). Run
scripts/drop_tables.py first if you need to wipe an existing database.

Import order respects foreign-key dependencies:
    User
    Bean → User
    Brewer → User
    Grinder → User
    BeanBag → Bean
    RecipeLine → Bean + Brewer + Grinder
    Recipe → RecipeLine (self-referential previous_recipe_id handled in two passes)
    Brew → Recipe + BeanBag
    PlannedBrew → User + BeanBag + Brewer + Grinder
    Delta → Recipe

Older snapshots still import: ones from before multi-user support have no
users.csv / planned_brews.csv / user_id columns, and ones from before named
recipes have no recipe_lines.csv / line_id columns. After loading, the app's
own migrations (db.run_migrations) fill the gaps exactly as app startup
would: user 1 is created and owns everything ownerless, and each
bean/brewer/grinder's recipes go into a "Default" named recipe.
"""

import base64
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select
from app import db
from app.models import User, Bean, BeanImage, BeanBag, Brewer, Grinder, RecipeLine, Recipe, Brew, BrewCurve, PlannedBrew, Delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(val: str | None) -> str | None:
    # Empty cells are None; anything else is kept verbatim (no stripping) so
    # notes and recipe text round-trip exactly.
    return val if val else None

def _int(val: str | None) -> int | None:
    v = (val or "").strip()
    return int(v) if v else None

def _float(val: str | None) -> float | None:
    v = (val or "").strip()
    return float(v) if v else None

def _date(val: str | None) -> date | None:
    v = (val or "").strip()
    if not v:
        return None
    # export writes date objects as YYYY-MM-DD
    return date.fromisoformat(v[:10])

def _datetime(val: str | None) -> datetime | None:
    v = (val or "").strip()
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

def _bool(val: str | None) -> bool:
    return (val or "").strip().lower() in ("true", "1", "yes")

def abort(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)

def read_csv(path: Path, required: bool = True) -> list[dict]:
    if not path.exists():
        if required:
            abort(f"{path} not found. Are you pointing at the right snapshot directory?")
        return []
    csv.field_size_limit(sys.maxsize)  # bean_images.csv holds whole photos
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Preflight check
# ---------------------------------------------------------------------------

def check_empty(session: Session) -> None:
    for model in [User, Bean, BeanImage, BeanBag, Brewer, Grinder, RecipeLine, Recipe, Brew, BrewCurve, PlannedBrew, Delta]:
        count = session.exec(select(func.count()).select_from(model)).one()
        if count:
            abort(
                f'Table "{model.__tablename__}" already has {count} row(s). '
                "Run scripts/drop_tables.py first, or point at an empty database."
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def import_all(engine: Engine, src: Path) -> None:
    if not src.is_dir():
        abort(f'Snapshot directory "{src}" does not exist.')

    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        check_empty(session)

        # 1. Users (absent in pre-multi-user snapshots)
        rows = read_csv(src / "users.csv", required=False)
        for r in rows:
            session.add(User(
                id=_int(r["id"]),
                name=r["name"],
                password_hash=_str(r.get("password_hash")),
                is_admin=_bool(r.get("is_admin")),
                must_change_password=_bool(r.get("must_change_password")),
                # older snapshots have neither: the defaults (animation on, live graph off)
                show_brew_animation=_bool(r["show_brew_animation"]) if r.get("show_brew_animation") else True,
                show_live_graph=_bool(r.get("show_live_graph")),
            ))
        session.commit()
        print(f"  users:    {len(rows)}")

        # 2. Beans
        rows = read_csv(src / "beans.csv")
        for r in rows:
            session.add(Bean(
                id=_int(r["id"]),
                user_id=_int(r.get("user_id")),
                name=r["name"],
                origin=_str(r["origin"]),
                roast_level=_str(r["roast_level"]),
                flavor_notes=_str(r["flavor_notes"]),
                notes=_str(r["notes"]),
                accent_color=_str(r.get("accent_color")),
                mesh_colors=_str(r.get("mesh_colors")),
                image_version=_int(r.get("image_version")),
            ))
        session.commit()
        print(f"  beans:    {len(rows)}")

        # Bag photos (absent in older snapshots)
        rows = read_csv(src / "bean_images.csv", required=False)
        for r in rows:
            session.add(BeanImage(
                bean_id=_int(r["bean_id"]),
                content_type=r["content_type"],
                data=base64.b64decode(r["data_base64"]),
            ))
        session.commit()
        print(f"  photos:   {len(rows)}")

        # 3. Brewers
        rows = read_csv(src / "brewers.csv")
        for r in rows:
            session.add(Brewer(
                id=_int(r["id"]),
                user_id=_int(r.get("user_id")),
                name=r["name"],
                method=_str(r["method"]),
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  brewers:  {len(rows)}")

        # 4. Grinders
        rows = read_csv(src / "grinders.csv")
        for r in rows:
            session.add(Grinder(
                id=_int(r["id"]),
                user_id=_int(r.get("user_id")),
                name=r["name"],
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  grinders: {len(rows)}")

        # 5. Bags
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
                thaw_date=_date(r.get("thaw_date")),
                is_completed=_bool(r.get("is_completed")),
                notes=_str(r["notes"]),
            ))
        session.commit()
        print(f"  bags:     {len(rows)}")

        # 6. Named recipes (absent in pre-named-recipe snapshots)
        rows = read_csv(src / "recipe_lines.csv", required=False)
        for r in rows:
            session.add(RecipeLine(
                id=_int(r["id"]),
                bean_id=_int(r["bean_id"]),
                brewer_id=_int(r["brewer_id"]),
                grinder_id=_int(r["grinder_id"]),
                name=r["name"],
                created_at=_datetime(r["created_at"]) or datetime.now(timezone.utc),
            ))
        session.commit()
        print(f"  lines:    {len(rows)}")

        # 7. Recipes — two passes to handle self-referential previous_recipe_id
        rows = read_csv(src / "recipes.csv")

        # Pass 1: insert all recipes without previous_recipe_id
        for r in rows:
            session.add(Recipe(
                id=_int(r["id"]),
                bean_id=_int(r["bean_id"]),
                brewer_id=_int(r["brewer_id"]),
                grinder_id=_int(r["grinder_id"]),
                line_id=_int(r.get("line_id")),
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

        # 8. Brews
        rows = read_csv(src / "brews.csv")
        for r in rows:
            session.add(Brew(
                id=_int(r["id"]),
                recipe_id=_int(r["recipe_id"]),
                bag_id=_int(r["bag_id"]),
                notes=_str(r["notes"]),
                rating=_int(r.get("rating")),
                recommended_param=_str(r["recommended_param"]),
                recommended_delta=_float(r["recommended_delta"]),
                recommended_rationale=_str(r["recommended_rationale"]),
                brewed_at=_datetime(r["brewed_at"]) or datetime.now(timezone.utc),
            ))
        session.commit()
        print(f"  brews:    {len(rows)}")

        # Scale curves (absent in older snapshots)
        rows = read_csv(src / "brew_curves.csv", required=False)
        for r in rows:
            session.add(BrewCurve(brew_id=_int(r["brew_id"]), samples=r["samples"]))
        session.commit()
        print(f"  curves:   {len(rows)}")

        # 9. Planned brews (absent in pre-multi-user snapshots)
        rows = read_csv(src / "planned_brews.csv", required=False)
        for r in rows:
            session.add(PlannedBrew(
                id=_int(r["id"]),
                user_id=_int(r["user_id"]),
                bag_id=_int(r["bag_id"]),
                brewer_id=_int(r["brewer_id"]),
                grinder_id=_int(r["grinder_id"]),
                line_id=_int(r.get("line_id")),
                notes=_str(r["notes"]),
                created_at=_datetime(r["created_at"]) or datetime.now(timezone.utc),
                suggested_param=_str(r.get("suggested_param")),
                suggested_delta=_float(r.get("suggested_delta")),
                suggested_rationale=_str(r.get("suggested_rationale")),
            ))
        session.commit()
        print(f"  planned:  {len(rows)}")

        # 10. Deltas
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

    # Fill in whatever an older snapshot lacks (owners, named recipes)
    db.run_migrations(engine)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("export")
    print(f"Importing from {src.resolve()}/")
    import_all(db.engine, src)
    print("Done.")


if __name__ == "__main__":
    main()
