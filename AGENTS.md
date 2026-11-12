# AGENTS.md — Context for LLM-guided editing

This file is written for future Claude (or other LLM) sessions, and for human contributors. It captures design decisions, known tricky areas, and conventions that are not obvious from reading the code alone.

---

## What this project is

A personal coffee recipe tracker, used on an iPhone (in Bluefy, for the Bookoo scale) and an iPad in landscape, and shared with a few friends. The core workflow is:

1. You buy a bag of coffee beans
2. You brew it, logging tasting notes after each cup
3. Based on those notes, you recommend what to change next time
4. You create a recipe variation (exactly one parameter changes)
5. Repeat until you dial in the recipe

The app is used during actual brewing sessions, often by people who aren't its author, so it must be obvious what to do next. Phone and iPad come first: touch targets of 44 px or more, the main action at the bottom within thumb reach, taps over typing (steppers, chips, stars), and two columns on a landscape iPad. The Kindle is no longer a target (since 2026-11-12); pages may rely on JavaScript and modern WebKit (`<dialog>`, popovers).

---

## Design philosophy

**Minimal dependencies, plain JavaScript.** The stack is FastAPI + SQLite + Jinja2. No JS framework, no npm or bundling: each script is a small file in `static/`. The interactivity: the touch shell (`static/sheet.js`: `<dialog class="sheet">`, a bottom sheet on a phone and a centred panel on an iPad, opened by any `data-sheet="id"`), help (`static/tips.js`: "?" popovers and the first-visit tour), form checks (`static/forms.js`: inline messages, drafts, no double submit, steppers, word chips), Try a change (`static/change_recipe.js`), the log form's chips (`static/log_form.js`), the ± sign button on signed amounts, the bag-photo upload (`static/bean_art.js`, which shrinks the photo and picks its accent colour in the browser so the server needs no imaging library), the step editor (`static/step_editor.js`, layered over a plain textarea), the brew-mode timer (`brew.html`, ES5 so the Kindle's old browser doesn't choke; without JavaScript the page is still the full recipe), the brew-mode animation (`static/brew_animation.js`, drawn as SVG and moved by CSS keyframes; modern browsers only, the Kindle isn't a target for it), the Bookoo scale in brew mode (`static/scale.js`, Web Bluetooth; see "Bookoo scale"), and a handful of inline `<script>` snippets. Server-rendered pages still do the work: a sheet holds an ordinary form that POSTs and redirects. htmx is still loaded, but only `/recipes/latest` (the card on its own, used by the tests) remains of it.

**Server-rendered, not API-first.** Routes return HTML, not JSON. Forms POST to endpoints that redirect. This keeps the codebase small.

**One-parameter delta rule.** This is the core intellectual constraint of the app. Each recipe variation must change exactly one of: `dose_g`, `water_ml`, `temp_c`, `grind_size`, `recipe_text`. This is enforced in `crud.validate_one_parameter_delta` and exists so that the effect of any change is unambiguous. Do not relax this constraint without the user's explicit instruction. The UI makes it visible rather than an error: Try a change locks every tile but the one picked. The server takes `changed_param` and `delta_amount` from the values themselves (the form's own are ignored), so a delta can't disagree with its versions. There is no jumping back to an older version (the user decided against it): "Undo the last change" makes a new version with the newest version's one change put back, so every move stays a single change.

**Recipe = definition, Brew = instance.** A `Recipe` is a parameter snapshot (dose, water, temp, grind). A `Brew` is a single cup pulled using that recipe, linked to a specific physical bag. Tasting notes live on `Brew`, not `Recipe`. This distinction is central — conflating them causes quantity tracking to break.

**RecipeLine = named recipe, Recipe = one version of it.** In the UI a "recipe" ("Default", "2 cup", "Coffee Chronicler") is a `RecipeLine`; each `Recipe` row is one version in that line's chain (`previous_recipe_id`). A bean/brewer/grinder combination can have several lines, each with its own versions, brews, deltas, and recommendations. The current version of a line is its newest `Recipe` by `created_at`. A variation always stays in its parent's line (the server takes `line_id` from the parent, never from the form), and the one-parameter rule compares it with that parent only. A recipe with no parent starts a new line: the first for a combination may be unnamed ("Default"), later ones need a name unique within the combination. When no line is chosen, the brew page opens the combination's most recently used line (newest version or brew) — with a single line this is exactly the old "newest recipe for the combination" behaviour.

**A method is text, in a standard format or free.** `Recipe.recipe_text` is always plain text; there is no schema for steps, so the one-parameter rule, versions and sharing treat both alike. The step editor (`static/step_editor.js`) writes the standard format: optional `Prep: ...` lines, then `m:ss — action` with an optional `(to 200g)`. `app/brew.py` parses it exactly and falls back to its best-effort reading for free text, which every recipe from before the editor still is and must keep working. A recipe is only converted when someone uses "Tidy into steps" (`/lines/{id}/tidy`), which proposes steps with `suggest_steps`, flags its guesses, and saves a new version with a `recipe_text` delta whose rationale is `brew.TIDY_RATIONALE`. That version logs no brew, and the panel keeps showing the brews and recommendation of the version it was tidied from.

