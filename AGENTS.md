# AGENTS.md — Context for LLM-guided editing

This file is written for future Claude (or other LLM) sessions, and for human contributors. It captures design decisions, known tricky areas, and conventions that are not obvious from reading the code alone.

---

## What this project is

A personal coffee recipe tracker used primarily on a Kindle browser and desktop. The core workflow is:

1. You buy a bag of coffee beans
2. You brew it, logging tasting notes after each cup
3. Based on those notes, you recommend what to change next time
4. You create a recipe variation (exactly one parameter changes)
5. Repeat until you dial in the recipe

The app is used during actual brewing sessions — UI must be legible on e-ink / small screens and interactions must be minimal.

---

## Design philosophy

**Minimal dependencies, minimal JavaScript.** The stack is FastAPI + SQLite + Jinja2 + htmx. No JS framework. The only interactivity is htmx partial loading (the brew page recipe panel and its named-recipe picker), the searchable bag-picker modal on the brew page, the ± sign button on signed amounts, the bag-photo upload (`static/bean_art.js`, which shrinks the photo and picks its accent colour in the browser so the server needs no imaging library), the step editor (`static/step_editor.js`, layered over a plain textarea), the brew-mode timer (`brew.html`, ES5 so the Kindle's old browser doesn't choke; without JavaScript the page is still the full recipe), and a handful of inline `<script>` snippets for show/hide logic. New features should follow this pattern — reach for htmx before reaching for JS, and avoid adding npm/bundling.

**Server-rendered, not API-first.** Routes return HTML, not JSON. Forms POST to endpoints that redirect. This keeps the Kindle-compatibility high and the codebase small.

**One-parameter delta rule.** This is the core intellectual constraint of the app. Each recipe variation must change exactly one of: `dose_g`, `water_ml`, `temp_c`, `grind_size`, `recipe_text`. This is enforced in `crud.validate_one_parameter_delta` and exists so that the effect of any change is unambiguous. Do not relax this constraint without the user's explicit instruction.

**Recipe = definition, Brew = instance.** A `Recipe` is a parameter snapshot (dose, water, temp, grind). A `Brew` is a single cup pulled using that recipe, linked to a specific physical bag. Tasting notes live on `Brew`, not `Recipe`. This distinction is central — conflating them causes quantity tracking to break.

**RecipeLine = named recipe, Recipe = one version of it.** In the UI a "recipe" ("Default", "2 cup", "Coffee Chronicler") is a `RecipeLine`; each `Recipe` row is one version in that line's chain (`previous_recipe_id`). A bean/brewer/grinder combination can have several lines, each with its own versions, brews, deltas, and recommendations. The current version of a line is its newest `Recipe` by `created_at`. A variation always stays in its parent's line (the server takes `line_id` from the parent, never from the form), and the one-parameter rule compares it with that parent only. A recipe with no parent starts a new line: the first for a combination may be unnamed ("Default"), later ones need a name unique within the combination. When no line is chosen, the brew page opens the combination's most recently used line (newest version or brew) — with a single line this is exactly the old "newest recipe for the combination" behaviour.

**A method is text, in a standard format or free.** `Recipe.recipe_text` is always plain text; there is no schema for steps, so the one-parameter rule, versions and sharing treat both alike. The step editor (`static/step_editor.js`) writes the standard format: optional `Prep: ...` lines, then `m:ss — action` with an optional `(to 200g)`. `app/brew.py` parses it exactly and falls back to its best-effort reading for free text, which every recipe from before the editor still is and must keep working. A recipe is only converted when someone uses "Tidy into steps" (`/lines/{id}/tidy`), which proposes steps with `suggest_steps`, flags its guesses, and saves a new version with a `recipe_text` delta whose rationale is `brew.TIDY_RATIONALE`. That version logs no brew, and the panel keeps showing the brews and recommendation of the version it was tidied from.

