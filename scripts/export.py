"""
Export all coffee data to CSV files in an export/ directory.

Usage:
    python scripts/export.py                  # writes to export/
    python scripts/export.py path/to/snapshot # writes to a custom directory

Restore with scripts/import.py.
"""
import base64
import csv
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select
from app import db
from app.models import User, Bean, BeanImage, BeanBag, Brewer, Grinder, RecipeLine, Recipe, Brew, BrewCurve, PlannedBrew, Delta
from app import crud


def export_all(engine: Engine, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # Same schema catch-up the app runs on startup, so an older DB exports cleanly
    SQLModel.metadata.create_all(engine)
    db.run_migrations(engine)

    with Session(engine) as session:

        # Users
        with open(out / "users.csv", "w", newline="") as f:
            w = csv.writer(f)
            # password hashes included so a restore keeps accounts working; signed-in sessions are not
            w.writerow(["id", "name", "password_hash", "is_admin", "must_change_password"])
            for u in session.exec(select(User).order_by(User.id)).all():
                w.writerow([u.id, u.name, u.password_hash, u.is_admin, u.must_change_password])

        # Beans
        with open(out / "beans.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "user_id", "name", "origin", "roast_level", "flavor_notes", "notes",
                        "accent_color", "mesh_colors", "image_version"])
            for b in session.exec(select(Bean).order_by(Bean.id)).all():
                w.writerow([b.id, b.user_id, b.name, b.origin, b.roast_level, b.flavor_notes, b.notes,
                            b.accent_color, b.mesh_colors, b.image_version])

        # Bag photos (base64, so a snapshot stays plain CSV)
        with open(out / "bean_images.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bean_id", "content_type", "data_base64"])
            for image in session.exec(select(BeanImage).order_by(BeanImage.bean_id)).all():
                w.writerow([image.bean_id, image.content_type, base64.b64encode(image.data).decode("ascii")])

        # Bags (with remaining quantity)
        with open(out / "bags.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "bean_id", "bean_name", "roast_date", "purchase_date",
                        "initial_quantity_g", "remaining_g", "low_threshold_g", "is_frozen", "frozen_date",
                        "thaw_date", "is_completed", "notes"])
            for bag in session.exec(select(BeanBag).order_by(BeanBag.id)).all():
                remaining = crud.get_remaining_quantity(session, bag)
                w.writerow([bag.id, bag.bean_id, bag.bean.name if bag.bean else "", bag.roast_date, bag.purchase_date,
                            bag.initial_quantity_g, round(remaining, 1), bag.low_threshold_g,
                            bag.is_frozen, bag.frozen_date, bag.thaw_date, bag.is_completed, bag.notes])

        # Brewers
        with open(out / "brewers.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "user_id", "name", "method", "notes"])
            for b in session.exec(select(Brewer).order_by(Brewer.id)).all():
                w.writerow([b.id, b.user_id, b.name, b.method, b.notes])

        # Grinders
        with open(out / "grinders.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "user_id", "name", "notes"])
            for g in session.exec(select(Grinder).order_by(Grinder.id)).all():
                w.writerow([g.id, g.user_id, g.name, g.notes])

        # Named recipes
        with open(out / "recipe_lines.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "bean_id", "brewer_id", "grinder_id", "name", "created_at"])
            for ln in session.exec(select(RecipeLine).order_by(RecipeLine.id)).all():
                w.writerow([ln.id, ln.bean_id, ln.brewer_id, ln.grinder_id, ln.name, ln.created_at])

        # Recipes (versions of a named recipe)
        with open(out / "recipes.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "bean_id", "bean_name", "brewer_id", "brewer_name",
                        "grinder_id", "grinder_name", "line_id", "line_name", "dose_g", "water_ml", "temp_c",
                        "grind_size", "recipe_text", "previous_recipe_id", "created_at"])
            for r in session.exec(select(Recipe).order_by(Recipe.id)).all():
                w.writerow([r.id, r.bean_id, r.bean.name if r.bean else "", r.brewer_id, r.brewer.name if r.brewer else "",
                            r.grinder_id, r.grinder.name if r.grinder else "", r.line_id, r.line.name if r.line else "",
                            r.dose_g, r.water_ml, r.temp_c,
                            r.grind_size, r.recipe_text, r.previous_recipe_id, r.created_at])

        # Brews (with tasting notes and recommendations)
        with open(out / "brews.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "recipe_id", "bean_name", "bag_id", "brewed_at", "notes", "rating",
                        "recommended_param", "recommended_delta", "recommended_rationale"])
            for b in session.exec(select(Brew).order_by(Brew.id)).all():
                bean_name = b.recipe.bean.name if b.recipe and b.recipe.bean else ""
                w.writerow([b.id, b.recipe_id, bean_name, b.bag_id, b.brewed_at,
                            b.notes, b.rating, b.recommended_param, b.recommended_delta, b.recommended_rationale])

        # Scale curves (brew mode's readings, JSON as stored)
        with open(out / "brew_curves.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["brew_id", "samples"])
            for c in session.exec(select(BrewCurve).order_by(BrewCurve.brew_id)).all():
                w.writerow([c.brew_id, c.samples])

        # Planned (scheduled) brews
        with open(out / "planned_brews.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "user_id", "bag_id", "brewer_id", "grinder_id", "line_id", "notes", "created_at"])
            for p in session.exec(select(PlannedBrew).order_by(PlannedBrew.id)).all():
                w.writerow([p.id, p.user_id, p.bag_id, p.brewer_id, p.grinder_id, p.line_id, p.notes, p.created_at])

        # Deltas (change history)
        with open(out / "deltas.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "from_recipe_id", "to_recipe_id", "bean_name",
                        "changed_param", "delta_amount", "rationale", "created_at"])
            for d in session.exec(select(Delta).order_by(Delta.id)).all():
                recipe = session.get(Recipe, d.to_recipe_id)
                w.writerow([d.id, d.from_recipe_id, d.to_recipe_id,
                            recipe.bean.name if recipe and recipe.bean else "",
                            d.changed_param, d.delta_amount, d.rationale, d.created_at])


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("export")
    export_all(db.engine, out)
    print(f"Exported to {out.resolve()}/")
    for f in sorted(out.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