**Bean = type, BeanBag = physical bag.** `Bean` is the coffee variety (Ethiopia Yirgacheffe, etc.). `BeanBag` is a specific purchase of that variety, with its own roast date, quantity, and freeze status. You can have multiple bags of the same bean. Recipe history is shared across bags of the same bean (named recipes are keyed by `bean_id + brewer_id + grinder_id`, not by bag).

**Two locks: a site password, then personal accounts.** Caddy's basic auth keeps the open internet out entirely (one shared login for friends; see "Deploying to prod"). Behind it, each person signs in with their own password on `/select-user`: `app/auth.py` hashes passwords with scrypt, and a random session cookie is stored only as a hash in `usersession`. Beans, brewers, and grinders are owned by a user (`user_id`); bags, recipes, lines, brews, and deltas inherit ownership through their bean. **Every route that takes an ID must load it with `_owned(session, user, Model, id)`**, which treats someone else's row as a 404; `tests/test_accounts.py` attacks each route as a second user, and a safety-net test fails if any new route works without a session. Only the admin (`is_admin`, the first user) can create, reset, or delete accounts; deleting also needs the admin's own password. New accounts and resets get a generated temporary password that must be changed at first sign-in.

**Lightweight migrations only.** There is no alembic. `db.run_migrations()` (called on startup, by `scripts/migrate.py`, and by the export/import scripts) first creates missing *tables* via `SQLModel.metadata.create_all`, then applies additive `ALTER TABLE ... ADD COLUMN` statements for columns added after the DB was first created, seeds user 1 if the `user` table is empty, assigns ownerless beans/brewers/grinders to user 1, (`_migrate_recipe_lines`) puts every recipe without a `line_id` into its combination's "Default" line, (`_migrate_brew_ratings`) adds `brew.rating`, (`_migrate_bean_art`) adds `bean.accent_color`, `bean.mesh_colors` and `bean.image_version`, (`_migrate_brew_settings`) adds `user.show_brew_animation` (default 1) and `user.show_live_graph` (default 0), (`_migrate_plan_suggestion`) adds `plannedbrew.suggested_param`, `suggested_delta` and `suggested_rationale`, and (`_migrate_gear_archive`) adds `brewer.archived` and `grinder.archived` (default 0). Every step is idempotent and must stay so — it runs on every startup and on every deploy. The older steps use try/except around `ALTER TABLE`; new steps should check `PRAGMA table_info` (`db._columns`) instead, so real errors aren't swallowed. For a new nullable or defaulted column, add a step there. `tests/test_reference_parity.py` checks every step against real data: existing rows unchanged, idempotent, same answers as before. For anything non-additive (renames, type changes, dropped columns), use the export → drop → import cycle (`scripts/export.py`, `scripts/drop_tables.py`, `scripts/import.py`). If the app grows, `alembic` is the right next step.

**Animations are decided on the server and drawn on the page.** `brew.animation_data` reads a standard-format method and the brewer: which drawing (`brewer_shape`), every action a step names in the order written (`step_actions`, keyword rules, with "idle" for anything unfamiliar so a step is never shown wrongly), and a timeline of phases per step: several actions play in order, then the moving ones loop until the step ends. Water level, valve, swollen bed and cup carry from phase to phase and step to step. Words like "Valve OPEN" on a valve that's already open are statements and draw nothing. That is plain Python, tested in pytest. `static/brew_animation.js` only draws one step at a time, using the step's real seconds so it keeps time with the clock. Free-text methods, and brewers with no drawing (espresso, "No Brewer"), simply get no drawing. The drawing comes from the brewer's name or its type (`Brewer.method`, set by the type chip when it was added). Whether it shows at all is the person's "Show the brewer animation" switch in Settings (`user.show_brew_animation`, on by default): when it's off the server leaves out `data-animation`, so the script never runs.

**The pages.** Three tabs (`base.html`: a bottom tab bar on a phone, a row on a portrait iPad, a side rail at 1024 px and up):
- **Brew** (`/`, `main.index`) opens on **Up next**: the planned brew; else the coffee brewed most recently (that still has coffee) with the gear and named recipe last used with it (`crud.gear_for_bean`); else, or with `?pick=1`, the coffees as photo cards (`crud.coffees_to_brew`, most recently brewed first). `?bag_id=` (and optional `brewer_id`, `grinder_id`, `line_id`) picks one; a coffee never brewed asks for gear as chips. A coffee with several open bags uses the oldest one that isn't frozen (`crud.pick_bag`). The card (`partials/latest_recipe.html`) shows brew mode's tiles, the method, the Next time note, and Start brewing pinned above the tab bar (`.dock`); everything else is a short list that opens sheets. A coffee and gear with no recipe offers, in order: copy one of yours (`POST /lines/{id}/copy`, `crud.copy_line`), a starting recipe for the brewer (`app/starters.py`, keyed by `brew.brewer_shape`), or your own numbers. Until a person has a recipe, Brew shows the first-run checklist (`partials/first_run.html`) instead.
- **Coffees** (`/browse`) is a list and one coffee's page (`?bean=`): bags as chips that open sheets, its recipes (to the versions page), recent cups, and an Edit sheet with the bag photo. Adding a coffee (`POST /beans`) takes the bag size and roast date too, so one sheet creates both.
- **Settings** (`/manage`) has savings and streak, your gear (added by tapping a type; "Put away" archives instead of deleting), brew mode's switches, your account and, for the admin, people.