**Bean = type, BeanBag = physical bag.** `Bean` is the coffee variety (Ethiopia Yirgacheffe, etc.). `BeanBag` is a specific purchase of that variety, with its own roast date, quantity, and freeze status. You can have multiple bags of the same bean. Recipe history is shared across bags of the same bean (named recipes are keyed by `bean_id + brewer_id + grinder_id`, not by bag).

**Two locks: a site password, then personal accounts.** Caddy's basic auth keeps the open internet out entirely (one shared login for friends; see "Deploying to prod"). Behind it, each person signs in with their own password on `/select-user`: `app/auth.py` hashes passwords with scrypt, and a random session cookie is stored only as a hash in `usersession`. Beans, brewers, and grinders are owned by a user (`user_id`); bags, recipes, lines, brews, and deltas inherit ownership through their bean. **Every route that takes an ID must load it with `_owned(session, user, Model, id)`**, which treats someone else's row as a 404; `tests/test_accounts.py` attacks each route as a second user, and a safety-net test fails if any new route works without a session. Only the admin (`is_admin`, the first user) can create, reset, or delete accounts; deleting also needs the admin's own password. New accounts and resets get a generated temporary password that must be changed at first sign-in.

**Lightweight migrations only.** There is no alembic. `db.run_migrations()` (called on startup, by `scripts/migrate.py`, and by the export/import scripts) first creates missing *tables* via `SQLModel.metadata.create_all`, then applies additive `ALTER TABLE ... ADD COLUMN` statements for columns added after the DB was first created, seeds user 1 if the `user` table is empty, assigns ownerless beans/brewers/grinders to user 1, (`_migrate_recipe_lines`) puts every recipe without a `line_id` into its combination's "Default" line, (`_migrate_brew_ratings`) adds `brew.rating`, and (`_migrate_bean_art`) adds `bean.accent_color`, `bean.mesh_colors` and `bean.image_version`. Every step is idempotent and must stay so — it runs on every startup and on every deploy. The older steps use try/except around `ALTER TABLE`; new steps should check `PRAGMA table_info` (`db._columns`) instead, so real errors aren't swallowed. For a new nullable or defaulted column, add a step there. `tests/test_reference_parity.py` checks every step against real data: existing rows unchanged, idempotent, same answers as before. For anything non-additive (renames, type changes, dropped columns), use the export → drop → import cycle (`scripts/export.py`, `scripts/drop_tables.py`, `scripts/import.py`). If the app grows, `alembic` is the right next step.

---

## Data model

```
User                          (password_hash, is_admin, must_change_password)
├── sessions: UserSession     ← one per signed-in browser; only a hash of the cookie's token
├── beans: List[Bean]
├── brewers: List[Brewer]
└── grinders: List[Grinder]

Bean                          (user_id → User; accent_color, mesh_colors, image_version)
├── bags: List[BeanBag]
└── recipes: List[Recipe]

BeanImage                     ← the bag photo, one per bean (bean_id is the key)
└── data: bytes               ← JPEG; no relationship from Bean, so loading beans never loads it

BeanBag
├── bean: Bean
└── brews: List[Brew]         ← quantity tracked via brews, not directly

Brewer                        (user_id → User)
└── recipes: List[Recipe]

Grinder                       (user_id → User)
└── recipes: List[Recipe]

RecipeLine                    ← a named recipe ("Default", "2 cup")
├── bean_id, brewer_id, grinder_id
└── recipes: List[Recipe]     ← its versions

Recipe                        ← one version
├── line: RecipeLine
├── bean: Bean                (same combination as its line)
├── brewer: Brewer
├── grinder: Grinder
├── previous_recipe_id → Recipe (same line)
└── brews: List[Brew]

Brew                          (rating: 1-5 or None)
├── recipe: Recipe
└── bag: BeanBag

PlannedBrew                   ← "scheduled brew"; at most one per user
├── user_id → User
├── bag_id → BeanBag
├── brewer_id → Brewer
├── grinder_id → Grinder
└── line_id → RecipeLine      (None = the combination's default line)

Delta
├── from_recipe_id → Recipe
└── to_recipe_id → Recipe
```

