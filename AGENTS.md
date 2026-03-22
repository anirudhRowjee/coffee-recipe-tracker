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

**Minimal dependencies, minimal JavaScript.** The stack is FastAPI + SQLite + Jinja2 + htmx. No JS framework. The only interactivity is htmx partial loading (the brew page recipe panel) and a handful of inline `<script>` snippets for show/hide logic. New features should follow this pattern — reach for htmx before reaching for JS, and avoid adding npm/bundling.

**Server-rendered, not API-first.** Routes return HTML, not JSON. Forms POST to endpoints that redirect. This keeps the Kindle-compatibility high and the codebase small.

**One-parameter delta rule.** This is the core intellectual constraint of the app. Each recipe variation must change exactly one of: `dose_g`, `water_ml`, `temp_c`, `grind_size`, `recipe_text`. This is enforced in `crud.validate_one_parameter_delta` and exists so that the effect of any change is unambiguous. Do not relax this constraint without the user's explicit instruction.

**Recipe = definition, Brew = instance.** A `Recipe` is a parameter snapshot (dose, water, temp, grind). A `Brew` is a single cup pulled using that recipe, linked to a specific physical bag. Tasting notes live on `Brew`, not `Recipe`. This distinction is central — conflating them causes quantity tracking to break.

**Bean = type, BeanBag = physical bag.** `Bean` is the coffee variety (Ethiopia Yirgacheffe, etc.). `BeanBag` is a specific purchase of that variety, with its own roast date, quantity, and freeze status. You can have multiple bags of the same bean. Recipe history is shared across bags of the same bean (looked up by `bean_id + brewer_id + grinder_id`).

**No migrations.** Schema changes require recreating the database. This is an intentional trade-off for a personal single-user app. There is `scripts/export.py` to export data before a wipe and `scripts/drop_tables.py` to reset. If the app grows in users or data, `alembic` is the right next step.

---

## Data model

```
Bean
├── bags: List[BeanBag]
└── recipes: List[Recipe]

BeanBag
├── bean: Bean
└── brews: List[Brew]         ← quantity tracked via brews, not directly

Brewer
└── recipes: List[Recipe]

Grinder
└── recipes: List[Recipe]

Recipe
├── bean: Bean
├── brewer: Brewer
├── grinder: Grinder
└── brews: List[Brew]

Brew
├── recipe: Recipe
└── bag: BeanBag

Delta
├── from_recipe_id → Recipe
└── to_recipe_id → Recipe
```

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
- These surface in the brew page as a green banner and pre-populate the "Create variation" form via the `applyRecommendation()` JS function

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

---

## File map

| File | Role |
|---|---|
| `app/models.py` | SQLModel ORM definitions. All schema changes start here. |
| `app/crud.py` | All DB reads and writes. No business logic in routes — it belongs here. |
| `app/db.py` | Engine, session factory, `create_db_and_tables()`. |
| `app/main.py` | FastAPI routes. Thin — calls crud, returns TemplateResponse. |
| `app/templates/base.html` | Nav bar, page shell, `toggleForm()` JS helper. |
| `app/templates/index.html` | Brew page. Picker form with htmx (`hx-get="/recipes/latest"`). |
| `app/templates/partials/latest_recipe.html` | htmx partial. Recipe display, log-a-brew form, variation form, recommendation banner. |
| `app/templates/manage.html` | Add/edit/delete beans+bags, brewers, grinders. Inline edit forms toggled by `toggleForm()`. Bag rows have Edit/Done/Delete actions. |
| `app/templates/browse.html` | Bean overview with bag inventory and collapsible history. |
| `app/static/styles.css` | All styles. No external CSS framework. |
| `scripts/export.py` | Exports all tables to CSV in `export/`. |
| `scripts/import.py` | Restores from a CSV snapshot. Two-pass recipe insert for `previous_recipe_id`. Requires empty tables. |
| `scripts/drop_tables.py` | Drops and recreates all tables after confirmation prompt. |

---

## htmx usage

Only one htmx interaction exists: the brew page picker (`index.html`). When any select changes, htmx fires a GET to `/recipes/latest?bag_id=&brewer_id=&grinder_id=` and swaps the response into `#latest-wing`.

The partial endpoint (`/recipes/latest`) handles the incomplete-selection case gracefully — if any of the three IDs are missing, it returns a prompt message instead of querying the DB.

If you add new htmx interactions, keep them similarly self-contained with graceful empty states.

---

## UI conventions

- **Collapsibles:** use `<details>/<summary>` — no JS needed, already styled with `.bean-block`, `.history-block` classes. The arrow indicator is a CSS `::before` pseudo-element that rotates on `[open]`.
- **Low stock:** rows with `remaining ≤ low_threshold_g` get class `low-stock` (amber background).
- **Muted text:** class `.muted` for secondary/empty-state text.
- **Buttons:** default button is dark (`#334155`). Secondary actions use `.btn-secondary` (light grey). The apply-recommendation button uses `.btn-apply-rec` (green, defined in styles.css).
- **Forms:** always use `.stacked-form` class. Labels go above inputs (separate `<label>` tag, not wrapping the input) for textareas. Inputs wrap labels for single-line fields — this is inconsistent and worth standardising if the forms grow.

---

## Edit/delete patterns

All entity management (beans, bags, brewers, grinders) follows the same pattern:

**Inline edit forms:** Hidden `<div class="edit-form hidden" id="edit-<entity>-{{ id }}">` inside the row. `toggleForm(id)` in `base.html` flips the `.hidden` class. Edit button calls `toggleForm(...)` with `event.stopPropagation()` when inside a `<summary>` (to prevent `<details>` open/close).

**Delete with cascade:** Deletion order must respect FK constraints: Deltas → Brews → Recipes → (Bags) → Bean. The crud functions handle this explicitly (SQLite does not enforce FK constraints by default). See `crud.delete_bean`, `crud.delete_brewer`, `crud.delete_grinder`.

**Completed bags:** `BeanBag.is_completed = True` hides the bag from the brew-page picker (`index.html` filters `{% if not bag.is_completed %}`). The bag remains in the database and still appears in the manage page (greyed out with `.row-completed`).

**Routes:** All edit/delete/complete routes are `POST` (HTML forms cannot `DELETE`). They all redirect to `/manage` with `status_code=303`.

**Confirm dialogs:** Delete buttons use `onsubmit="return confirm('...')"` to prevent accidental deletion.

---

## What has been intentionally left out

- **No user accounts.** Single-user personal app. Auth was discussed for public cloud deployment but not implemented.
- **No CSRF protection.** Safe for local/LAN use. Add `starlette-csrf` middleware before any public deployment.
- **No migrations.** Use `scripts/export.py` before any schema change.
- **No tests.** The CRUD functions are pure and easily testable with pytest fixtures if needed.
- **No migrations.** Use `scripts/export.py` before any schema change, then `scripts/drop_tables.py` to wipe, then `scripts/import.py` to restore.
