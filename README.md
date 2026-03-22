# Coffee Recipe Tracker

A personal web app for tracking coffee recipes, brew sessions, and iterative improvements across different beans, brewers, and grinders.

Built with FastAPI + SQLite (via SQLModel) + htmx. No JavaScript frameworks — just server-rendered HTML with lightweight partial updates.

---

## Features

- **Beans & bags** — track coffee types separately from physical bags. Each bag has its own roast date, purchase date, and quantity. Running totals update automatically as you log brews.
- **Low stock alerts** — configurable per-bag threshold; highlighted in the UI when you're running low.
- **Frozen bag tracking** — mark bags as frozen with a freeze date, tracked separately from active bags.
- **Brew log** — log every brew with tasting notes against a specific bag and recipe.
- **Recipe versioning** — recipes are immutable snapshots. Changing one parameter creates a new recipe linked to the previous one.
- **One-parameter delta rule** — each variation must change exactly one parameter (dose, water, temp, grind size, or recipe text), keeping the change history clean.
- **Recommended next change** — when logging a brew, optionally record what to try next time. Surfaces prominently on your next session.
- **Browse page** — see the latest recipe and bag inventory for every bean at a glance, with collapsible brew and change history per bean.
- **Full edit/delete UI** — edit or delete beans, bags, brewers, and grinders directly from the Manage page; deletes cascade automatically. Mark a bag as completed when it's finished.
- **CSV backup & restore** — export all data to CSV, restore from a snapshot with `scripts/import.py`.

---

## Data model

```
Bean              — coffee type (name, origin, roast level, flavor notes)
└── BeanBag       — physical bag (roast date, quantity, frozen status)
    └── Brew      — single brew session (tasting notes, recommendation)

Brewer            — brewing device (V60, Aeropress, espresso machine, etc.)
Grinder           — grinder

Recipe            — parameter snapshot (dose, water, temp, grind, recipe text)
                    linked to Bean + Brewer + Grinder
└── Delta         — records what changed between two recipes and why
```

**Key relationships:**
- A `Brew` links a `Recipe` to a `BeanBag` — this is how quantity is tracked (remaining = initial − Σ dose_g across all brews from that bag)
- Recipes are looked up by bean+brewer+grinder, so history is preserved across bag changes
- A `Delta` is created whenever you save a variation, recording the changed parameter, amount, and rationale

---

## Setup

**Requirements:** Python 3.11+

```bash
# Clone and create a virtual environment
git clone <repo>
cd coffee
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialise the database (creates data/coffee.db)
python -m app.db

# Start the server
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

---

## Usage workflow

1. **Manage** (`/manage`) — add, edit, and delete beans, bags, brewers, and grinders
   - Add a bean first (coffee type), then add one or more bags to it
   - Each bag gets its own roast date and quantity
   - Mark a bag as "Done" when it's finished — it disappears from the brew picker but stays in the history
   - Edit any field inline; delete cascades to all linked recipes, brews, and deltas
2. **Brew** (`/`) — select a bag + brewer + grinder to load the latest recipe
   - If no recipe exists yet, enter a baseline
   - Log a brew with tasting notes after each cup
   - Optionally recommend what to change next time
   - When ready to experiment, open "Create variation" — one parameter must change
3. **Browse** (`/browse`) — overview of all beans, current bag inventory, latest recipes, and history

---

## Local network access (e.g. Kindle, phone)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Find your machine's local IP (`ipconfig getifaddr en0` on Mac, `hostname -I` on Linux) and open `http://<your-ip>:8000` from any device on the same network.

---

## Project structure

```
app/
├── main.py          # FastAPI routes
├── models.py        # SQLModel ORM models (Bean, BeanBag, Brewer, Grinder, Recipe, Brew, Delta)
├── crud.py          # All database read/write operations
├── db.py            # Engine setup, DB initialisation
├── templates/
│   ├── base.html           # Nav bar, shell
│   ├── index.html          # Brew page (bag + brewer + grinder picker)
│   ├── browse.html         # Bean overview
│   ├── manage.html         # Add/view beans, bags, brewers, grinders
│   └── partials/
│       └── latest_recipe.html  # htmx partial: recipe, brew log, variation form
└── static/
    ├── styles.css
    └── htmx.min.js

scripts/
├── export.py        # Export all data to CSV (creates export/ directory)
├── import.py        # Restore from a CSV snapshot (tables must be empty)
└── drop_tables.py   # Wipe and recreate all tables (prompts for confirmation)

data/
└── coffee.db        # SQLite database (created on first run)
```

**Important implementation note:** All `TemplateResponse` calls must be made *inside* the `with Session(db.engine) as session:` block. SQLModel uses lazy loading — accessing a relationship after the session closes raises `DetachedInstanceError`.

---

## Database

The database is a single file at `data/coffee.db`. It can be opened directly with [DB Browser for SQLite](https://sqlitebrowser.org) or the `sqlite3` CLI.

**Export all data to CSV:**
```bash
python scripts/export.py
```

**Restore from a CSV snapshot:**
```bash
python scripts/drop_tables.py   # wipe first
python scripts/import.py        # reads from export/ by default
# python scripts/import.py path/to/other/snapshot
```

**Wipe and reset the database:**
```bash
python scripts/drop_tables.py
```

**Schema changes** require recreating the database (there is no migration system). Always export first.

**Useful queries:**

```sql
-- Remaining quantity per bag
SELECT b.name, bg.id, bg.roast_date,
       bg.initial_quantity_g - COALESCE(SUM(r.dose_g), 0) AS remaining_g
FROM beanbag bg
JOIN bean b ON b.id = bg.bean_id
LEFT JOIN brew bw ON bw.bag_id = bg.id
LEFT JOIN recipe r ON r.id = bw.recipe_id
GROUP BY bg.id;

-- Full brew history with tasting notes
SELECT b.name, bw.brewed_at, r.dose_g, r.grind_size, bw.notes,
       bw.recommended_param, bw.recommended_delta
FROM brew bw
JOIN recipe r ON r.id = bw.recipe_id
JOIN bean b ON b.id = r.bean_id
ORDER BY bw.brewed_at DESC;

-- Change history for all beans
SELECT b.name, d.changed_param, d.delta_amount, d.rationale, d.created_at
FROM delta d
JOIN recipe r ON r.id = d.to_recipe_id
JOIN bean b ON b.id = r.bean_id
ORDER BY d.created_at DESC;
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | Web framework and routing |
| `uvicorn` | ASGI server |
| `sqlmodel` | ORM (SQLAlchemy + Pydantic, SQLite-backed) |
| `jinja2` | HTML templating |
| `python-multipart` | Form data parsing |
| `httpx` / `pytest` | Testing |