**PlannedBrew:** created from the brew page ("Plan for next time") or the browse page ("Schedule next brew"). `crud.create_plan` replaces any existing plan for that user. When a plan exists, the home page renders the planned recipe first with "Log a brew" open; logging a brew or saving a variation with `planned_brew_id` deletes the plan. Deleting a bag, brewer, grinder, or named recipe also deletes plans that reference it. Plans record the named recipe (`line_id`); the browse form offers every named recipe for the bean and `/plan` takes the brewer and grinder from it unless they are chosen explicitly. A plan with no `line_id` means "whichever line is the default when opened" (a bean with no recipes yet, or gear that matches none of the chosen recipe's). `/plan` drops a `line_id` that doesn't belong to the bag's bean or the submitted gear. `is_current_plan` is computed in `main._latest_recipe_context`, not in the template.

**Bag photos:** one per `Bean` (artwork belongs to the coffee; re-buys share it), stored in the database so backups, deploys and rollbacks cover it. `image_version` says one exists and is the `?v=` on its URL, so templates never touch the bytes. It is a timestamp, not a counter: the image is cached forever, so a version must never repeat after a remove and re-add. The upload also saves `accent_color` and `mesh_colors` (four `#rrggbb`, one per corner of the gradient), which "Edit colours" (`POST /beans/{id}/colors`) can change by hand without touching the photo. The upload route only accepts JPEG bytes under `MAX_BEAN_IMAGE_BYTES`; browsers convert and shrink first. Do not add an imaging library for this: `deploy.sh` runs `pip install -r requirements.txt` when that file changes, which would re-pin prod's packages, and a failed deploy's rollback does not undo that.

**Quantity formula:**
```
remaining_g = bag.initial_quantity_g − Σ(recipe.dose_g for each Brew linked to this bag)
```
This is computed in `crud.get_remaining_quantity`. It joins through `Brew → Recipe` to get `dose_g`. Do not move `bag_id` back onto `Recipe` — it would break the ability to use different bags with the same recipe across sessions.

**Delta fields:**
- `changed_param`: one of `dose_g`, `water_ml`, `temp_c`, `grind_size`, `recipe_text`
- `delta_amount`: float, stored as `0.0` for `recipe_text` changes (no meaningful numeric value)
- `rationale`: free text explaining why

**Brew recommendation fields:**
- `recommended_param`, `recommended_delta` (Optional[float]), `recommended_rationale`
- These surface in the brew page as an amber "Recommended next" banner and pre-populate the "Create variation" form via the `applyRecommendation()` JS function
- Recommendations, like everything else in history, are per named recipe: the banner comes from the newest brew of the current line's latest version

---

## Critical implementation gotchas

### 1. DetachedInstanceError — always return TemplateResponse inside `with Session()`

SQLModel uses lazy loading. If you access a relationship (e.g. `bag.bean.name`, `brew.recipe.dose_g`) after the session closes, you get:

```
sqlalchemy.orm.exc.DetachedInstanceError: Parent instance is not bound to a Session
```

**The fix:** return `templates.TemplateResponse(...)` *inside* the `with Session(db.engine) as session:` block, not after it. Every route in `main.py` follows this pattern. If you add a new route, do not pull the return outside the `with` block even though it looks cleaner.

### 2. `# type: ignore` comments in crud.py are intentional

SQLModel/Pyright cannot resolve `.desc()` on datetime columns or `.join()` with SQLAlchemy column comparisons. These are annotated with `# type: ignore[union-attr]` and `# type: ignore[arg-type]`. Do not remove them — they suppress false positives, not real errors.

### 3. The variation form targets `#variation-form` by ID

The brew page has multiple `.stacked-form` elements. The `applyRecommendation()` JS function uses `document.getElementById('variation-form')` — not `document.querySelector('.stacked-form')`, which would grab the wrong form. This was a bug that was fixed. If the variation form is restructured, keep the `id="variation-form"` attribute.

### 4. Jinja2 inside `<script>` blocks breaks the IDE, not the runtime

The VS Code JS parser reports errors on `{% if rec %}` and `{{ value }}` inside `<script>` tags. This is a tooling limitation, not a real error. The convention in this codebase is to avoid Jinja2 inside script blocks entirely — instead, embed template data in `data-*` attributes on a hidden element and read them with `dataset` in JS. See `latest_recipe.html` (`#rec-data`) for the established pattern.

### 5. `textarea` needs explicit CSS to behave

The global CSS rule `input, select, button { width: 100% }` originally omitted `textarea`. This caused textareas to appear inline next to their label text and not stretch to full width. The fix (`textarea { display: block; width: 100%; }`) is in `styles.css`. When adding new textareas, use a separate `<label>` element above the `<textarea>` — do not nest the `<textarea>` inside the label text node.

### 6. Checkbox fields for booleans in forms

FastAPI's `bool = Form(...)` does not parse HTML checkbox values correctly by default — an unchecked checkbox sends nothing, a checked one sends `"true"` (a string). The `is_frozen` field in `/bags` works around this. If you add more boolean form fields, test the unchecked case explicitly.

### 7. Schema changes must also update export/import

`scripts/export.py` and `scripts/import.py` list every column by hand. When you add a model or column, add it to both (import should read new columns with `r.get(...)` so older snapshots still load), then run `.venv/bin/pytest tests/`. The round-trip test copies `data/coffee.db`, exports it, imports into a fresh DB, and asserts every table is row-for-row identical — it will fail if a column is dropped. Import's `_str` deliberately does **not** strip whitespace; several real notes have trailing whitespace/newlines. Add the new table to `TABLES` in `tests/test_export_import.py`.

### 8. Test against prod data before deploying

Every test that uses a reference DB reads `COFFEE_REFERENCE_DB` (default `data/coffee.db`) and only ever works on a copy made with the sqlite backup API. Prod has more and messier data than the local DB; `scripts/deploy.sh` runs the suite against a fresh prod backup automatically, but run it yourself while developing a schema change: `COFFEE_REFERENCE_DB=/path/to/prod.db .venv/bin/pytest tests/`.

Scripts that run as their own process (like `scripts/migrate.py`) only see the models they import. `db.run_migrations()` therefore creates missing tables itself; keep it that way. `tests/test_migrate_script.py` runs the script as a subprocess (with `COFFEE_DB` pointing at a copy) for exactly this reason.

### 9. Routes that need a user call `_require_user`, and IDs go through `_owned`

`_require_user(request, session)` raises `_redirect_to_select`, which the `_redirect_to_select_handler` exception handler turns into a redirect to `/select-user` (and clears a stale session cookie). Someone on a temporary password is sent to `/account` first. Tests sign in with `app.sign_in(user_id)`. Use it in any page or create route that needs the current user; list queries in `crud` take `user_id` and filter on it.

Keep it an `@app.exception_handler`. It used to be an `@app.middleware("http")` that caught the exception; under prod's starlette 0.46 that still sent the redirect but then re-raised, logging a traceback on every redirect (and failing the first deploy's on-VPS tests). Avoid `BaseHTTPMiddleware` for control flow in general.

