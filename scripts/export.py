"""
Export all coffee data to CSV files in an export/ directory.
Usage: python scripts/export.py
"""
import csv
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select
from app import db
from app.models import Bean, BeanBag, Brewer, Grinder, Recipe, Brew, Delta
from app import crud

OUT = Path("export")
OUT.mkdir(exist_ok=True)

db.create_db_and_tables()

with Session(db.engine) as session:

    # Beans
    with open(OUT / "beans.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "origin", "roast_level", "flavor_notes", "notes"])
        for b in session.exec(select(Bean)).all():
            w.writerow([b.id, b.name, b.origin, b.roast_level, b.flavor_notes, b.notes])

    # Bags (with remaining quantity)
    with open(OUT / "bags.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "bean_id", "bean_name", "roast_date", "purchase_date",
                    "initial_quantity_g", "remaining_g", "low_threshold_g", "is_frozen", "frozen_date", "notes"])
        for bag in session.exec(select(BeanBag)).all():
            remaining = crud.get_remaining_quantity(session, bag)
            w.writerow([bag.id, bag.bean_id, bag.bean.name, bag.roast_date, bag.purchase_date,
                        bag.initial_quantity_g, round(remaining, 1), bag.low_threshold_g,
                        bag.is_frozen, bag.frozen_date, bag.notes])

    # Brewers
    with open(OUT / "brewers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "method", "notes"])
        for b in session.exec(select(Brewer)).all():
            w.writerow([b.id, b.name, b.method, b.notes])

    # Grinders
    with open(OUT / "grinders.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "notes"])
        for g in session.exec(select(Grinder)).all():
            w.writerow([g.id, g.name, g.notes])

    # Recipes
    with open(OUT / "recipes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "bean_id", "bean_name", "brewer_id", "brewer_name",
                    "grinder_id", "grinder_name", "dose_g", "water_ml", "temp_c",
                    "grind_size", "recipe_text", "previous_recipe_id", "created_at"])
        for r in session.exec(select(Recipe)).all():
            w.writerow([r.id, r.bean_id, r.bean.name, r.brewer_id, r.brewer.name,
                        r.grinder_id, r.grinder.name, r.dose_g, r.water_ml, r.temp_c,
                        r.grind_size, r.recipe_text, r.previous_recipe_id, r.created_at])

    # Brews (with tasting notes and recommendations)
    with open(OUT / "brews.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "recipe_id", "bean_name", "bag_id", "brewed_at", "notes",
                    "recommended_param", "recommended_delta", "recommended_rationale"])
        for b in session.exec(select(Brew)).all():
            w.writerow([b.id, b.recipe_id, b.recipe.bean.name, b.bag_id, b.brewed_at,
                        b.notes, b.recommended_param, b.recommended_delta, b.recommended_rationale])

    # Deltas (change history)
    with open(OUT / "deltas.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "from_recipe_id", "to_recipe_id", "bean_name",
                    "changed_param", "delta_amount", "rationale", "created_at"])
        for d in session.exec(select(Delta)).all():
            recipe = session.get(Recipe, d.to_recipe_id)
            w.writerow([d.id, d.from_recipe_id, d.to_recipe_id,
                        recipe.bean.name if recipe else "",
                        d.changed_param, d.delta_amount, d.rationale, d.created_at])

print(f"Exported to {OUT.resolve()}/")
for f in sorted(OUT.iterdir()):
    print(f"  {f.name}")