**Try a change** (`/lines/{id}/change`, `change_recipe.html`) is how a version is made: tap the one tile to change, set it with a stepper (limits in `main.CHANGE_LIMITS`; grind steps from `_grind_step`), say why. It starts from the Next time note (or a planned change). Saving logs no cup unless "I already brewed it" is ticked (that checkbox is the `bag_id`), and a plan is only used up when a cup is logged. `?method=1&actual=<brew>` opens on the method with what the scale saw beside each step (`brew.actual_timings`); the log form's "Save and edit the steps now" (`then=change`) goes there.

**Versions** (`/lines/{id}/versions`): newest first, each with its change in real values, reason, cups and average rating; compare any version with the current one; "Brew it once" (`/lines/{id}/brew?recipe_id=`) runs an older version and logs the cup against it without changing the current one. Only the newest version can be fixed in place (`/recipes/{id}/fix`: its own changed value and reason, still exactly one change from its parent) or, with no cups, deleted; any version's reason can be reworded.

**Cups can be corrected.** `/brews/{id}/edit` changes notes (with "+ Cooled note"), rating, Next time and bag (same coffee only). For an hour after logging, the card offers "How is it now it's cooled?". Deleting a cup redirects to `/?undo=<token>`; Undo restores it (curve included) for two minutes. The tokens live in memory (`main._UNDO`): prod runs one process, and a restart only loses the Undo.

**Words and help.** Settings and changes reach the screen only through `app/words.py` ("Temp +3 °C", "Temp 91 → 93 °C", `num` drops ".0"); `Delta.change_label` reads its two versions. The UI words are Recipe, Version, Try a change, Next time, Up next. Every "?" is `tip('key')` (`partials/tip.html`) with its text in `app/tips.py`; `tests/test_help.py` fails if a template uses a key with no text. The tour (three cards on Brew, `data-tour` targets) is remembered per person in `localStorage`; `/?tour=1` replays it. `/help` explains the loop.

**Form checks never lose work.** `static/forms.js` sets `novalidate` and shows its own messages under fields (`data-label`, `data-unit` for wording; `data-taken` for names already used), warns without blocking (an odd ratio), keeps `textarea[data-draft]` on the device, and disables a form's buttons once it's sent. A refused POST (400, or 422 for a missing or non-numeric field) renders `error.html` with the message and Go back, where the browser still has what was typed; requests that don't accept HTML get the plain JSON error. Read a form's method with `getAttribute('method')`: a field named "method" (the brewer form) shadows `form.method`.

---

## Data model

```
User                          (password_hash, is_admin, must_change_password, show_brew_animation, show_live_graph)
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

BrewCurve                     ← brew mode's scale readings, one per brew (brew_id is the key)
└── samples: str              ← JSON {"t","g","f"}; no relationship from Brew, so loading brews never loads it

Brewer                        (user_id → User; method = its type; archived)
└── recipes: List[Recipe]

Grinder                       (user_id → User; archived)
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
├── line_id → RecipeLine      (None = the combination's default line)
└── suggested_param/delta/rationale  ← a change to try, when the recipe has no recommendation

Delta
├── from_recipe_id → Recipe
└── to_recipe_id → Recipe
```