---

## Deploying to prod

Prod is a VPS (`root@168.144.126.15`, Ubuntu): systemd unit `coffee.service` runs uvicorn on 127.0.0.1:8000 from a git checkout at `/root/coffee-recipe-tracker`, behind Caddy. The live database is `data/coffee.db` in that checkout and is **not** tracked by git (never commit a database; prod's data and the local DB have diverged and the local one must never reach prod). Code moves by `git merge --ff-only` from GitHub; data only changes in place via migrations.

From your Mac, with `main` committed and pushed: `scripts/deploy.sh`. It backs up prod, copies the backup to `data/backups/`, runs the tests against it locally, then on the VPS (`scripts/remote/ship.sh`): stops the app, copies the database, fast-forwards, runs the tests again with prod's own packages, runs `scripts/migrate.py`, starts the app. Any failure there restores the copy and the previous commit automatically. `scripts/remote/verify.sh` then checks every page for every user (with throwaway sessions it removes straight after) and that no pre-deploy row changed. `scripts/rollback.sh` undoes the last deploy (keeping the current database aside as `*-before-rollback.db`). The last deploy (previous commit, backup path) is recorded in `/root/backups/last-deploy`; a rollback renames it to `last-deploy.rolled-back-<stamp>`.

- Prod's venv was not installed from `requirements.txt` and has different versions (e.g. starlette 0.46 vs 0.52). Deploy only runs `pip install` when `requirements.txt` changed, and its on-VPS test run is what catches version problems.
- One-off data corrections go in `DATA_FIXES` in `scripts/migrate.py`, each guarded to match exactly the bad row (so it is a no-op elsewhere and on re-runs). Allow-list the row in `verify.sh` too, which otherwise flags any changed pre-deploy row.
- The first deploy of accounts leaves everyone without a password until `scripts/set_password.py 1` is run on the VPS for the admin (`ssh -t`, it prompts); the admin then uses Manage for everyone else. A rollback restores the pre-accounts database, so passwords set since are lost, but Caddy still guards the site.
- `scripts/change_gate_password.sh` replaces Caddy's logins with one shared login. It prompts on your own terminal, so never ask for or pass that password through chat.
- The root crontab's nightly backup (`sqlite3 ... .backup`) has never worked: the VPS has no `sqlite3` CLI. Replace it with `scripts/backup.py data/coffee.db /root/backups --keep-days 60` (needs the user's OK — it changes prod config).
- To rehearse without touching prod, `COFFEE_HOST=local` plus `APP`, `BACKUPS`, `URL`, `START_CMD`, `STOP_CMD` run the VPS side on your machine against a local checkout.

