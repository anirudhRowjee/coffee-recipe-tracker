# Coffee Recipe Tracker

A personal web app for tracking coffee recipes, brew sessions, and iterative improvements across different beans, brewers, and grinders.

Built with FastAPI + SQLite (via SQLModel) + htmx. No JavaScript frameworks — just server-rendered HTML with lightweight partial updates. Designed to be used mid-brew on a Kindle, phone, or desktop.

---

## Features

- **Beans & bags** — track coffee types separately from physical bags. Each bag has its own roast date, purchase date, and quantity. Running totals update automatically as you log brews.
- **Low stock alerts** — configurable per-bag threshold; highlighted in the UI when you're running low.
- **Frozen bag tracking** — mark bags as frozen with a freeze date, tracked separately from active bags.
- **Brew log** — log every brew with tasting notes against a specific bag and recipe.
- **Named recipes** — keep several independent recipes for the same bean + brewer + grinder (e.g. "Default", "2 cup", "Coffee Chronicler"), each with its own versions, brews, change history, and recommendations. A recipe picker appears on the brew page once there is more than one.
- **Recipe versioning** — each version is an immutable snapshot. Changing one parameter creates a new version linked to the previous one, within the same named recipe.
- **One-parameter delta rule** — each variation must change exactly one parameter (dose, water, temp, grind size, or recipe text), keeping the change history clean.
- **Recommended next change** — when logging a brew, optionally record what to try next time (e.g. grind −1). Surfaces prominently next session and can pre-fill the variation form. A **±** button next to each amount flips its sign, since phone number keypads (iOS) have no minus key.
- **Scheduled brews** — plan tomorrow's brew (bag, brewer, grinder, named recipe, note) from the brew or browse page; it opens first on the home page the next morning.
- **Accounts** — everyone signs in with their own password and sees only their own beans, brewers, grinders, and brews. The admin creates accounts with a temporary password, resets forgotten ones, and is the only person who can delete an account. A separate site-wide password keeps the open internet out.
- **Browse page** — see the latest recipe and bag inventory for every bean at a glance, with collapsible brew and change history per bean.
- **Full edit/delete UI** — edit or delete beans, bags, brewers, grinders, and named recipes; deletes cascade automatically. Mark a bag as completed when it's finished.
- **Star ratings** — rate each brew from 1 to 5 when you log it; stars appear in the brew history.
- **Bag artwork and colours** — add a photo of the bag from the Manage page. It appears on the brew, browse, and bag-picker views, an accent colour picked from it tints that coffee's buttons and highlights, and its cards get a gradient border of the bag's main colours (a thin strip along the top in brew mode). Retake the photo any time, or adjust the colours by hand under "Edit colours".
- **Welcome popup** — someone with no recipes yet gets a short one-time list of how to get started.
- **Share as image** — "Share as image" on the recipe card makes an Instagram-sized picture (4:5) of the recipe: bean, gear, every parameter and the method, framed in the bag's colours with its photo. Share it straight from your phone, or save it. Like the text export, it never includes tasting notes or ratings.
- **Lifetime savings** — the Manage page shows how much brewing at home has saved you: every cup you've logged, at ₹300 a café cup.
- **Brewing streak** — also on Manage: how many days in a row you've brewed, your longest run, and days brewed this month.
- **Step editor** — write a method as rows of time, action and target weight (type `140` for 1:40). Older free-text recipes keep working, and "Tidy into steps" proposes a conversion for you to correct; saving records it as a new version.
- **Brew mode** — "▶ Brew" on the recipe card opens the recipe in large type with a big timer. Times written in the method ("Swirl at 1:00", "0:40 — pour to 200g") become steps: the current one is highlighted, the next one counts down, and the phone beeps at each (not in silent mode) and stays awake while the timer runs. Stopping puts "Brewed 3:12" into the log form below it.
- **Brew animations** — for recipes in the step format, a small drawing beside the timer shows each step (bloom, pour, stir, swirl, plunge, the Switch's valve), with the water level following your pour-to weights and the bag's colour tinting the coffee. Untick "Animation" to hide it; each device remembers.
- **Share a recipe as text** — "Share as text" on the recipe card opens the current named recipe as plain Markdown to copy into a chat ("Download .md" saves a file): bean, gear, dose/water/ratio/temp, grind on which grinder, method, and how it got there. Tasting notes, bags, and other personal details are left out.
- **CSV backup & restore** — export all data to CSV, restore from a snapshot with `scripts/import.py`.

---

## Data model

```
User              — whoever is brewing (picked on /select-user, stored in a cookie)
└── Bean          — coffee type (name, origin, roast level, flavor notes)
    └── BeanBag   — physical bag (roast date, quantity, frozen status)
        └── Brew  — single brew session (tasting notes, recommendation)

Brewer            — brewing device (V60, Aeropress, espresso machine, etc.), per user
Grinder           — grinder, per user

RecipeLine        — a named recipe for one Bean + Brewer + Grinder ("Default", "2 cup")
└── Recipe        — one version: dose, water, temp, grind, recipe text
    └── Delta     — records what changed between two versions and why

PlannedBrew       — a scheduled brew: bag + brewer + grinder (+ named recipe), one per user
```

**Key relationships:**
- A `Brew` links a `Recipe` version to a `BeanBag` — this is how quantity is tracked (remaining = initial − Σ dose_g across all brews from that bag)
- Named recipes are keyed by bean+brewer+grinder, so history is preserved across bag changes
- A variation always stays in the named recipe it came from; a recipe with no parent starts a new one
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

Then set the first account's password, and open http://127.0.0.1:8000 to sign in:

```bash
python scripts/set_password.py 1
```

---

## Usage workflow

1. **Manage** (`/manage`) — add, edit, and delete beans, bags, brewers, grinders, and users
   - Add a bean first (coffee type), then add one or more bags to it
   - Each bag gets its own roast date and quantity
   - Open a bean and use "Add bag photo" to give it its artwork and colours; "Retake photo" and "Edit colours" change them later
   - Mark a bag as "Done" when it's finished — it disappears from the brew picker but stays in the history
   - Edit any field inline; delete cascades to all linked recipes, brews, and deltas
2. **Brew** (`/`) — select a bag + brewer + grinder to load the latest recipe
   - If no recipe exists yet, enter a baseline (optionally give it a name)
   - Log a brew with tasting notes after each cup
   - Optionally recommend what to change next time — use **±** for a negative amount
   - When ready to experiment, open "Create variation" — one parameter must change
   - To keep a separate recipe for the same coffee and gear, open "New named recipe"; switch between them with the "Recipe" picker
   - "Plan for next time" schedules this brew for tomorrow morning
   - "▶ Brew" opens brew mode: big numbers, a timer that follows the times in your method, and the log form
   - "Share as text" (under the recipe) gives you the recipe to paste to a friend
3. **Browse** (`/browse`) — overview of all beans, current bag inventory, latest recipes, history, and "Schedule next brew"

---

## Local network access (e.g. Kindle, phone)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Find your machine's local IP (`ipconfig getifaddr en0` on Mac, `hostname -I` on Linux) and open `http://<your-ip>:8000` from any device on the same network.

Keep the app behind a site-wide password or on a trusted network: accounts separate people from each other, but there is no login rate limiting.

---

## Project structure

```
app/
├── main.py          # FastAPI routes
├── models.py        # SQLModel ORM models (User, Bean, BeanBag, Brewer, Grinder,
│                    #   RecipeLine, Recipe, Brew, PlannedBrew, Delta)
├── crud.py          # All database read/write operations
├── export.py        # Named recipe → shareable Markdown (no personal data)
├── theme.py         # Bean accent colour → readable CSS variables
├── brew.py          # The step format, brew-mode steps, and tidy suggestions
├── db.py            # Engine setup, DB initialisation, startup migrations
├── auth.py          # Password hashing and session tokens
├── templates/
│   ├── base.html           # Nav bar, shell, small JS helpers (toggleForm, flipSign)
│   ├── brew.html           # Brew mode: large recipe, timer, log form
│   ├── select_user.html    # Sign in
│   ├── account.html        # Change your password, sign out
│   ├── index.html          # Brew page (bag + brewer + grinder picker, scheduled brew)
│   ├── browse.html         # Bean overview + scheduling
│   ├── manage.html         # Add/edit beans, bags, brewers, grinders, users
│   └── partials/
│       ├── latest_recipe.html  # htmx partial: recipe picker, recipe, brew log, variation form
│       ├── log_brew_form.html  # "Log a brew" form, shared by the recipe panel and brew mode
│       ├── star_input.html     # 1-5 star picker (no JavaScript)
│       └── bean_art_form.html  # Bag photo controls on the manage page
└── static/
    ├── styles.css
    ├── bean_art.js  # Shrinks bag photos and picks their accent colour in the browser
    ├── step_editor.js  # Step rows over the recipe text box
    └── htmx.min.js

scripts/
├── export.py        # Export all data to CSV (creates export/ directory)
├── import.py        # Restore from a CSV snapshot (tables must be empty)
├── drop_tables.py   # Wipe and recreate all tables (prompts for confirmation)
├── set_password.py  # Set an account's password from the terminal
├── change_gate_password.sh  # Change the site-wide Caddy login
├── migrate.py       # Bring a DB up to the current schema + one-off data fixes
├── backup.py        # Consistent SQLite backup using only the Python stdlib
├── deploy.sh        # Deploy main to the prod VPS (see "Deploying")
├── rollback.sh      # Undo the last deploy
└── remote/          # The VPS side of deploy/rollback, streamed over ssh

tests/               # pytest: HTTP flows, named recipes, recipe export, real-data
                     #   parity, brew mode, migrate script, export/import round-trip

data/
├── coffee.db        # SQLite database (created on first run; not tracked by git)
└── backups/         # Local backups, including prod backups pulled by deploy
```

**Important implementation note:** All `TemplateResponse` calls must be made *inside* the `with Session(db.engine) as session:` block. SQLModel uses lazy loading — accessing a relationship after the session closes raises `DetachedInstanceError`. See `AGENTS.md` for this and other gotchas.

---

## Database

The database is a single file at `data/coffee.db` (override with the `COFFEE_DB` environment variable). It can be opened directly with [DB Browser for SQLite](https://sqlitebrowser.org) or the `sqlite3` CLI. It is not tracked by git.

**Schema changes** are applied automatically on startup by `db.run_migrations()`: missing tables are created, new columns are added, and data is backfilled (e.g. every existing recipe is put into a "Default" named recipe). These steps are idempotent. Anything non-additive (renames, type changes) still needs the export → wipe → import cycle below.

**Back up the database (safe while the app is running):**
```bash
python scripts/backup.py data/coffee.db data/backups/   # data/backups/coffee-YYYY-MM-DD.db
```
`--keep-days N` also deletes `coffee-YYYY-MM-DD.db` files in that folder older than N days (meant for a nightly cron job).

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
Older snapshots (from before multi-user support or named recipes) still import; the missing pieces are filled in the same way app startup would.

**Wipe and reset the database:**
```bash
python scripts/drop_tables.py
```

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

-- Full brew history with tasting notes and named recipe
SELECT b.name, l.name AS recipe, bw.brewed_at, r.dose_g, r.grind_size, bw.notes,
       bw.recommended_param, bw.recommended_delta
FROM brew bw
JOIN recipe r ON r.id = bw.recipe_id
JOIN recipeline l ON l.id = r.line_id
JOIN bean b ON b.id = r.bean_id
ORDER BY bw.brewed_at DESC;

-- Change history for all beans
SELECT b.name, l.name AS recipe, d.changed_param, d.delta_amount, d.rationale, d.created_at
FROM delta d
JOIN recipe r ON r.id = d.to_recipe_id
JOIN recipeline l ON l.id = r.line_id
JOIN bean b ON b.id = r.bean_id
ORDER BY d.created_at DESC;
```

---

## Tests

```bash
.venv/bin/pytest tests/
```

The tests run the real app against throwaway databases; real database files are only ever read (copied with the SQLite backup API). Several tests check behaviour against a reference database — `data/coffee.db` by default. To check a change against production data, point them at a prod backup:

```bash
COFFEE_REFERENCE_DB=data/backups/prod-<stamp>-predeploy.db .venv/bin/pytest tests/
```

---

## Deploying

Prod runs on a VPS as the systemd service `coffee` (uvicorn behind Caddy) from a git checkout. Code reaches it through GitHub; the database there is never replaced, only migrated in place.

With `main` committed and pushed:

```bash
scripts/deploy.sh
```

This backs up prod and copies the backup to `data/backups/`, runs the tests against it locally, shows the commits and asks to confirm, then on the VPS: stops the app, takes another copy, fast-forwards the code, runs the tests with the server's packages, migrates, and starts the app. If any of those steps fails it restores the copy and the previous code automatically. Finally it checks every page for every user and that no existing row was lost.

To undo the last deploy (the database as it was then is restored; the current one is kept aside on the VPS):

```bash
scripts/rollback.sh
```

Details, and how to rehearse a deploy locally, are in `AGENTS.md` ("Deploying to prod").

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