**PlannedBrew:** "Up next" in the UI, created from the card's "Make this Up next" sheet or a coffee's page. `crud.create_plan` replaces any existing plan for that user. When a plan exists, Brew opens on it; logging a brew, or saving a variation that also logs a cup, with `planned_brew_id` deletes the plan. Deleting a bag, brewer, grinder, or named recipe also deletes plans that reference it. Plans record the named recipe (`line_id`); the browse form offers every named recipe for the bean and `/plan` takes the brewer and grinder from it unless they are chosen explicitly. A plan with no `line_id` means "whichever line is the default when opened" (a bean with no recipes yet, or gear that matches none of the chosen recipe's). `/plan` drops a `line_id` that doesn't belong to the bag's bean or the submitted gear. `is_current_plan` is computed in `main._latest_recipe_context`, not in the template.

**A suggested change on a plan:** both schedule forms offer "Suggest a change to try" (`partials/plan_suggestion_fields.html`) only when the recipe has no recommendation yet (`crud.line_recommendation`: the newest brew of its current version). On browse each recipe option carries `data-has-rec` and a small script swaps the fields for a note; `/plan` drops a suggestion for a recipe that has one either way, so without JavaScript nothing goes wrong. `_latest_recipe_context` hands the panel `rec`: the newest brew's recommendation, else the current plan's suggestion (`from_plan`, labelled "Planned change"). Both feed the banner and Try a change alike. A brew's own recommendation always wins, and the suggestion goes with the plan when it's used or cancelled.

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
- These surface in the brew page as an amber "Recommended next" banner (or a scheduled brew's suggestion, "Planned change", when the newest brew has none; see PlannedBrew) and pre-populate the "Create variation" form via the `applyRecommendation()` JS function
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

### 3. Try a change's form is `#variation-form`, and the step editor knows it

`static/step_editor.js` marks the Method tile when its rows are edited (it looks for `[name="changed_param"]`: a select in old forms, radios here), and skips its submit check once its editor has been replaced (`editor.isConnected`): switching away from Method puts back a fresh editor from `<template id="method-original">`. `forms.js` leaves that form's Save button to `change_recipe.js`.

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

## Bookoo scale

Brew mode can connect a Bookoo Themis (Mini or Ultra; the protocol was tried on an Ultra) over Web Bluetooth: `static/scale.js`, browser only, nothing on the server and no schema change.

- **Only where it works.** The "Scale" button is `hidden` in the HTML and the script shows it only if `navigator.bluetooth` exists in a secure context (Chrome, Edge, Android Chrome, Bluefy). Safari, Firefox and the Kindle never see it. Claude's in-app browser has `navigator.bluetooth` but no device picker, so `requestDevice` is cancelled at once there; test in Chrome.
- **Protocol:** Bookoo's own notes, github.com/BooKooCode/OpenSource (`bookoo_ultra_scale/protocols.md`, `bookoo_mini_scale/protocols.md`). Service `0x0FFE`. `0xFF11` notifies 20-byte packets: `03 0B`, timer ms (3 bytes), unit, sign (`0x2D` is minus), grams × 100 (3 bytes), flow sign, flow × 100 (2), battery, standby, buzzer, smoothing, `00`, checksum. `0xFF12` takes `03 0A <cmd> 00 00 <checksum>` (01 tare, 04 start, 05 stop, 06 reset, 07 tare and start). Every checksum is the XOR of the bytes before it. Don't copy pybookoo's hard-coded command bytes: its start/stop/reset checksums are wrong (and it reads grams from 2 bytes, which breaks above 655 g). Automatic-mode events are `03 0D <state>` (00 stopped, 01 started, 02 ready, 03 exit ready, 04 exit done); the notes don't say which characteristic sends them, so the script listens on both.
- **The scale ignores commands by mode,** silently: on the Ultra, timer commands only work in timing and ratio mode, and tare not during an automatic brew, after one is done, or while charging. Write errors (as opposed to ignored commands) show under the weight (`#brew-scale-note`).
- **Targets come from the server.** Each step's `<li>` carries `data-grams` from `Step.target`: its "(to 200g)", or grams written in a pour/bloom ("90g bloom"), by the same rule the animation uses (`brew._target_grams`). The script reads the highlighted step (or the last target before it, so a swirl or drawdown still shows 500 g), so it follows the clock without talking to the timer script. The server runs without reload in development: restart it after changing `brew.py`, or the template sees no `target` and every `data-grams` comes out empty.
- **Reaching a weight ticks the step off; the clock still moves on.** Once the reading is within 2 g of the target while the timer runs, the step gets `data-reached` (a ✓) and `window.brewBeep('reached')` plays a rising double chirp, unlike the single new-step beep. It stays ticked if the weight dips or goes past the target (the tile stays green with its ✓, so a glance says no more to pour; the overshoot shows beside it as an amber "+6 g" once it's more than 2 g), and Reset clears it. Never advance a step by weight: the method's times are part of the recipe. Use an attribute, not a class, since the timer script rewrites every step's `className` four times a second.
- **Countdown, then coupling with the timer:** Start from zero counts down 5 s (low beep a second, high one at go; pressing again cancels) so there is time to pick up the kettle; Resume starts at once. At go the timer script calls `window.brewScaleGo()`, which sends tare-and-start (Bookoo's recommended command; it also starts a ready automatic brew); the Start and Cancel clicks themselves send nothing. Resume sends start, Stop stop, Reset reset (`scale.js` loads before the timer script, so its click listener sees the label that was pressed). The scale's started event, or its timer starting, while the clock shows Start or is counting down calls `window.brewTimerStartNow()`: no countdown, nothing echoed back. Its stopped event clicks Stop while running. `stop()` appends `window.brewScaleGrams()` to the "Brewed m:ss" line. Sounds are `SOUNDS` in the timer script; the AudioContext is woken on any tap (click or touchend), since a brew the scale starts has none. On iPhones the first tap also plays a silent blip (iOS only lets sound out later after one) and sets `navigator.audioSession.type = 'playback'`, or the ringer's silent switch mutes every beep; that can pause music from another app. Each beep resumes a context the phone suspended after a lock or a call.
- **The scale's own timer drives the app's too.** Every weight packet carries the scale's timer (ms). When it starts counting (its button, or its auto-start) while the clock shows Start (or is counting down), the app starts; when it stops ticking for 1.5 s, the app stops, but only if the scale's timer ran during this run of the app's, since the scale ignores a start that would resume a stopped timer. A timer already running at connect is not a start. Starts from the scale go through `startNow()` and stops through `press()`, so neither is sent back.
- **Lifting the brewer before Stop.** The scale was tared with the brewer on, so lifting it drops the reading by its whole weight, often below zero. Nothing else in a brew makes the weight fall, so while running, a reading (median of the last second, so a spoon press doesn't count) held more than 50 g below the brew's highest for 1 s means the brewer is off: the readings from the fall are dropped from the curve, the last real weight is shown and used for the "Brewed" line, nothing is recorded until the reading is back within 50 g, and a note says so. Tare and Reset clear it.
- **Graphs after the brew** (`static/brew_graphs.js`): while the timer runs, `scale.js` records `[brew seconds, grams, g/s]` from every packet (its own clock, paused with the timer), and on Stop draws weight and flow as two SVG charts on one time axis (never one chart with two y-scales), the step targets dashed on the weight chart, a summary line, and a crosshair readout on hover/touch, laid over this named recipe's newest saved curve in grey (`main._last_curve`, `data-compare`). Reset hides them. With "Show the graph while brewing" on in Manage (`user.show_live_graph`, off by default) and a scale connected, `BrewGraphs.live` redraws a shorter pair into `#brew-live` once a second while the timer runs, out to the method's last step so the whole target staircase shows; it hides the step dots (`.brew-live-on`). The same file draws a logged brew's graph page and saves either as a PNG on a canvas (charts serialised with their CSS written in, since a standalone SVG has no stylesheet).
- **Curves are saved with the brew** (`BrewCurve`, one row per brew, JSON `{"t","g","f"}` at ~2 readings/s, ~5-10 KB for a 4-minute brew). Stopping the timer fills the log form's hidden `curve` field; `/brews` stores it through `crud.parse_curve`, which validates and re-encodes it and returns None for anything malformed: a bad curve is dropped, the brew is still logged, so a bug never costs someone their tasting notes. Brews are deleted only through `crud._delete_brew`, which removes the curve too. `/brews/{id}/graph` (owned via the brew's bag) compares with the previous brew of the same named recipe by default (`?compare=<id>`, `0` for none; brews of other named recipes are a 404), labelling the other brew with what differed from this version; `/brews/{id}/curve.csv` is the raw readings. History rows link "Graph" when a curve exists (`curve_ids`).
- **Curves are private brew data.** The Markdown export never has them. The share image gets one only with `?curve=1` (a link on the share page), only weight and flow over time (no date), and only from a brew of the current version, since an older version's curve isn't this recipe.
- Templates link static files with `{{ static('scale.js') }}` (`main.static_url`), which adds `?v=<content hash>`, so a changed file gets a new URL and no browser keeps an old copy (Bluefy on an iPad did). The hash is read once per process: restart the dev server after editing a static file. Always use `static(...)` for new `<script>`/`<link>` tags.

---

## Sharing recipes

"Share as text" / "Download .md" on the recipe card serve `app/export.py`'s Markdown for the current named recipe. It stays behind Caddy's basic auth like every other route; nothing is public.

- **Privacy is a whitelist.** `export.py` reads only bean name/origin/roast/flavour notes, brewer and grinder names, the latest version's parameters and method, and the line's deltas with their rationales. Tasting notes, ratings, recommendations, bags/quantities, `Bean.notes`, plans, and user names must never appear; `tests/test_export_recipe.py` plants marker strings in all of them. Keep new fields out unless they are clearly meant for friends.
- **History shows real values** (`before → after` read from the two versions), never `Delta.delta_amount`, which is typed by hand and can be wrong (prod change #22 records −1 for 21 → 19).
- **Share as image** (`/lines/{id}/share-image`) uses the same whitelist: `export.card_data` gives the bean, gear, every parameter and the method, and `static/share_image.js` draws a 1080×1350 (Instagram 4:5) PNG on a canvas in the browser, with the bag photo and colours (text only ever on the plain card, never on the colours), then offers the phone's share sheet and a download. No imaging library on the server, for the reason under "Bag photos". `tests/test_share_image.py` plants the same marker strings.
- **Opt-in extras on the share image**, each off until switched on for that card, by a link on the share page: `?curve=1` (the weight and flow of the newest brew of this version, as two small labelled charts side by side with no axes, the weight against its step targets, dashed), `?notes=1` (this named recipe's tasting notes, newest first, `crud.tasting_note` with brew mode's "Brewed m:ss · N g" line removed, labelled with the date and what differed from the current version), and `?format=story` (1080×1920; the note and the curve above the recipe). The person picks one note and trims it in a textarea; `share_image.js` redraws from that in the browser, so the text is never in a URL or saved. A rating shows only if that brew has one and they tick "Show my rating". Recommendations, bean/bag/plan notes and user names stay off in every mode (`tests/test_share_image.py`). With a note or curve, the post card shrinks its header and tiles so the method keeps room.
- "Default" is not shown as a recipe name; grind is always printed with the grinder's name, since a setting means nothing on another grinder.
- A public link (`/s/<token>`) was planned as a second step: a `RecipeShare` table with revocable random tokens, a self-contained read-only page reusing `export.py`'s data, and a Caddy `handle /s/*` placed before `basicauth`. Not built; it needs the user's go-ahead for the Caddy change.

---

## File map

| File | Role |
|---|---|
| `app/models.py` | SQLModel ORM definitions. All schema changes start here. |
| `app/crud.py` | All DB reads and writes. No business logic in routes — it belongs here. |
| `app/auth.py` | Password hashing (scrypt, stdlib only) and session tokens. |
| `app/brew.py` | The step format (`is_standard`, `needs_tidy`, `step_editor_data`), `parse_steps` for brew mode, `animation_data` for its animation, and `suggest_steps` for tidying. For free text it picks out `m:ss` times (skipping ratios like "1:16" and the end of ranges like "3:30–4:00"). Server-side so it's tested in pytest; the page's script only keeps time. |
| `app/theme.py` | Bean colours → `--accent`, `--accent-soft`, `--mesh-strip` and `--mesh-strong` CSS variables (the `bean_theme` filter, applied to a bean). Validates the colours and guarantees readable contrast. |
| `app/export.py` | Named recipe → shareable Markdown (`GET /lines/{id}/export.md`, `?download=1` for a file). Whitelists what it shows; see "Sharing recipes". |
| `app/db.py` | Engine (path overridable with `COFFEE_DB`), session factory, `create_db_and_tables()`, `run_migrations()` (creates missing tables, additive column adds, user seeding, Default named-recipe backfill). |
| `app/main.py` | FastAPI routes. Thin — calls crud, returns TemplateResponse. Also user-cookie helpers, the morning banner's pixel art and quotes. |
| `app/templates/base.html` | Nav bar (with current user link), page shell, `toggleForm()` and `flipSign()` JS helpers. |
| `app/templates/select_user.html` | Sign-in page: pick your name, enter your password. |
| `app/templates/account.html` | Change your password, sign out; also the forced first-sign-in password step. |
| `app/templates/temporary_password.html` | Shows a new temporary password once, to the admin. |
| `app/templates/brew.html` | Brew mode (`GET /lines/{id}/brew?bag_id=&plan_id=&recipe_id=`; `recipe_id` brews an older version once), the layout picked from mockups ("E"): before Start the recipe as four labelled tiles (Coffee, Grind, Water, Temperature, each saying what it's for, readable from the counter); then time and weight as two equal tiles (without a scale the right tile is "Pour to" the step's target, or "Step ends in"), the current step in a card with the animation, the next step, and the method folded under "All steps" with dots; a labelled one-line recipe once brewing; Start/Stop/Tare/Reset/Log in a sticky bar at the bottom. "Log this brew" (the log card) stays hidden until Stop. A reached target turns the weight tile green with a big ✓ and the step card's background green. Numbers size with their tile (`cqi`), so they never spill over whatever the font. A landscape iPad (the main device) gets two columns, `.brew-main` and `.brew-side` (every step open, the live graph, the graphs after Stop); everything down to the bar fits 1180×820 and a 375×740 phone. No site header. Without JavaScript (the Kindle) it's the recipe tiles, every step and the log form. Steps carry `data-times`; the log form shows when the bag belongs to this bean. `plan_id` is only honoured if it is the current user's plan for this bag/brewer/grinder/line, so logging from here clears the schedule like the panel does. |
| `app/templates/partials/log_brew_form.html` | The "Log a brew" form, included by the card's log sheet and brew mode with `log_recipe_id` / `log_bag_id` / `log_plan_id` (and `log_bag_left` / `log_dose` for the finish-the-bag prompt). Big stars, taste chips and Next time chips (`static/log_form.js`) over the real fields; "Change steps" offers Save and edit the steps now (`then=change`). One per page: it uses fixed ids (`log-notes`, `rec-delta-row`). |
| `app/templates/partials/first_run.html` | The first-run checklist on Brew (until the person has a recipe): add the coffee (sheet), tap a brewer and grinder, pick a starting recipe. |
| `app/templates/partials/star_input.html` | 1-5 star picker, CSS only (reversed radios). Expects `star_name`; used by the log form (`rating`) and variation form (`brew_rating`). |
| `app/templates/partials/bean_art_form.html` | Bag photo controls on the manage page (add/retake, remove, edit colours); `static/bean_art.js` does the upload and "Reset to photo". |
| `app/templates/partials/recipe_text_field.html` | The method field: a real `<textarea name="recipe_text">` that `static/step_editor.js` covers with rows when the text is standard or empty. It stays the form field, so no JavaScript (Kindle) or free text just means the plain box. The script only rewrites it after an actual edit, so an untouched recipe can't change. |
| `app/templates/tidy_recipe.html` | "Tidy into steps": the current method, suggested rows, save as a new version. |
| `app/templates/index.html` | Brew: saved-version banner, the morning strip (pixel art and quote on one line), then Up next (the card), a coffee that needs gear, or the coffees as cards; the coffee sheet, and the add-coffee and add-gear sheets. See "The pages". |
| `app/templates/partials/latest_recipe.html` | The Up next card (also `/recipes/latest`): tiles, method, Next time with Try it, Start brewing in a `.dock`, the action list, recent cups and change history (second column on an iPad), and its sheets (log, share, Make this Up next, More: rename / copy / new recipe / delete, gear). With no recipe: copy one, a starting recipe, or your own numbers. |
| `app/templates/manage.html` | Settings: savings and streak cards, your gear (type chips to add, Put away, delete), put-away gear, brew mode, you (account, help, tour), people (admin). |
| `app/templates/browse.html` | Coffees: the list and one coffee's page (bags as chips with sheets, recipes with their numbers, recent cups, Edit sheet with photo and colours, Make Up next sheet with the suggested-change fields). |
| `app/static/brew_animation.js` | Draws brew mode's animation from the plan in `data-animation` into the step card (switched on and off on Manage). Its CSS is at the end of `styles.css`, with every selector under `.brew-scene` and keyframes prefixed `ba-`. |
| `app/static/scale.js` | Brew mode's Bookoo scale: connect, live weight against the step's `data-grams`, tare, auto-start. See "Bookoo scale". |
| `app/static/brew_graphs.js` | Weight and flow graphs: after a brew in brew mode, and on a logged brew's graph page (with comparison); PNG export. |
| `app/templates/brew_graph.html` | A logged brew's graph page (`/brews/{id}/graph`): compare picker, PNG and CSV. Slots come from `partials/brew_graph_body.html`. |
| `app/static/share_image.js` | Draws the "Share as image" card on a canvas from `data-card` and hands it to the share sheet. |
| `app/static/styles.css` | All styles. No external CSS framework. Later sections: touch shell, Up next card, Try a change, versions, Coffees and Settings, first run, form checks, help. |
| `app/words.py` | Settings and changes in words ("Temp +3 °C", "Temp 91 → 93 °C"), `num` without ".0". Template filters `num`, `param_label`; globals `change_label`, `change_amount`. |
| `app/tips.py` | The text behind every "?" (`partials/tip.html`'s `tip('key')`). |
| `app/starters.py` | Starting recipes per brewer drawing, for a first recipe. |
| `app/templates/change_recipe.html` | Try a change (`/lines/{id}/change`). |
| `app/templates/versions.html` | A named recipe's versions (`/lines/{id}/versions`): compare, brew once, undo, fix, delete. |
| `app/templates/brew_edit.html` | Correct a logged cup (`/brews/{id}/edit`). |
| `app/templates/help.html` | How this works (`/help`). |
| `app/templates/error.html` | A refused form, in words, with Go back. |
| `app/templates/partials/` (new) | `tip.html`, `coffee_cards.html`, `gear_choice.html`, `bag_size_field.html`, `add_coffee_sheet.html`, `add_gear_sheets.html`, `first_run.html`. |
| `app/static/sheet.js`, `tips.js`, `forms.js`, `change_recipe.js`, `log_form.js` | Sheets; tips and the tour; form checks; Try a change; the log form's chips. |
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
| `tests/test_brew_animation.py` | What each step is read as, brewer drawings, the water/valve/cup plan, real prod methods, and free text getting no animation. The drawing itself is checked by hand. |
| `tests/test_scale.py` | What brew mode gives the scale script: step targets (incl. inline grams), hidden controls, the script. The Bluetooth side is checked by hand with a real scale. |
| `tests/test_brew_curves.py` | Saving curves from the log form, validation (a bad curve never loses the brew), graph page and comparison, CSV, history links, the share image's opt-in curve, delete cascades, export/import. |
| `tests/test_share_image.py` | The share image's data: every parameter, method steps, colours, and no private fields. The drawing is checked by hand. |
| `tests/test_savings.py` | Lifetime savings on Manage: brews × ₹300 (`main.CAFE_CUP_PRICE_INR`), Indian digit grouping (`main.inr`), only your own brews. |
| `tests/test_streaks.py` | Brewing streaks: runs of days, a streak surviving until today ends, India-time day boundaries, this month, the card. |
| `tests/test_plan_suggestion.py` | A change to try on a scheduled brew: offered only without a recommendation, shown as "Planned change", a brew's recommendation winning, validation, export/import. |
| `tests/test_welcome.py` | The first-run checklist: who gets it, coffee and bag in one go, gear by tapping, starting recipes. |
| `tests/test_words.py`, `test_help.py`, `test_edit_cups.py`, `test_try_a_change.py`, `test_log_sheet.py`, `test_up_next.py`, `test_versions.py`, `test_form_checks.py`, `test_gear_archive.py` | The simplification pass (2026-11-12): wording, tips, fixing cups and Undo, Try a change, logging chips and real timings, Up next and copy, versions, form checks, putting gear away. |
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

## The card on its own

`/recipes/latest?bag_id=&brewer_id=&grinder_id=&line_id=` renders `partials/latest_recipe.html` by itself (once htmx's swap target; Brew now renders it in place). Most panel tests use it (`tests/test_flows.latest`). With an incomplete combination it returns a prompt instead of querying. Choosing a named recipe on Brew is a plain GET form back to `/`.

---

## UI conventions

- **Touch first:** `button`, `select` and inputs are at least 44 px tall. Secondary tasks go in a `<dialog class="sheet">` (with `.sheet-grab` and `.sheet-head`), opened by `data-sheet="id"`, closed by `data-sheet-close` or a tap outside. The page's one main action goes in a `.dock` (sticky above the tab bar). Lists of actions are `.action-list` rows with a `.chev`. Choices are `.chip`s (`.on` / `aria-pressed`), a `.seg` segmented control, or a `.stepper` (− input +).
- **Recipe numbers** are tiles (`.rtiles` / `.rtile`: eyebrow label, big number, what it's for), as in brew mode; a visually hidden `.sr-only` line keeps them readable as one sentence.
- **Two columns on a landscape iPad:** `.up-next-grid`, `.change-layout`, `.versions-layout`, `.coffees-layout`, `.settings-grid` switch at 1024 px.
- **Collapsibles:** use `<details>/<summary>` — no JS needed, already styled with `.bean-block`, `.history-block` classes. The arrow indicator is a CSS `::before` pseudo-element that rotates on `[open]`.
- **Low stock:** rows with `remaining ≤ low_threshold_g` get class `low-stock` (amber background).
- **Per-bean colours:** set `style="{{ bean|bean_theme }}"` on a container, then use `var(--accent, <default>)` / `var(--accent-soft, <default>)` in CSS so beans without a photo keep the normal palette. `--mesh-strip` is the gradient border around a coffee's cards (a thin strip along the top in brew mode, which has enough going on); `--mesh-strong` frames the artwork. Never put a mesh behind text: it was tried as a card background and hurt readability.
- **Muted text:** class `.muted` for secondary/empty-state text.
- **Buttons:** default button is dark brown (`#6b3d2e`). Secondary actions use `.btn-secondary` (parchment `#f0e4d4`). Destructive actions add `.btn-danger`.
- **`hidden` works everywhere:** a global `[hidden] { display: none !important; }` rule makes the attribute win over any `display` rule.
- **Phone width:** the page must never be wider than the screen, or iOS zooms everything out ("the recipe got tiny"). `.grid` uses `minmax(0, 1fr)` — never a bare `1fr`/auto column, which grows to its widest content and widens every card; rows of inputs + buttons need `flex-wrap`/`min-width: 0`; `.delta-table` scrolls inside its card under 600px. Check new UI at 375px wide (`document.documentElement.scrollWidth` must equal the viewport) and at 1180×820 (a landscape iPad).
- **Signed amounts:** iOS number keypads (`inputmode="decimal"`) have no minus key. Any input that can be negative goes in a `<span class="signed-input">` with a `<button type="button" class="btn-sign" onclick="flipSign(this)">±</button>` right after the input (`flipSign` flips the sign of its previous sibling).
- **Forms:** always use `.stacked-form` class. Labels go above inputs (separate `<label>` tag, not wrapping the input) for textareas. Inputs wrap labels for single-line fields — this is inconsistent and worth standardising if the forms grow.

---

## Edit/delete patterns

All entity management on the manage page (beans, bags, brewers, grinders) follows the same pattern (named recipes are renamed/deleted from the brew page instead):

**Edit forms:** in a sheet (a bag, a coffee) or a `<details class="gear-row">` (gear, people). `toggleForm(id)` in `base.html` remains for older markup.

**Delete with cascade:** Deletion order must respect FK constraints: Deltas → Brews → Recipes → PlannedBrews → RecipeLines → (Bags) → Bean. The crud functions handle this explicitly (SQLite does not enforce FK constraints by default), via the shared helpers `crud._delete_recipes` and `crud._delete_lines`. See `crud.delete_bean`, `crud.delete_brewer`, `crud.delete_grinder`, `crud.delete_line`, and `crud.delete_user` (which cascades through all of the user's beans, brewers, and grinders).

**Completed bags:** `BeanBag.is_completed = True` hides the bag from the brew-page picker (`crud.get_active_bags_for_user` excludes completed bags, and the `/` route also drops bags with nothing remaining). The bag remains in the database and still appears on its coffee's page (a faded chip). Logging a cup that leaves less than another cup offers "Mark the bag finished" (`finish_bag`). A coffee whose bags are all finished folds into "Finished" on Coffees.

**Routes:** All edit/delete/complete routes are `POST` (HTML forms cannot `DELETE`). They redirect with `status_code=303`: bean, bag and photo routes to the coffee's page (`/browse?bean=`), gear routes to `/manage#gear` (or a form's own `next`, checked by `main._back_to`), named-recipe routes to `/`, version routes to the versions page. Validation failures raise `HTTPException(400)` with a message written for the person (it's shown on `error.html`).

**Confirm dialogs:** big deletes (a coffee, a recipe, gear, a bag) use `onsubmit="return confirm('...')"`, saying what goes with them. A cup is deleted at once with Undo instead.

---

## What has been intentionally left out

- **No email or self-service password reset.** The admin resets passwords. There is also no login rate limiting, because Caddy's password already keeps the open internet away; add both before ever removing it.
- **No CSRF tokens.** The session cookie is `SameSite=Lax`, which stops cross-site form posts, and the site is behind Caddy's password.
- **No alembic.** Additive columns go in `db.run_migrations()`; anything else uses export → `scripts/drop_tables.py` → import.
- **No unit tests for templates/CSS.** `tests/` covers the HTTP flows, data parity, and export/import; visual changes are checked by hand in a browser.