---

## Sharing recipes

"Share as text" / "Download .md" on the recipe card serve `app/export.py`'s Markdown for the current named recipe. It stays behind Caddy's basic auth like every other route; nothing is public.

- **Privacy is a whitelist.** `export.py` reads only bean name/origin/roast/flavour notes, brewer and grinder names, the latest version's parameters and method, and the line's deltas with their rationales. Tasting notes, ratings, recommendations, bags/quantities, `Bean.notes`, plans, and user names must never appear; `tests/test_export_recipe.py` plants marker strings in all of them. Keep new fields out unless they are clearly meant for friends.
- **History shows real values** (`before → after` read from the two versions), never `Delta.delta_amount`, which is typed by hand and can be wrong (prod change #22 records −1 for 21 → 19).
- "Default" is not shown as a recipe name; grind is always printed with the grinder's name, since a setting means nothing on another grinder.
- A public link (`/s/<token>`) was planned as a second step: a `RecipeShare` table with revocable random tokens, a self-contained read-only page reusing `export.py`'s data, and a Caddy `handle /s/*` placed before `basicauth`. Not built; it needs the user's go-ahead for the Caddy change.

---

## File map

| File | Role |
|---|---|
| `app/models.py` | SQLModel ORM definitions. All schema changes start here. |
| `app/crud.py` | All DB reads and writes. No business logic in routes — it belongs here. |
| `app/auth.py` | Password hashing (scrypt, stdlib only) and session tokens. |
| `app/brew.py` | The step format (`is_standard`, `needs_tidy`, `step_editor_data`), `parse_steps` for brew mode, and `suggest_steps` for tidying. For free text it picks out `m:ss` times (skipping ratios like "1:16" and the end of ranges like "3:30–4:00"). Server-side so it's tested in pytest; the page's script only keeps time. |
| `app/theme.py` | Bean colours → `--accent`, `--accent-soft`, `--mesh-strip` and `--mesh-strong` CSS variables (the `bean_theme` filter, applied to a bean). Validates the colours and guarantees readable contrast. |
| `app/export.py` | Named recipe → shareable Markdown (`GET /lines/{id}/export.md`, `?download=1` for a file). Whitelists what it shows; see "Sharing recipes". |
| `app/db.py` | Engine (path overridable with `COFFEE_DB`), session factory, `create_db_and_tables()`, `run_migrations()` (creates missing tables, additive column adds, user seeding, Default named-recipe backfill). |
| `app/main.py` | FastAPI routes. Thin — calls crud, returns TemplateResponse. Also user-cookie helpers, the morning banner's pixel art and quotes. |
| `app/templates/base.html` | Nav bar (with current user link), page shell, `toggleForm()` and `flipSign()` JS helpers. |
| `app/templates/select_user.html` | Sign-in page: pick your name, enter your password. |
| `app/templates/account.html` | Change your password, sign out; also the forced first-sign-in password step. |
| `app/templates/temporary_password.html` | Shows a new temporary password once, to the admin. |
| `app/templates/brew.html` | Brew mode (`GET /lines/{id}/brew?bag_id=&plan_id=`): large parameters, timer (current step above the clock, so nothing needs scrolling mid-brew; no site header and compact tiles so everything down to Start fits one phone screen, and the page must not scroll itself), steps with `data-times`, and the log form when the bag belongs to this bean. `plan_id` is only honoured if it is the current user's plan for this bag/brewer/grinder/line, so logging from here clears the schedule like the panel does. |
| `app/templates/partials/log_brew_form.html` | The "Log a brew" form, included by the recipe panel and brew mode with `log_recipe_id` / `log_bag_id` / `log_plan_id`. One per page: it uses fixed ids (`log-notes`, `rec-delta-row`). |
| `app/templates/partials/star_input.html` | 1-5 star picker, CSS only (reversed radios). Expects `star_name`; used by the log form (`rating`) and variation form (`brew_rating`). |
| `app/templates/partials/bean_art_form.html` | Bag photo controls on the manage page (add/retake, remove, edit colours); `static/bean_art.js` does the upload and "Reset to photo". |
| `app/templates/partials/recipe_text_field.html` | The method field: a real `<textarea name="recipe_text">` that `static/step_editor.js` covers with rows when the text is standard or empty. It stays the form field, so no JavaScript (Kindle) or free text just means the plain box. The script only rewrites it after an actual edit, so an untouched recipe can't change. |
| `app/templates/tidy_recipe.html` | "Tidy into steps": the current method, suggested rows, save as a new version. |
| `app/templates/index.html` | Brew page. Morning banner, bag-picker modal, picker form with htmx (`hx-get="/recipes/latest"`). Shows the scheduled brew first if one exists. |
| `app/templates/partials/latest_recipe.html` | htmx partial. Named-recipe picker (only with 2+ lines), recipe display, plan-for-next-time form, recommendation banner, and collapsed sections: log a brew, create variation, new named recipe, rename/delete the current one. |
| `app/templates/manage.html` | Add/edit/delete beans+bags, brewers, grinders, users. Inline edit forms toggled by `toggleForm()`. Bag rows have Edit/Done/Delete actions. Beans whose bags are all completed are listed separately as archived. |
| `app/templates/browse.html` | Bean overview with bag inventory, collapsible history, and "Schedule next brew" form. |
| `app/static/styles.css` | All styles. No external CSS framework. |
| `scripts/export.py` | Exports every table (incl. users, named recipes, planned brews, owner `user_id`s) to CSV. Brings the DB up to the current schema first. Default `export/`, or pass a directory. `export_all(engine, out_dir)` is importable. |
| `scripts/import.py` | Restores from a CSV snapshot. Two-pass recipe insert for `previous_recipe_id`. Requires every table to be empty. Also accepts older snapshots (no `users.csv` / `planned_brews.csv` / `recipe_lines.csv`) and fills the gaps via `run_migrations`. `import_all(engine, src_dir)` is importable. |
| `scripts/drop_tables.py` | Drops and recreates all tables after confirmation prompt. |
| `scripts/set_password.py` | Set a password from the server's terminal; needed for the admin's first sign-in. |
| `scripts/change_gate_password.sh` | Change Caddy's site-wide login (with `scripts/remote/set_gate_login.py`). |
| `scripts/migrate.py` | Schema migrations + guarded one-off data fixes + sanity checks; exits non-zero on problems. Run by deploy with the app stopped. |
| `scripts/backup.py` | Consistent SQLite backup with the stdlib only (the VPS has no `sqlite3` CLI). Must not import the app: deploy streams it over ssh. |
| `scripts/deploy.sh`, `scripts/rollback.sh` | Run on your Mac. See "Deploying to prod". |
| `scripts/remote/*.sh` | `ship.sh`, `verify.sh`, `rollback.sh`: the VPS side, streamed over ssh by the two scripts above. |
| `tests/conftest.py` | `app_on` fixture: runs the real app (startup migrations included) against a throwaway DB, empty or copied from a reference DB. |
| `tests/test_flows.py` | Behaviour of the core flows through HTTP: baseline → brews → variations, one-parameter rule, scheduling, browse, delete cascades. Written before named recipes; must keep passing unchanged. |
| `tests/test_named_recipes.py` | Several named recipes per combination: separate histories, picker, default choice, scheduling, rename/delete. |
| `tests/test_brew_mode.py` | Step-time parsing (real prod method texts), the brew page, logging from it (incl. a scheduled brew), bag/plan validation. |
| `tests/test_accounts.py` | Sign-in, passwords, admin tools, one user attacking another's data on every route, and sign-in required everywhere. |
| `tests/test_step_editor.py` | The step format, suggestions from real recipes, tidy flow, and free text staying exactly as it was. |
| `tests/test_ratings.py` | Star ratings: logging, validation, display, and staying out of shared recipes. |
| `tests/test_bean_art.py` | Bag photo upload/serve/replace/remove and validation, per-bean colours and their contrast. Colour picking itself runs in the browser and is checked by hand. |
| `tests/test_export_recipe.py` | Recipe export: exact output, no personal data (marker strings planted in every private field), per-line history, CRLF normalisation, download headers. |
| `tests/test_reference_parity.py` | On a copy of the reference DB: every combination shows the same latest recipe / brews / deltas as the original rules (computed in plain SQL), every page renders, existing rows untouched, migrations idempotent. |
| `tests/test_export_import.py` | Export→import round-trip against a temp copy of the reference DB, plus named recipes, legacy-snapshot and non-empty-DB checks. |
| `tests/test_migrate_script.py` | Runs `scripts/migrate.py` as a subprocess on a copy of the reference DB (idempotent, no unassigned recipes) and checks the data fix only touches the known bad row. |
| `data/backups/` | Dated copies of `coffee.db`, plus `prod-*-predeploy.db` copies pulled down by deploy (not tracked in git). |
| `export/` | A committed pre-multi-user CSV snapshot; the tests use it as the legacy-format fixture. |

---

## htmx usage

Only one htmx interaction exists: the brew page picker (`index.html`). The bag is chosen in a JS modal that writes a hidden `bag_id` input and dispatches a `change` event; brewer and grinder are plain selects. When any of them changes, htmx fires a GET to `/recipes/latest?bag_id=&brewer_id=&grinder_id=` and swaps the response into `#latest-wing`.

The partial adds a second, nested interaction: when a combination has more than one named recipe it renders a "Recipe" `<select name="line_id">` whose form does the same GET with `hx-include="#picker-form"`, so the bag/brewer/grinder come along. Changing the bag, brewer, or grinder drops `line_id`, which resets to the default line.

The partial endpoint (`/recipes/latest`) handles the incomplete-selection case gracefully — if any of the three IDs are missing, it returns a prompt message instead of querying the DB.

If you add new htmx interactions, keep them similarly self-contained with graceful empty states.

---

## UI conventions

- **Collapsibles:** use `<details>/<summary>` — no JS needed, already styled with `.bean-block`, `.history-block` classes. The arrow indicator is a CSS `::before` pseudo-element that rotates on `[open]`.
- **Low stock:** rows with `remaining ≤ low_threshold_g` get class `low-stock` (amber background).
- **Per-bean colours:** set `style="{{ bean|bean_theme }}"` on a container, then use `var(--accent, <default>)` / `var(--accent-soft, <default>)` in CSS so beans without a photo keep the normal palette. `--mesh-strip` is the gradient border around a coffee's cards (a thin strip along the top in brew mode, which has enough going on); `--mesh-strong` frames the artwork. Never put a mesh behind text: it was tried as a card background and hurt readability.
- **Muted text:** class `.muted` for secondary/empty-state text.
- **Buttons:** default button is dark brown (`#6b3d2e`). Secondary actions use `.btn-secondary` (parchment `#f0e4d4`). The apply-recommendation button uses `.btn-apply-rec` (amber). Destructive actions add `.btn-danger`.
- **`hidden` needs help:** elements with a `display` rule (`textarea`, `.step-editor`) ignore the `hidden` attribute unless a `[hidden] { display: none }` rule matches them.
- **Phone width:** the page must never be wider than the screen, or iOS zooms everything out ("the recipe got tiny"). `.grid` uses `minmax(0, 1fr)` — never a bare `1fr`/auto column, which grows to its widest content and widens every card; rows of inputs + buttons need `flex-wrap`/`min-width: 0`; `.delta-table` scrolls inside its card under 600px. Check new UI at 375px wide (`document.documentElement.scrollWidth` must equal the viewport). The manage page is still too wide on phones.
- **Signed amounts:** iOS number keypads (`inputmode="decimal"`) have no minus key. Any input that can be negative goes in a `<span class="signed-input">` with a `<button type="button" class="btn-sign" onclick="flipSign(this)">±</button>` right after the input (`flipSign` flips the sign of its previous sibling).
- **Forms:** always use `.stacked-form` class. Labels go above inputs (separate `<label>` tag, not wrapping the input) for textareas. Inputs wrap labels for single-line fields — this is inconsistent and worth standardising if the forms grow.

---

## Edit/delete patterns

All entity management on the manage page (beans, bags, brewers, grinders) follows the same pattern (named recipes are renamed/deleted from the brew page instead):

**Inline edit forms:** Hidden `<div class="edit-form hidden" id="edit-<entity>-{{ id }}">` inside the row. `toggleForm(id)` in `base.html` flips the `.hidden` class. Edit button calls `toggleForm(...)` with `event.stopPropagation()` when inside a `<summary>` (to prevent `<details>` open/close).

**Delete with cascade:** Deletion order must respect FK constraints: Deltas → Brews → Recipes → PlannedBrews → RecipeLines → (Bags) → Bean. The crud functions handle this explicitly (SQLite does not enforce FK constraints by default), via the shared helpers `crud._delete_recipes` and `crud._delete_lines`. See `crud.delete_bean`, `crud.delete_brewer`, `crud.delete_grinder`, `crud.delete_line`, and `crud.delete_user` (which cascades through all of the user's beans, brewers, and grinders).

**Completed bags:** `BeanBag.is_completed = True` hides the bag from the brew-page picker (`crud.get_active_bags_for_user` excludes completed bags, and the `/` route also drops bags with nothing remaining). The bag remains in the database and still appears in the manage page (greyed out with `.row-completed`).

**Routes:** All edit/delete/complete routes are `POST` (HTML forms cannot `DELETE`). They redirect with `status_code=303`: to `/manage`, except the named-recipe routes (`/lines/{id}/rename`, `/lines/{id}/delete`), which redirect to `/`. Validation failures raise `HTTPException(400)` with a plain message.

**Confirm dialogs:** Delete buttons use `onsubmit="return confirm('...')"` to prevent accidental deletion.

---

## What has been intentionally left out

- **No email or self-service password reset.** The admin resets passwords. There is also no login rate limiting, because Caddy's password already keeps the open internet away; add both before ever removing it.
- **No CSRF tokens.** The session cookie is `SameSite=Lax`, which stops cross-site form posts, and the site is behind Caddy's password.
- **No alembic.** Additive columns go in `db.run_migrations()`; anything else uses export → `scripts/drop_tables.py` → import.
- **No unit tests for templates/CSS.** `tests/` covers the HTTP flows, data parity, and export/import; visual changes are checked by hand in a browser.
