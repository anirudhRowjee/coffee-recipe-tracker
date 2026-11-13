import functools
import hashlib
import json
import random
import secrets
import time
from datetime import date as date_type, datetime, timezone

from fastapi import FastAPI, File, Form, Query, Request, HTTPException, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from pathlib import Path
from typing import NamedTuple, Optional

from . import auth, brew, crud, db, export, four_six, models, starters, theme, tips, words

app = FastAPI(title="Coffee Recipe Tracker", docs_url=None, redoc_url=None, openapi_url=None)

STATIC_DIR = Path("app/static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory="app/templates")


@functools.lru_cache(maxsize=None)
def static_url(path: str) -> str:
    """/static/<path>?v=<content hash>: a changed file gets a new URL, so no browser
    (Bluefy on an iPad, say) keeps running an old script. Read once per process; a
    deploy restarts the app."""
    digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    return f"/static/{path}?v={digest}"


templates.env.globals["static"] = static_url
templates.env.filters["bean_theme"] = theme.bean_style
templates.env.filters["needs_tidy"] = brew.needs_tidy
templates.env.filters["num"] = words.num
templates.env.filters["steps_summary"] = brew.steps_summary
templates.env.filters["ratio"] = export.ratio
templates.env.filters["param_label"] = words.label
templates.env.globals["change_label"] = words.change
templates.env.globals["TIPS"] = tips.TIPS
templates.env.globals["change_amount"] = words.amount
templates.env.filters["step_editor_data"] = brew.step_editor_data
# What a cup costs at a café: every cup brewed at home is that much saved
CAFE_CUP_PRICE_INR = 300


def inr(amount: int) -> str:
    """Rupees with Indian digit grouping: ₹1,23,456."""
    digits = str(amount)
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join(([head] if head else []) + groups + [tail])


templates.env.filters["inr"] = inr
templates.env.filters["days"] = lambda n: f"{n} day" + ("" if n == 1 else "s")


def day_range(start: date_type, end: date_type) -> str:
    """"22–29 Oct 2026", or "30 Oct – 2 Nov 2026" across months; one day is just "9 Nov 2026"."""
    if start == end:
        return f"{end.day} {end:%b %Y}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {end:%b %Y}"
    first = f"{start.day} {start:%b}" if start.year == end.year else f"{start.day} {start:%b %Y}"
    return f"{first} – {end.day} {end:%b %Y}"


templates.env.globals["day_range"] = day_range
templates.env.filters["stars"] = lambda n: "★" * n + "☆" * (5 - n)
templates.env.filters["ist"] = lambda moment, pattern: crud.local_time(moment).strftime(pattern)  # India time

# The browser shrinks photos to about 1000px before uploading, so this is generous
MAX_BEAN_IMAGE_BYTES = 3_000_000

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 365  # a year: phones and the Kindle should stay signed in

PIXEL_ART_COLORS = [
    # coffee browns
    "#f5ebe0", "#e0c9b0", "#d4b896", "#c4956a", "#a08060", "#8c6a4f", "#7a4f32", "#5c3520", "#4a2a1e", "#3b1f0e",
    # caramel / amber
    "#fcd9a0", "#f5c87a", "#e0a458", "#c68a3d", "#92400e", "#8a5a2b",
    # matcha greens
    "#c9d97a", "#a8b545", "#7c9a3d", "#4d6b2f",
]

QUOTES = [
    # Coffee-flavored
    "Good things happen slowly, one cup at a time.",
    "Small adjustments, better mornings.",
    "The best brew is the one you paid attention to.",
    "Patience tastes like a well-timed pour.",
    "Every recipe is a rough draft until proven right.",
    "Today's grind is tomorrow's dial-in.",
    "Consistency is the secret ingredient.",
    "One variable at a time, one cup at a time.",
    "The perfect cup doesn't exist — the next one does.",
    "Slow down. The coffee isn't going anywhere.",
    "Taste first, tweak second.",
    "A quiet morning starts with a careful pour.",
    "Brew with intention, sip with attention.",
    "Great mornings are brewed, not found.",
    "Today's cup is data for tomorrow's cup.",
    # General
    "Start before you feel ready.",
    "Progress hides inside repetition.",
    "Curiosity is a renewable resource.",
    "The quiet hours are often the most productive.",
    "Focus is saying no to almost everything.",
    "Discipline looks like freedom from the outside.",
    "Small steps, repeated, become momentum.",
    "Done is a decision, not an accident.",
    "Attention is the rarest form of generosity.",
    "You don't need permission to begin.",
    "Clarity comes from doing, not thinking.",
    "The work reveals itself once you start.",
    "Habits are just decisions you've already made.",
    "Rest is part of the process, not a break from it.",
    "Every expert was once a beginner who didn't quit.",
    "Momentum is easier to keep than to build.",
    "Simplicity is the reward of hard editing.",
    "Precision is a form of care.",
    "Notice everything. Change one thing.",
    "The best time to start was earlier. The next best time is now.",
]


def _generate_pixel_art_svg(grid: int = 12, cell: int = 7, fill_chance: float = 0.62, asymmetry_chance: float = 0.4) -> str:
    half = grid // 2
    size = grid * cell

    def _pixel() -> Optional[str]:
        return random.choice(PIXEL_ART_COLORS) if random.random() < fill_chance else None

    rows: list = []
    for _y in range(grid):
        row = [_pixel() for _ in range(half)]
        mirrored = [row[i] if random.random() >= asymmetry_chance else _pixel() for i in range(half)]
        rows.append(row + mirrored[::-1])

    rects = []
    for y, row in enumerate(rows):
        for x, color in enumerate(row):
            if color:
                rects.append(f'<rect x="{x * cell}" y="{y * cell}" width="{cell}" height="{cell}" fill="{color}" />')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-label="Generative pixel art">{"".join(rects)}</svg>'


@app.on_event("startup")
def on_startup():
    db.create_db_and_tables()
    db.run_migrations()


def _parse_rating(value: Optional[str]) -> Optional[int]:
    """1-5 from the star inputs; anything else is treated as not rated."""
    return int(value) if value in ("1", "2", "3", "4", "5") else None


def _get_current_user(request: Request, session: Session) -> Optional[models.User]:
    token = request.cookies.get(SESSION_COOKIE)
    return crud.get_user_by_session_token(session, token) if token else None


def _require_user(request: Request, session: Session, allow_temporary_password: bool = False) -> models.User:
    user = _get_current_user(request, session)
    if not user:
        raise _redirect_to_select()
    if user.must_change_password and not allow_temporary_password:
        raise _redirect_to_change_password()
    return user


def _require_admin(request: Request, session: Session) -> models.User:
    user = _require_user(request, session)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the admin can do that")
    return user


def _owner_id(session: Session, item) -> Optional[int]:
    if isinstance(item, models.Brew):
        item = session.get(models.BeanBag, item.bag_id)
        if not item:
            return None
    if isinstance(item, (models.BeanBag, models.RecipeLine, models.Recipe)):
        bean = session.get(models.Bean, item.bean_id)
        return bean.user_id if bean else None
    return item.user_id


def _owned(session: Session, user: models.User, model, item_id: int):
    """The row, if it exists and belongs to this user. Someone else's is a 404, like a missing one."""
    item = session.get(model, item_id)
    if not item or _owner_id(session, item) != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return item


class _redirect_to_select(Exception):
    pass


class _redirect_to_change_password(Exception):
    pass


# Exception handlers, not an HTTP middleware: with some starlette versions
# (prod's 0.46) a middleware that catches these still sends the redirect but
# then re-raises the exception, logging a traceback on every redirect.
@app.exception_handler(_redirect_to_select)
def _redirect_to_select_handler(request: Request, exc: _redirect_to_select):
    r = RedirectResponse(url="/select-user", status_code=302)
    r.delete_cookie(SESSION_COOKIE)
    return r


# A refused form shows a page that says what was wrong and goes back to the form
# (the browser keeps what was typed), instead of a bare line of text.
def _wants_page(request: Request) -> bool:
    return request.method == "POST" and "text/html" in request.headers.get("accept", "text/html")


@app.exception_handler(StarletteHTTPException)
async def _http_error_page(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 400 and _wants_page(request):
        return templates.TemplateResponse("error.html", {"request": request, "heading": "Not saved",
                                                         "message": exc.detail}, status_code=400)
    return await http_exception_handler(request, exc)


_FIELD_NAMES = {"dose_g": "Coffee", "water_ml": "Water", "temp_c": "Temp", "grind_size": "Grind", "initial_quantity_g": "Bag size",
                "name": "Name", "recipe_id": "Recipe", "bag_id": "Bag", "bean_id": "Coffee", "brewer_id": "Brewer", "grinder_id": "Grinder"}


@app.exception_handler(RequestValidationError)
async def _validation_error_page(request: Request, exc: RequestValidationError):
    if not _wants_page(request):
        return await request_validation_exception_handler(request, exc)
    problems = []
    for err in exc.errors():
        field = str(err.get("loc", ["", ""])[-1])
        label = _FIELD_NAMES.get(field, field.replace("_", " ").capitalize())
        problems.append(f"{label} is missing." if err.get("type") == "missing" else f"{label} needs to be a number.")
    return templates.TemplateResponse("error.html", {"request": request, "heading": "Something's missing",
                                                     "message": " ".join(dict.fromkeys(problems)) or "Some of the form wasn't filled in."},
                                      status_code=422)


@app.exception_handler(_redirect_to_change_password)
def _redirect_to_change_password_handler(request: Request, exc: _redirect_to_change_password):
    return RedirectResponse(url="/account", status_code=302)


def _signin_page(request: Request, session: Session, error: str = "", selected_user_id: Optional[int] = None, status_code: int = 200):
    return templates.TemplateResponse("select_user.html", {
        "request": request,
        "users": crud.get_users(session),
        "current_user": None,
        "error": error,
        "selected_user_id": selected_user_id,
    }, status_code=status_code)


@app.get("/select-user", response_class=HTMLResponse)
def select_user(request: Request):
    with Session(db.engine) as session:
        return _signin_page(request, session)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, user_id: int = Form(...), password: str = Form(...)):
    with Session(db.engine) as session:
        user = session.get(models.User, user_id)
        if not user or not user.password_hash or not auth.verify_password(password, user.password_hash):
            return _signin_page(request, session, "That didn't match. If you don't have a password yet, ask your admin.", user_id, 401)
        token = crud.create_user_session(session, user_id)
        r = RedirectResponse(url="/account" if user.must_change_password else "/", status_code=303)
        r.set_cookie(SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
                     secure=request.url.scheme == "https")
        return r


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    with Session(db.engine) as session:
        if token:
            crud.delete_user_session(session, token)
    r = RedirectResponse(url="/select-user", status_code=303)
    r.delete_cookie(SESSION_COOKIE)
    return r


def _account_page(request: Request, user: models.User, error: str = "", status_code: int = 200):
    return templates.TemplateResponse("account.html", {
        "request": request,
        "current_user": user,
        "error": error,
        "min_length": auth.MIN_PASSWORD_LENGTH,
    }, status_code=status_code)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    with Session(db.engine) as session:
        return _account_page(request, _require_user(request, session, allow_temporary_password=True))


@app.post("/account/password", response_class=HTMLResponse)
def change_password(request: Request, new_password: str = Form(...), confirm_password: str = Form(...), current_password: str = Form("")):
    with Session(db.engine) as session:
        user = _require_user(request, session, allow_temporary_password=True)
        # someone on a temporary password has only just used it to sign in
        if not user.must_change_password and not auth.verify_password(current_password, user.password_hash or ""):
            return _account_page(request, user, "Your current password didn't match.", 400)
        if len(new_password) < auth.MIN_PASSWORD_LENGTH:
            return _account_page(request, user, f"Use at least {auth.MIN_PASSWORD_LENGTH} characters.", 400)
        if new_password != confirm_password:
            return _account_page(request, user, "Those two passwords didn't match.", 400)
        crud.set_user_password(session, user, new_password, must_change=False)
        crud.delete_sessions_for_user(session, user.id, except_token=request.cookies.get(SESSION_COOKIE))  # type: ignore[arg-type]
    return RedirectResponse(url="/", status_code=303)


def _temporary_password_page(request: Request, admin: models.User, name: str, password: str):
    return templates.TemplateResponse("temporary_password.html", {
        "request": request,
        "current_user": admin,
        "name": name,
        "password": password,
    })


@app.post("/users", response_class=HTMLResponse)
def create_user(request: Request, name: str = Form("")):
    with Session(db.engine) as session:
        admin = _require_admin(request, session)
        name = name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name can't be empty")
        if crud.name_taken(session, name):
            raise HTTPException(status_code=400, detail=f'There is already someone called "{name}"')
        password = auth.temporary_password()
        crud.create_user(session, name=name, password=password)
        return _temporary_password_page(request, admin, name, password)


@app.post("/users/{target_user_id}/reset-password", response_class=HTMLResponse)
def reset_user_password(target_user_id: int, request: Request):
    with Session(db.engine) as session:
        admin = _require_admin(request, session)
        target = session.get(models.User, target_user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Not found")
        if target.id == admin.id:
            raise HTTPException(status_code=400, detail="Change your own password on the account page")
        password = auth.temporary_password()
        crud.set_user_password(session, target, password, must_change=True)
        crud.delete_sessions_for_user(session, target_user_id)
        return _temporary_password_page(request, admin, target.name, password)


@app.post("/users/{target_user_id}/delete")
def delete_user(target_user_id: int, request: Request, admin_password: str = Form("")):
    with Session(db.engine) as session:
        admin = _require_admin(request, session)
        if not auth.verify_password(admin_password, admin.password_hash or ""):
            raise HTTPException(status_code=403, detail="Your password didn't match, so nothing was deleted")
        if target_user_id == admin.id:
            raise HTTPException(status_code=400, detail="You can't delete your own account")
        if not session.get(models.User, target_user_id):
            raise HTTPException(status_code=404, detail="Not found")
        crud.delete_user(session, target_user_id)
    return RedirectResponse(url="/manage", status_code=303)


class _Shown:
    """A recipe with one value swapped, for showing a change that isn't saved yet
    (brew mode's "Brew with change"). Everything else reads through to the real version."""
    def __init__(self, base, overrides: dict):
        self._base, self._overrides = base, overrides

    def __getattr__(self, name):
        return self._overrides[name] if name in self._overrides else getattr(self._base, name)


def _applied_change(latest: Optional[models.Recipe], rec) -> Optional[dict]:
    """What the Next time note (or planned change) would make the recipe, if it can be applied
    without asking: a number with an amount (coffee, water, temp, or a plain-number grind).
    None for a method change or a grind like "2.5.0", which need Try a change."""
    if not latest or not rec or rec.recommended_delta is None or rec.recommended_param not in ("dose_g", "water_ml", "temp_c", "grind_size"):
        return None
    param, before = rec.recommended_param, getattr(latest, rec.recommended_param)
    try:
        after_num = round(float(before) + rec.recommended_delta, 3)
    except (TypeError, ValueError):
        return None
    if param == "grind_size":
        after = words.num(after_num) if "." in str(before) or after_num % 1 else str(int(after_num))
    else:
        after = after_num
    if after == before or (param != "grind_size" and after_num <= 0):
        return None
    return {"param": param, "value": after, "label": words.change(param, rec.recommended_delta),
            "before_after": f"{words.label(param)} {words.num(before)} → {words.num(after)}{words.UNITS[param]}",
            "rationale": rec.recommended_rationale}


class _Rec(NamedTuple):
    recommended_param: str
    recommended_delta: Optional[float]
    recommended_rationale: Optional[str]
    from_plan: bool


def _shape_of(brewer: Optional[models.Brewer]) -> Optional[str]:
    """Which kind of brewer it is (brew mode's drawing): "cone", "switch", "flat", "aeropress" or None."""
    return brew.brewer_shape(brewer.name, brewer.method) if brewer else None


def _starters_for(brewer: Optional[models.Brewer]) -> list:
    return starters.for_brewer(brew.brewer_shape(brewer.name, brewer.method) if brewer else None)


def _is_pre_ground(grinder: Optional[models.Grinder]) -> bool:
    name = (grinder.name if grinder else "").lower()
    return "pre-ground" in name or "preground" in name or name in ("no grinder", "none")


def _up_next(session: Session, plan: Optional[models.PlannedBrew]) -> Optional[dict]:
    """What's planned, in words, for the "this replaces ..." warning on every Make-Up-next form."""
    if not plan:
        return None
    bag = session.get(models.BeanBag, plan.bag_id)
    line = session.get(models.RecipeLine, plan.line_id) if plan.line_id else None
    name = bag.bean.name if bag and bag.bean else "your planned coffee"
    if line and line.name != "Default":
        name += f" · {line.name}"
    return {"label": name, "bag_id": plan.bag_id, "line_id": plan.line_id or ""}


def _recipe_choices(session: Session, bean_id: int) -> list:
    """A coffee's named recipes as choices for "Another coffee", most recently used first:
    which gear each is on, how many versions, so the gear follows the recipe picked."""
    lines = crud.get_lines_for_bean(session, bean_id)
    out = []
    for ln in lines:
        brewer, grinder = session.get(models.Brewer, ln.brewer_id), session.get(models.Grinder, ln.grinder_id)
        latest = crud.get_latest_recipe(session, ln.id)  # type: ignore[arg-type]
        if not latest:
            continue
        out.append({"line_id": ln.id, "name": None if ln.name == "Default" else ln.name,
                    "brewer_id": ln.brewer_id, "grinder_id": ln.grinder_id,
                    "brewer": brewer.name if brewer else "", "grinder": grinder.name if grinder else "",
                    "summary": f"{words.num(latest.dose_g)} g · {words.num(latest.water_ml)} ml · {words.num(latest.temp_c)} °C · grind {latest.grind_size}",
                    "version": crud.version_number(session, latest)})
    return out


def _copy_sources(session: Session, user_id: Optional[int]) -> list:
    """Every named recipe of yours, newest first, as something to copy onto a coffee and gear that has none."""
    if not user_id:
        return []
    out = []
    for bean in crud.get_beans(session, user_id):
        for line in crud.get_lines_for_bean(session, bean.id):  # type: ignore[arg-type]
            latest = crud.get_latest_recipe(session, line.id)  # type: ignore[arg-type]
            if latest:
                out.append((line, bean, latest))
    out.sort(key=lambda e: e[2].created_at, reverse=True)
    return out[:12]


def _latest_recipe_context(session: Session, bag_id_int: Optional[int], brewer_id_int: Optional[int], grinder_id_int: Optional[int], user_id: Optional[int], line_id_int: Optional[int] = None) -> dict:
    pending_plan = crud.get_pending_plan(session, user_id) if user_id else None

    if not bag_id_int or not brewer_id_int or not grinder_id_int:
        return {
            "latest": None,
            "recent_brews": [],
            "recent_deltas": [],
            "lines": [],
            "line": None,
            "bag": None,
            "bag_id": bag_id_int,
            "bean_id": None,
            "brewer_id": brewer_id_int,
            "grinder_id": grinder_id_int,
            "rec": None,
            "cooling_brew": None,
            "message": "Select a bag, brewer, and grinder to show recipes.",
            "pending_plan": pending_plan,
            "is_current_plan": False,
        }

    bag = session.get(models.BeanBag, bag_id_int)
    if not bag:
        raise HTTPException(status_code=404, detail="Bag not found")

    bean_id = bag.bean_id
    # lines[0] is the most recently used named recipe: the default when none is picked
    lines = crud.get_lines_for_combo(session, bean_id, brewer_id_int, grinder_id_int)
    line = next((ln for ln in lines if ln.id == line_id_int), lines[0] if lines else None)
    latest = crud.get_latest_recipe(session, line.id) if line and line.id else None  # type: ignore[arg-type]
    recent_brews = crud.get_recent_brews_for_panel(session, latest) if latest and latest.id else []
    recent_deltas = crud.get_recent_deltas(session, line.id) if line and line.id else []  # type: ignore[arg-type]

    # A plan without a line (made from the browse page) means "the default one"
    is_current_plan = bool(
        pending_plan and line
        and pending_plan.bag_id == bag_id_int
        and pending_plan.brewer_id == brewer_id_int
        and pending_plan.grinder_id == grinder_id_int
        and (pending_plan.line_id == line.id or (pending_plan.line_id is None and line is lines[0]))
    )
    # What to try next: the newest brew's recommendation, else the scheduled brew's suggestion
    rec = None
    if recent_brews and recent_brews[0].recommended_param:
        rec = _Rec(recent_brews[0].recommended_param, recent_brews[0].recommended_delta, recent_brews[0].recommended_rationale, False)
    elif line and line.next_param:  # the recipe's planned change, whether or not it's Up next
        rec = _Rec(line.next_param, line.next_delta, line.next_rationale, True)
    # For an hour after a cup is logged, offer to add how it tastes once cooled
    cooling_brew, cooling_minutes = None, 0
    if recent_brews:
        brewed = recent_brews[0].brewed_at
        minutes = int((datetime.now(timezone.utc) - (brewed if brewed.tzinfo else brewed.replace(tzinfo=timezone.utc))).total_seconds() // 60)
        if 0 <= minutes < 60:
            cooling_brew, cooling_minutes = recent_brews[0], max(minutes, 1)
    return {
        "trial": _applied_change(latest, rec),
        "shape": _shape_of(session.get(models.Brewer, brewer_id_int)),
        "version": crud.version_number(session, latest) if latest else 0,
        "brewer": session.get(models.Brewer, brewer_id_int),
        "grinder": session.get(models.Grinder, grinder_id_int),
        "all_brewers": crud.get_brewers(session, user_id) if user_id else [],
        "all_grinders": crud.get_grinders(session, user_id) if user_id else [],
        "bean_bags": [(b, crud.get_remaining_quantity(session, b)) for b in crud.get_bags_for_bean(session, bean_id) if not b.is_completed],
        "copy_sources": [] if latest else _copy_sources(session, user_id),
        "starters": [] if latest else _starters_for(session.get(models.Brewer, brewer_id_int)),
        "pre_ground": _is_pre_ground(session.get(models.Grinder, grinder_id_int)),
        "bag_left": crud.get_remaining_quantity(session, bag),
        "cooling_brew": cooling_brew,
        "cooling_minutes": cooling_minutes,
        "rec": rec,
        "latest": latest,
        "recent_brews": recent_brews,
        "curve_ids": crud.brews_with_curves(session, [b.id for b in recent_brews]),  # type: ignore[misc]
        "recent_deltas": recent_deltas,
        "lines": lines,
        "line": line,
        "bag": bag,
        "bag_id": bag_id_int,
        "bean_id": bean_id,
        "brewer_id": brewer_id_int,
        "grinder_id": grinder_id_int,
        "message": "",
        "pending_plan": pending_plan,
        "is_current_plan": is_current_plan,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, bag_id: Optional[str] = None, brewer_id: Optional[str] = None,
          grinder_id: Optional[str] = None, line_id: Optional[str] = None, pick: int = 0, gear: str = ""):
    """Brew. "Up next" is the brew you planned; otherwise the coffee you brewed most
    recently (with the gear and recipe you used); otherwise, or with ?pick=1, a choice
    of coffees. ?bag_id= (and optionally brewer, grinder, recipe) picks one."""
    ints = {k: int(v) if v and v.isdigit() else None
            for k, v in (("bag", bag_id), ("brewer", brewer_id), ("grinder", grinder_id), ("line", line_id))}
    with Session(db.engine) as session:
        user = _require_user(request, session)
        coffees = crud.coffees_to_brew(session, user.id)  # type: ignore[arg-type]
        pending_plan = crud.get_pending_plan(session, user.id)  # type: ignore[arg-type]
        context = {
            "request": request,
            "coffees": coffees,
            "brewers": crud.get_brewers(session, user.id),  # type: ignore[arg-type]
            "grinders": crud.get_grinders(session, user.id),  # type: ignore[arg-type]
            "current_user": user,
            "pending_plan": pending_plan,
            "up_next": _up_next(session, pending_plan),
            "pixel_art_svg": _generate_pixel_art_svg(cell=4),
            "morning_quote": random.choice(QUOTES),
            "picking": bool(pick),
        }
        if not crud.user_has_recipes(session, user.id):  # type: ignore[arg-type]
            context["first_run"] = {"coffee": bool(coffees), "gear": bool(context["brewers"]) and bool(context["grinders"])}
        combo = None
        if ints["bag"]:
            bag = _owned(session, user, models.BeanBag, ints["bag"])
            line = None if gear == "pick" else crud.gear_for_bean(session, bag.bean_id)  # gear=pick: choose it afresh
            if ints["line"]:  # a recipe picked by name brings its own gear
                picked = _owned(session, user, models.RecipeLine, ints["line"])
                if picked.bean_id == bag.bean_id:
                    line = picked
            brewer = ints["brewer"] or (line.brewer_id if line else None)
            grinder = ints["grinder"] or (line.grinder_id if line else None)
            if brewer:
                _owned(session, user, models.Brewer, brewer)
            if grinder:
                _owned(session, user, models.Grinder, grinder)
            combo = (bag.id, brewer, grinder, ints["line"])
        elif pending_plan and not pick:
            combo = (pending_plan.bag_id, pending_plan.brewer_id, pending_plan.grinder_id, pending_plan.line_id)
        elif coffees and coffees[0][2] and not pick:
            bag = coffees[0][0]
            line = crud.gear_for_bean(session, bag.bean_id)
            if line:
                combo = (bag.id, line.brewer_id, line.grinder_id, line.id)
        context["combo"] = combo
        # Another coffee: pick the coffee, then one of its recipes (each on its own gear)
        context["coffee_recipes"] = {b.bean_id: _recipe_choices(session, b.bean_id) for b, _, _ in coffees}
        if combo and combo[1] and combo[2]:
            context.update(_latest_recipe_context(session, combo[0], combo[1], combo[2], user.id, combo[3]))  # type: ignore[arg-type]
            if context.get("bag"):
                context["planned_bag_remaining"] = crud.get_remaining_quantity(session, context["bag"])
        elif combo:
            context["bag"] = session.get(models.BeanBag, combo[0])
        # Just saved a new version on Try a change: say what changed, offer to brew it
        saved_id = request.query_params.get("saved", "")
        if saved_id.isdigit():
            recipe = session.get(models.Recipe, int(saved_id))
            if recipe and _owner_id(session, recipe) == user.id:
                delta = session.exec(select(models.Delta).where(models.Delta.to_recipe_id == recipe.id)).first()
                context["saved"] = {"recipe": recipe, "version": crud.version_number(session, recipe),
                                    "change": delta.change_label if delta else "", "why": delta.rationale if delta else ""}
        return templates.TemplateResponse("index.html", context)


@app.get("/recipes/latest", response_class=HTMLResponse)
def latest_recipe_partial(request: Request, bag_id: Optional[str] = None, brewer_id: Optional[str] = None, grinder_id: Optional[str] = None, line_id: Optional[str] = None):
    bag_id_int = int(bag_id) if bag_id and bag_id.isdigit() else None
    brewer_id_int = int(brewer_id) if brewer_id and brewer_id.isdigit() else None
    grinder_id_int = int(grinder_id) if grinder_id and grinder_id.isdigit() else None
    line_id_int = int(line_id) if line_id and line_id.isdigit() else None

    with Session(db.engine) as session:
        user = _require_user(request, session)
        if bag_id_int:
            _owned(session, user, models.BeanBag, bag_id_int)
        if brewer_id_int:
            _owned(session, user, models.Brewer, brewer_id_int)
        if grinder_id_int:
            _owned(session, user, models.Grinder, grinder_id_int)
        context = _latest_recipe_context(session, bag_id_int, brewer_id_int, grinder_id_int, user.id, line_id_int)  # type: ignore[arg-type]
        context["request"] = request
        return templates.TemplateResponse("partials/latest_recipe.html", context)


@app.get("/manage", response_class=HTMLResponse)
def manage(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        beans = crud.get_beans(session, user.id)  # type: ignore[arg-type]
        all_beans_with_bags = [
            (bean, [(bag, crud.get_remaining_quantity(session, bag)) for bag in crud.get_bags_for_bean(session, bean.id)])  # type: ignore[arg-type]
            for bean in beans
        ]
        active_beans_with_bags = [
            (bean, bags) for bean, bags in all_beans_with_bags
            if not bags or any(not bag.is_completed for bag, _ in bags)
        ]
        archived_beans_with_bags = [
            (bean, bags) for bean, bags in all_beans_with_bags
            if bags and all(bag.is_completed for bag, _ in bags)
        ]
        brewers = crud.get_brewers(session, user.id)  # type: ignore[arg-type]
        grinders = crud.get_grinders(session, user.id)  # type: ignore[arg-type]
        put_away = crud.get_brewers(session, user.id, archived=True) + crud.get_grinders(session, user.id, archived=True)  # type: ignore[operator,arg-type]
        all_users = crud.get_users(session) if user.is_admin else []
        cups, first_brew = crud.get_brew_totals(session, user.id)  # type: ignore[arg-type]
        return templates.TemplateResponse("manage.html", {
            "cups": cups,
            "first_brew": first_brew,
            "cup_price": CAFE_CUP_PRICE_INR,
            "streak": crud.streaks(crud.get_brew_days(session, user.id), datetime.now(crud.IST).date()),  # type: ignore[arg-type]
            "request": request,
            "beans_with_bags": active_beans_with_bags,
            "archived_beans_with_bags": archived_beans_with_bags,
            "brewers": brewers,
            "grinders": grinders,
            "put_away": put_away,
            "current_user": user,
            "all_users": all_users,
        })


@app.post("/settings/brew-mode")
def save_brew_settings(request: Request, show_brew_animation: Optional[str] = Form(None),
                       show_live_graph: Optional[str] = Form(None)):
    """Brew mode's switches on Manage. Unticked checkboxes send nothing."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.set_brew_settings(session, user, animation=bool(show_brew_animation), live_graph=bool(show_live_graph))
    return RedirectResponse(url="/manage#brew-mode", status_code=303)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        return templates.TemplateResponse("help.html", {"request": request, "current_user": user})


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request, bean: Optional[int] = None):
    """Coffees: a list (most recently brewed first) and one coffee's page: its bags,
    recipes, cups, photo and details. Side by side on a landscape iPad."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        entries = []
        for b in crud.get_beans(session, user.id):  # type: ignore[arg-type]
            bags = [(bag, crud.get_remaining_quantity(session, bag)) for bag in crud.get_bags_for_bean(session, b.id)]  # type: ignore[arg-type]
            open_bags = [(bag, rem) for bag, rem in bags if not bag.is_completed]
            entries.append({"bean": b, "bags": bags, "left": sum(rem for _, rem in open_bags),
                            "finished": bool(bags) and not open_bags, "last": crud.last_brewed_at(session, b.id)})  # type: ignore[arg-type]
        entries.sort(key=lambda e: (e["last"] is None, -(e["last"].timestamp() if e["last"] else 0), e["bean"].name.lower()))
        active = [e for e in entries if not e["finished"]]
        finished = [e for e in entries if e["finished"]]
        selected = next((e for e in entries if e["bean"].id == bean), None) if bean else None
        if bean and not selected:
            raise HTTPException(status_code=404, detail="Not found")
        if not selected and active:
            selected = active[0]
        detail = {}
        if selected:
            sb = selected["bean"]
            lines = crud.get_lines_for_bean(session, sb.id)  # type: ignore[arg-type]
            line_rows = []
            for line in lines:
                versions = crud.get_versions(session, line.id)  # type: ignore[arg-type]
                cups = [c for v in versions for c in crud.brews_of(session, [v.id])[v.id]]  # type: ignore[list-item,index]
                rated = [c.rating for c in cups if c.rating]
                line_rows.append({"line": line, "latest": versions[-1] if versions else None, "versions": len(versions), "cups": len(cups),
                                  "rating": round(sum(rated) / len(rated), 1) if rated else None,
                                  "brewer": session.get(models.Brewer, line.brewer_id), "grinder": session.get(models.Grinder, line.grinder_id),
                                  "has_rec": crud.line_recommendation(session, line.id) is not None})  # type: ignore[arg-type]
            # two recipes of one coffee can share a name on different gear ("Default" on the Kalita
            # and on the Switch): say which gear, so they don't look like duplicates
            names = [r["line"].name for r in line_rows]
            for r in line_rows:
                r["label"] = f'{r["line"].name} · {r["brewer"].name}' if names.count(r["line"].name) > 1 else r["line"].name
            brews = crud.get_brews_for_bean(session, sb.id)[:20]  # type: ignore[arg-type]
            detail = {"lines": line_rows, "brews": brews, "bag_to_use": crud.pick_bag(session, sb.id),  # type: ignore[arg-type]
                      "curve_ids": crud.brews_with_curves(session, [b.id for b in brews])}  # type: ignore[misc]
        return templates.TemplateResponse("browse.html", {
            "request": request, "current_user": user, "active": active, "finished": finished, "selected": selected,
            "picked": bool(bean), "brewers": crud.get_brewers(session, user.id), "grinders": crud.get_grinders(session, user.id),  # type: ignore[arg-type]
            "up_next": _up_next(session, crud.get_pending_plan(session, user.id)),  # type: ignore[arg-type]
            **detail,
        })


def _back_to(next_url: Optional[str], default: str) -> str:
    """Where a form sends you after saving: its own `next` if it's a page of ours."""
    return next_url if next_url and next_url.startswith("/") and not next_url.startswith("//") else default


@app.post("/beans")
def create_bean(request: Request, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None),
                notes: str = Form(None), initial_quantity_g: str = Form(None), roast_date: str = Form(None), next: str = Form(None)):
    """A coffee, and (with a bag size) the bag you bought, in one go."""
    grams = _parse_amount(initial_quantity_g)
    if grams is not None and not 0 < grams <= 10000:
        raise HTTPException(status_code=400, detail="The bag size should be between 1 g and 10 kg")
    with Session(db.engine) as session:
        user = _require_user(request, session)
        new_bean = crud.create_bean(session, user_id=user.id, name=name.strip(), origin=origin, roast_level=roast_level,  # type: ignore[arg-type]
                                    flavor_notes=(flavor_notes or "").strip(" ,") or None, notes=notes)
        if grams:
            crud.create_bag(session, bean_id=new_bean.id, initial_quantity_g=grams,  # type: ignore[arg-type]
                            roast_date=date_type.fromisoformat(roast_date) if roast_date else None)
        bean_id = new_bean.id
    return RedirectResponse(url=_back_to(next, f"/browse?bean={bean_id}"), status_code=303)


@app.post("/beans/{bean_id}/image")
def upload_bean_image(request: Request, bean_id: int, image: UploadFile = File(...), accent: str = Form(None), mesh: str = Form(None)):
    """Takes the JPEG and colours that static/bean_art.js prepared in the browser."""
    data = image.file.read(MAX_BEAN_IMAGE_BYTES + 1)
    if len(data) > MAX_BEAN_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="That image is too large")
    if not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="The image must be a JPEG")
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        if not crud.set_bean_image(session, bean_id, data, "image/jpeg", theme.clean_accent(accent), theme.clean_mesh(mesh)):
            raise HTTPException(status_code=404, detail="Bean not found")
    return RedirectResponse(url=f"/browse?bean={bean_id}", status_code=303)


@app.post("/beans/{bean_id}/colors")
def edit_bean_colors(
    request: Request,
    bean_id: int,
    accent: str = Form(None),
    mesh1: str = Form(None),
    mesh2: str = Form(None),
    mesh3: str = Form(None),
    mesh4: str = Form(None),
):
    """Save hand-picked colours. Sending none clears them (a photo with no real colour in it)."""
    mesh_parts = [mesh1, mesh2, mesh3, mesh4]
    accent_color = theme.clean_accent(accent)
    mesh_colors = theme.clean_mesh(",".join(part or "" for part in mesh_parts))
    if (accent and not accent_color) or (any(mesh_parts) and not mesh_colors):
        raise HTTPException(status_code=400, detail="Colours must be #rrggbb")
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        if not crud.set_bean_colors(session, bean_id, accent_color, mesh_colors):
            raise HTTPException(status_code=404, detail="Bean not found")
    return RedirectResponse(url=f"/browse?bean={bean_id}", status_code=303)


@app.post("/beans/{bean_id}/image/delete")
def delete_bean_image(request: Request, bean_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.delete_bean_image(session, bean_id)
    return RedirectResponse(url=f"/browse?bean={bean_id}", status_code=303)


@app.get("/beans/{bean_id}/image")
def bean_image(bean_id: int, request: Request):
    with Session(db.engine) as session:
        _owned(session, _require_user(request, session), models.Bean, bean_id)
        image = session.get(models.BeanImage, bean_id)
        if not image:
            raise HTTPException(status_code=404, detail="No photo for this bean")
        # image URLs carry ?v=<image_version>, so a new upload gets a new URL
        return Response(content=image.data, media_type=image.content_type,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.post("/bags")
def create_bag(
    request: Request,
    bean_id: int = Form(...),
    initial_quantity_g: float = Form(...),
    roast_date: str = Form(None),
    purchase_date: str = Form(None),
    low_threshold_g: float = Form(50.0),
    is_frozen: bool = Form(False),
    frozen_date: str = Form(None),
    notes: str = Form(None),
):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.create_bag(
            session,
            bean_id=bean_id,
            initial_quantity_g=initial_quantity_g,
            roast_date=date_type.fromisoformat(roast_date) if roast_date else None,
            purchase_date=date_type.fromisoformat(purchase_date) if purchase_date else None,
            low_threshold_g=low_threshold_g,
            is_frozen=is_frozen,
            frozen_date=date_type.fromisoformat(frozen_date) if frozen_date else None,
            notes=notes,
        )
    return RedirectResponse(url=f"/browse?bean={bean_id}", status_code=303)


@app.post("/beans/{bean_id}/edit")
def edit_bean(request: Request, bean_id: int, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.update_bean(session, bean_id, name=name, origin=origin or None, roast_level=roast_level or None, flavor_notes=flavor_notes or None, notes=notes or None)
    return RedirectResponse(url=f"/browse?bean={bean_id}", status_code=303)


@app.post("/beans/{bean_id}/delete")
def delete_bean(request: Request, bean_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.delete_bean(session, bean_id)
    return RedirectResponse(url="/browse", status_code=303)


@app.post("/bags/{bag_id}/edit")
def edit_bag(
    request: Request,
    bag_id: int,
    initial_quantity_g: float = Form(...),
    roast_date: str = Form(None),
    purchase_date: str = Form(None),
    low_threshold_g: float = Form(50.0),
    is_frozen: bool = Form(False),
    frozen_date: str = Form(None),
    notes: str = Form(None),
):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag_bean = _owned(session, user, models.BeanBag, bag_id).bean_id
        crud.update_bag(
            session, bag_id,
            initial_quantity_g=initial_quantity_g,
            roast_date=date_type.fromisoformat(roast_date) if roast_date else None,
            purchase_date=date_type.fromisoformat(purchase_date) if purchase_date else None,
            low_threshold_g=low_threshold_g,
            is_frozen=is_frozen,
            frozen_date=date_type.fromisoformat(frozen_date) if frozen_date else None,
            notes=notes or None,
        )
    return RedirectResponse(url=f"/browse?bean={bag_bean}", status_code=303)


@app.post("/bags/{bag_id}/complete")
def complete_bag(request: Request, bag_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag_bean = _owned(session, user, models.BeanBag, bag_id).bean_id
        crud.complete_bag(session, bag_id)
    return RedirectResponse(url=f"/browse?bean={bag_bean}", status_code=303)


@app.post("/bags/{bag_id}/delete")
def delete_bag(request: Request, bag_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag_bean = _owned(session, user, models.BeanBag, bag_id).bean_id
        crud.delete_bag(session, bag_id)
    return RedirectResponse(url=f"/browse?bean={bag_bean}", status_code=303)


@app.post("/brewers/{brewer_id}/edit")
def edit_brewer(request: Request, brewer_id: int, name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Brewer, brewer_id)
        crud.update_brewer(session, brewer_id, name=name, method=method or None, notes=notes or None)
    return RedirectResponse(url="/manage#gear", status_code=303)


@app.post("/brewers/{brewer_id}/delete")
def delete_brewer(request: Request, brewer_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Brewer, brewer_id)
        crud.delete_brewer(session, brewer_id)
    return RedirectResponse(url="/manage#gear", status_code=303)


@app.post("/grinders/{grinder_id}/edit")
def edit_grinder(request: Request, grinder_id: int, name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Grinder, grinder_id)
        crud.update_grinder(session, grinder_id, name=name, notes=notes or None)
    return RedirectResponse(url="/manage#gear", status_code=303)


@app.post("/grinders/{grinder_id}/delete")
def delete_grinder(request: Request, grinder_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Grinder, grinder_id)
        crud.delete_grinder(session, grinder_id)
    return RedirectResponse(url="/manage#gear", status_code=303)


@app.post("/{kind}/{item_id}/archive")
def archive_gear(request: Request, kind: str, item_id: int, archived: str = Form("1")):
    """Put a brewer or grinder away (out of the pickers, its recipes and cups kept), or bring it back."""
    model = {"brewers": models.Brewer, "grinders": models.Grinder}.get(kind)
    with Session(db.engine) as session:
        user = _require_user(request, session)  # sign-in first, like every route
        if not model:
            raise HTTPException(status_code=404, detail="Not found")
        item = _owned(session, user, model, item_id)
        item.archived = archived == "1"
        session.add(item)
        session.commit()
    return RedirectResponse(url="/manage#gear", status_code=303)


@app.post("/brewers")
def create_brewer(request: Request, name: str = Form(...), method: str = Form(None), notes: str = Form(None), next: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_brewer(session, user_id=user.id, name=name, method=method, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url=_back_to(next, "/manage#gear"), status_code=303)


@app.post("/grinders")
def create_grinder(request: Request, name: str = Form(...), notes: str = Form(None), next: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_grinder(session, user_id=user.id, name=name, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url=_back_to(next, "/manage#gear"), status_code=303)


@app.post("/plan")
def create_plan(
    request: Request,
    bag_id: int = Form(...),
    brewer_id: int = Form(None),
    grinder_id: int = Form(None),
    notes: str = Form(None),
    line_id: int = Form(None),
    suggested_param: str = Form(None),
    suggested_delta: str = Form(None),
    suggested_rationale: str = Form(None),
):
    suggestion = _plan_suggestion(suggested_param, suggested_delta, suggested_rationale)
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag = _owned(session, user, models.BeanBag, bag_id)
        if brewer_id:
            _owned(session, user, models.Brewer, brewer_id)
        if grinder_id:
            _owned(session, user, models.Grinder, grinder_id)
        line = session.get(models.RecipeLine, line_id) if line_id else None
        if line and line.bean_id != bag.bean_id:
            line = None
        # A named recipe brings its own gear; anything chosen explicitly wins
        brewer_id = brewer_id or (line.brewer_id if line else None)
        grinder_id = grinder_id or (line.grinder_id if line else None)
        if not brewer_id or not grinder_id:
            raise HTTPException(status_code=400, detail="Choose a brewer and grinder")
        if line and (line.brewer_id, line.grinder_id) != (brewer_id, grinder_id):
            line = None  # different gear: fall back to that combination's default recipe
        # The change to try is kept on the recipe (the one planned, or the gear's default), so it
        # outlasts the plan. Only when the recipe has no Next time note of its own: that always wins.
        target = line or next(iter(crud.get_lines_for_combo(session, bag.bean_id, brewer_id, grinder_id)), None)
        if suggestion and target and not crud.line_recommendation(session, target.id):  # type: ignore[arg-type]
            crud.set_next_change(session, target, suggestion["suggested_param"], suggestion["suggested_delta"], suggestion["suggested_rationale"])
        crud.create_plan(session, user_id=user.id, bag_id=bag_id, brewer_id=brewer_id, grinder_id=grinder_id, notes=notes or None, line_id=line.id if line else None)  # type: ignore[arg-type,union-attr]
    return RedirectResponse(url="/", status_code=303)


@app.post("/lines/{line_id}/next")
def set_next_change(request: Request, line_id: int, suggested_param: str = Form(None), suggested_delta: str = Form(None),
                    suggested_rationale: str = Form(None), next: str = Form(None)):
    """Set (or, with no setting, clear) a named recipe's planned change."""
    suggestion = _plan_suggestion(suggested_param, suggested_delta, suggested_rationale)
    if suggestion and suggestion["suggested_param"] != "recipe_text" and not suggestion["suggested_delta"]:
        raise HTTPException(status_code=400, detail="Set how much to change it by: an amount other than 0")
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        crud.set_next_change(session, line, suggestion.get("suggested_param"), suggestion.get("suggested_delta"), suggestion.get("suggested_rationale"))
    return RedirectResponse(url=_back_to(next, "/"), status_code=303)


SUGGESTABLE_PARAMS = ("dose_g", "water_ml", "temp_c", "grind_size", "recipe_text")


def _plan_suggestion(param: Optional[str], delta: Optional[str], rationale: Optional[str]) -> dict:
    """The change to try on a scheduled brew, from the schedule form; {} for none."""
    param = (param or "").strip()
    if not param:
        return {}
    if param not in SUGGESTABLE_PARAMS:
        raise HTTPException(status_code=400, detail="Unknown parameter to change")
    amount = None
    if delta and delta.strip() and param != "recipe_text":
        try:
            amount = float(delta.strip().replace("\u2212", "-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="The amount to change by must be a number")
    return {"suggested_param": param, "suggested_delta": amount,
            "suggested_rationale": (rationale or "").strip() or None}


@app.post("/lines/{line_id}/copy")
def copy_line(request: Request, line_id: int, bean_id: int = Form(...), brewer_id: int = Form(...),
              grinder_id: int = Form(...), bag_id: int = Form(None), grind_size: str = Form(None)):
    """Copy a named recipe's current version onto another coffee and gear, as its version 1."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        source = _owned(session, user, models.RecipeLine, line_id)
        _owned(session, user, models.Bean, bean_id)
        _owned(session, user, models.Brewer, brewer_id)
        grinder = _owned(session, user, models.Grinder, grinder_id)
        bag = _owned(session, user, models.BeanBag, bag_id) if bag_id else crud.pick_bag(session, bean_id)
        grind = (grind_size or "").strip() or None
        if grinder_id != source.grinder_id and not grind:
            # a grind setting means nothing on another grinder
            if not _is_pre_ground(grinder):
                raise HTTPException(status_code=400, detail=f"Set the grind for the {grinder.name}: the number from another grinder won't match.")
            grind = "pre-ground"
        new_line = crud.copy_line(session, source, bean_id, brewer_id, grinder_id, grind)
        target = f"/?bag_id={bag.id}&brewer_id={brewer_id}&grinder_id={grinder_id}&line_id={new_line.id}" if bag else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/lines/{line_id}/rename")
def rename_line(request: Request, line_id: int, name: str = Form(...)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.RecipeLine, line_id)
        line = session.get(models.RecipeLine, line_id)
        if not line:
            raise HTTPException(status_code=404, detail="Recipe not found")
        name = name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name can't be empty")
        if crud.line_name_taken(session, line.bean_id, line.brewer_id, line.grinder_id, name, exclude_line_id=line_id):
            raise HTTPException(status_code=400, detail=f'There is already a recipe called "{name}" for this combination')
        crud.rename_line(session, line_id, name)
    return RedirectResponse(url="/", status_code=303)


@app.get("/lines/{line_id}/brew", response_class=HTMLResponse)
def brew_mode(line_id: int, request: Request, bag_id: Optional[int] = None, plan_id: Optional[int] = None,
              recipe_id: Optional[int] = None, try_change: int = Query(0, alias="try")):
    """Brew mode: the named recipe's current version in large type, with a
    timer that follows the times written in the method, and the log form."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        older_version = None
        if recipe_id and latest and recipe_id != latest.id:  # "Brew it once": an older version of this recipe
            older = session.get(models.Recipe, recipe_id)
            if not older or older.line_id != line_id:
                raise HTTPException(status_code=404, detail="Recipe not found")
            older_version = (crud.version_number(session, older), crud.version_number(session, latest))
            latest = older
        if not latest or not latest.bean or not latest.grinder:
            raise HTTPException(status_code=404, detail="Recipe not found")
        # Logging needs a bag of this bean; a stale or foreign one just hides the form
        bag = session.get(models.BeanBag, bag_id) if bag_id else None
        if bag and bag.bean_id != line.bean_id:
            bag = None
        plan = session.get(models.PlannedBrew, plan_id) if plan_id else None
        if not (plan and bag and plan.user_id == user.id and plan.bag_id == bag.id
                and (plan.brewer_id, plan.grinder_id) == (line.brewer_id, line.grinder_id)
                and plan.line_id in (None, line.id)):
            plan = None
        # "Brew with change": the Next time note (or the plan's change) applied for this brew
        # only; it becomes a new version when the cup is logged, not before
        trial = None
        if try_change and not older_version:
            rec_brew = crud.line_recommendation(session, line_id)
            rec = (_Rec(rec_brew.recommended_param, rec_brew.recommended_delta, rec_brew.recommended_rationale, False) if rec_brew  # type: ignore[arg-type]
                   else _Rec(line.next_param, line.next_delta, line.next_rationale, True) if line.next_param else None)  # type: ignore[arg-type]
            trial = _applied_change(latest, rec)
            if trial:
                trial["version"] = crud.version_number(session, latest) + 1
                latest = _Shown(latest, {trial["param"]: trial["value"]})  # type: ignore[assignment]
        return templates.TemplateResponse("brew.html", {
            "trial": trial,
            "request": request,
            "current_user": user,
            "line": line,
            "latest": latest,
            "title": export.title(line, latest.bean),
            "ratio": export.ratio(latest),
            "steps": brew.parse_steps(latest.recipe_text),
            "prep": brew.prep_text(latest.recipe_text),
            "animation": brew.animation_data(latest.recipe_text, latest.brewer.name, latest.brewer.method)
                         if user.show_brew_animation else "",
            "live_graph": user.show_live_graph,
            "last_curve": _last_curve(session, line, latest),
            "bag": bag,
            "plan_id": plan.id if plan and not older_version else None,
            "older_version": older_version,
            "bag_left": crud.get_remaining_quantity(session, bag) if bag else None,
        })


def _last_curve(session: Session, line: models.RecipeLine, latest: models.Recipe) -> str:
    """The newest saved curve of this named recipe, as JSON for brew mode to lay under
    the graph after Stop ("" if there is none)."""
    last = next(iter(crud.line_brews_with_curves(session, line.id)), None)  # type: ignore[arg-type]
    if last is None:
        return ""
    curve = crud.get_curve(session, last.id)  # type: ignore[arg-type]
    label = _brew_label(last, session.get(models.Recipe, last.recipe_id), latest)
    return json.dumps({**curve, "label": "Last brew, " + label}, separators=(",", ":"))  # type: ignore[dict-item]


# Steps and limits for each setting on Try a change: (step, min, max)
CHANGE_LIMITS = {"dose_g": (0.5, 5, 60), "water_ml": (10, 50, 1000), "temp_c": (1, 70, 100)}


def _grind_step(value: str) -> Optional[float]:
    """How far − and + move a grind setting: 1 for "22", 0.5 for "2.5"; None if it isn't a number."""
    try:
        float(value)
    except (TypeError, ValueError):
        return None
    return 1 if "." not in value else 0.5 if value.split(".")[1] in ("0", "5") else 0.1


@app.get("/lines/{line_id}/change", response_class=HTMLResponse)
def change_recipe_page(request: Request, line_id: int, bag_id: Optional[int] = None, plan_id: Optional[int] = None,
                       method: int = 0, actual: Optional[int] = None):
    """Try a change: tap the one setting to change, set its new value, say why."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        if not latest:
            raise HTTPException(status_code=404, detail="Not found")
        bag = session.get(models.BeanBag, bag_id) if bag_id else None
        if bag and (_owner_id(session, bag) != user.id or bag.bean_id != line.bean_id):
            bag = None
        if not bag:
            bags = [b for b in crud.get_bags_for_bean(session, line.bean_id) if not b.is_completed]
            bag = bags[0] if bags else None
        plan = crud.get_pending_plan(session, user.id)  # type: ignore[arg-type]
        plan = plan if plan and plan_id == plan.id and plan.bag_id == (bag.id if bag else None) else None
        rec = None
        rec_brew = crud.line_recommendation(session, line_id)
        if rec_brew:
            rec = _Rec(rec_brew.recommended_param, rec_brew.recommended_delta, rec_brew.recommended_rationale, False)  # type: ignore[arg-type]
        elif line.next_param:
            rec = _Rec(line.next_param, line.next_delta, line.next_rationale, True)
        return templates.TemplateResponse("change_recipe.html", {
            "request": request, "current_user": user, "line": line, "latest": latest, "bag": bag, "plan": plan,
            "rec": rec, "version": crud.version_number(session, latest),
            "deltas": crud.get_recent_deltas(session, line_id, limit=5),
            "limits": CHANGE_LIMITS, "grind_step": _grind_step(latest.grind_size),
            "start_with_method": bool(method), "actuals": _actual_timings(session, user, actual, latest),
            "just_logged": actual,
        })


def _actual_timings(session: Session, user: models.User, brew_id: Optional[int], recipe: models.Recipe) -> str:
    """What happened in a brew, step by step, from its scale curve (JSON for the step editor):
    when each step's pour really started and when it reached its target. "" without a curve."""
    if not brew_id:
        return ""
    found = session.get(models.Brew, brew_id)
    if not found or _owner_id(session, found) != user.id:
        return ""
    curve = session.get(models.BrewCurve, brew_id)
    if not curve:
        return ""
    return json.dumps(brew.actual_timings(recipe.recipe_text, json.loads(curve.samples)))


@app.get("/lines/{line_id}/versions", response_class=HTMLResponse)
def versions_page(request: Request, line_id: int, bag_id: Optional[int] = None, compare: Optional[int] = None):
    """A named recipe's versions, newest first: what each changed, its cups and ratings;
    compare one with the current version, brew an old one once, undo or fix the newest."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        versions = crud.get_versions(session, line_id)
        if not versions:
            raise HTTPException(status_code=404, detail="Not found")
        cups = crud.brews_of(session, [v.id for v in versions])  # type: ignore[misc]
        rows = []
        for n, v in enumerate(versions, start=1):
            rated = [b.rating for b in cups[v.id] if b.rating]  # type: ignore[index]
            rows.append({"n": n, "recipe": v, "delta": crud.delta_into(session, v.id), "cups": cups[v.id],  # type: ignore[arg-type,index]
                         "rating": round(sum(rated) / len(rated), 1) if rated else None})
        best = max((r for r in rows if r["rating"]), key=lambda r: (r["rating"], r["n"]), default=None)
        current = rows[-1]
        other = next((r for r in rows if r["recipe"].id == compare), None) if compare else None
        bag = session.get(models.BeanBag, bag_id) if bag_id else None
        if not bag or _owner_id(session, bag) != user.id or bag.bean_id != line.bean_id:
            bag = crud.pick_bag(session, line.bean_id)
        return templates.TemplateResponse("versions.html", {
            "request": request, "current_user": user, "line": line, "rows": list(reversed(rows)), "current": current,
            "best": best, "other": other, "bag": bag, "fields": ("dose_g", "grind_size", "water_ml", "temp_c"),
            "curve_ids": crud.brews_with_curves(session, [b.id for r in rows for b in r["cups"]]),
        })


def _newest_version(session: Session, user: models.User, recipe_id: int) -> models.Recipe:
    recipe = _owned(session, user, models.Recipe, recipe_id)
    if crud.get_latest_recipe(session, recipe.line_id).id != recipe.id:  # type: ignore[arg-type,union-attr]
        raise HTTPException(status_code=400, detail="Only the newest version can be fixed or deleted")
    return recipe


@app.post("/lines/{line_id}/undo")
def undo_last_change(request: Request, line_id: int, bag_id: int = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.RecipeLine, line_id)
        new = crud.undo_last_change(session, line_id)
        if not new:
            raise HTTPException(status_code=400, detail="The first version has no change to undo")
        saved_id = new.id
    return RedirectResponse(url=f"/?saved={saved_id}", status_code=303)


@app.post("/recipes/{recipe_id}/fix")
def fix_version(request: Request, recipe_id: int, value: str = Form(None), rationale: str = Form(None),
                dose_g: str = Form(None), water_ml: str = Form(None), temp_c: str = Form(None), grind_size: str = Form(None)):
    """Correct the newest version in place: its own change (or, for a first version, any
    value) and its reason. It must stay exactly one change from the version before."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        recipe = _newest_version(session, user, recipe_id)
        delta = crud.delta_into(session, recipe.id)  # type: ignore[arg-type]
        values: dict = {}
        if delta and value is not None and delta.changed_param != "recipe_text":
            raw = {delta.changed_param: value}
        else:
            raw = {k: v for k, v in (("dose_g", dose_g), ("water_ml", water_ml), ("temp_c", temp_c), ("grind_size", grind_size)) if v is not None}
            if delta:
                raw = {}  # a later version's other values belong to the version before it
        for name, v in raw.items():
            v = v.strip()
            if name == "grind_size":
                if not v:
                    raise HTTPException(status_code=400, detail="Grind can't be empty")
                values[name] = v
            else:
                values[name] = _parse_amount(v)
                if values[name] is None:
                    raise HTTPException(status_code=400, detail=f"{words.label(name)} can't be empty")
        if delta:
            parent = session.get(models.Recipe, delta.from_recipe_id)
            valid, changed = crud.validate_one_parameter_delta(parent, {**{f: getattr(recipe, f) for f in crud.VALUE_FIELDS}, **values})  # type: ignore[arg-type]
            if not valid:
                raise HTTPException(status_code=400, detail="That would make this version the same as the one before. Delete it instead, if it has no cups.")
        crud.fix_version(session, recipe, values, (rationale or "").strip() or None)
        line_id = recipe.line_id
    return RedirectResponse(url=f"/lines/{line_id}/versions", status_code=303)


@app.post("/recipes/{recipe_id}/reason")
def edit_version_reason(request: Request, recipe_id: int, rationale: str = Form(None)):
    """The reason for any version's change can be reworded; its values can't (later versions build on them)."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        recipe = _owned(session, user, models.Recipe, recipe_id)
        delta = crud.delta_into(session, recipe.id)  # type: ignore[arg-type]
        if not delta:
            raise HTTPException(status_code=400, detail="The first version has no change to explain")
        delta.rationale = (rationale or "").strip() or None
        session.add(delta)
        session.commit()
        line_id = recipe.line_id
    return RedirectResponse(url=f"/lines/{line_id}/versions", status_code=303)


@app.post("/recipes/{recipe_id}/delete")
def delete_version(request: Request, recipe_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        recipe = _newest_version(session, user, recipe_id)
        if not recipe.previous_recipe_id:
            raise HTTPException(status_code=400, detail="This is the recipe's only version: delete the recipe instead")
        if crud.brews_of(session, [recipe.id])[recipe.id]:  # type: ignore[list-item,index]
            raise HTTPException(status_code=400, detail="Cups were brewed with this version, so it stays. Fix it, or undo its change.")
        line_id = recipe.line_id
        crud.delete_version(session, recipe)
    return RedirectResponse(url=f"/lines/{line_id}/versions", status_code=303)


@app.get("/four-six", response_class=HTMLResponse)
def four_six_page(request: Request, bag_id: int, brewer_id: int, grinder_id: int):
    """Build a 4:6 recipe (the calculator's rules) as a coffee's starting recipe on this gear."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag = _owned(session, user, models.BeanBag, bag_id)
        brewer = _owned(session, user, models.Brewer, brewer_id)
        grinder = _owned(session, user, models.Grinder, grinder_id)
        return templates.TemplateResponse("four_six.html", {
            "request": request, "current_user": user, "bag": bag, "brewer": brewer, "grinder": grinder,
            "roast_temps": four_six.ROAST_TEMPS, "roast_names": four_six.ROAST_NAMES, "bodies": four_six.BODIES,
            "has_lines": bool(crud.get_lines_for_combo(session, bag.bean_id, brewer_id, grinder_id)),
            "pre_ground": _is_pre_ground(grinder), "shape": brew.brewer_shape(brewer.name, brewer.method),
        })


@app.post("/four-six")
def four_six_create(request: Request, bag_id: int = Form(...), brewer_id: int = Form(...), grinder_id: int = Form(...),
                    coffee: str = Form(...), ratio: str = Form(...), temp_c: str = Form(...), taste: str = Form("0"),
                    pours: str = Form("3"), grind_size: str = Form(None), name: str = Form(None)):
    """Save the 4:6 recipe as version 1 of a new named recipe; the server builds the steps."""
    dose, water_ratio, temp = _parse_amount(coffee), _parse_amount(ratio), _parse_amount(temp_c)
    try:
        taste_f, body = float(taste), int(pours)
    except ValueError:
        raise HTTPException(status_code=400, detail="Taste and strength must be one of the choices")
    lo, hi = four_six.LIMITS["coffee"]
    if dose is None or not lo <= dose <= hi:
        raise HTTPException(status_code=400, detail=f"Coffee should be between {lo:g} and {hi:g} g")
    lo, hi = four_six.LIMITS["ratio"]
    if water_ratio is None or not lo <= water_ratio <= hi:
        raise HTTPException(status_code=400, detail=f"The ratio should be between 1:{lo:g} and 1:{hi:g}")
    lo, hi = four_six.LIMITS["temp"]
    if temp is None or not lo <= temp <= hi:
        raise HTTPException(status_code=400, detail=f"The water should be between {lo:g} and {hi:g} °C")
    if not -1 <= taste_f <= 1 or body not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="Taste and strength must be within their sliders")
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bag = _owned(session, user, models.BeanBag, bag_id)
        brewer = _owned(session, user, models.Brewer, brewer_id)
        grinder = _owned(session, user, models.Grinder, grinder_id)
        grind = "pre-ground" if _is_pre_ground(grinder) else (grind_size or "").strip()
        if not grind:
            raise HTTPException(status_code=400, detail=f"Set the grind for the {grinder.name}: coarse, about French-press coarse")
        p = four_six.plan(dose, water_ratio, taste_f, body)
        label, n = (name or "").strip() or "4:6", 2
        base = label
        while crud.line_name_taken(session, bag.bean_id, brewer_id, grinder_id, label):
            label, n = f"{base} {n}", n + 1
        line = crud.create_line(session, bag.bean_id, brewer_id, grinder_id, label)
        crud.create_recipe(session, bean_id=bag.bean_id, brewer_id=brewer_id, grinder_id=grinder_id, line_id=line.id,  # type: ignore[arg-type]
                           dose_g=dose, water_ml=p["water"], temp_c=temp, grind_size=grind,
                           recipe_text=four_six.steps_text(dose, temp, p, brew.brewer_shape(brewer.name, brewer.method)))
        target = f"/?bag_id={bag.id}&brewer_id={brewer_id}&grinder_id={grinder_id}&line_id={line.id}"
    return RedirectResponse(url=target, status_code=303)


@app.get("/lines/{line_id}/tidy", response_class=HTMLResponse)
def tidy_line(line_id: int, request: Request, bag_id: Optional[int] = None):
    """Suggest steps for a free-text method, for the person to correct and save."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        back_url = f"/lines/{line_id}/brew?bag_id={bag_id}" if bag_id else "/"
        if not latest or not latest.bean:
            raise HTTPException(status_code=404, detail="Recipe not found")
        if not brew.needs_tidy(latest.recipe_text):
            return RedirectResponse(url=back_url, status_code=303)
        return templates.TemplateResponse("tidy_recipe.html", {
            "request": request,
            "current_user": user,
            "line": line,
            "latest": latest,
            "title": export.title(line, latest.bean),
            "suggestion": brew.suggest_steps(latest.recipe_text),
            "bag_id": bag_id,
            "back_url": back_url,
        })


@app.post("/lines/{line_id}/tidy")
def save_tidied_line(line_id: int, request: Request, recipe_text: str = Form(""), bag_id: int = Form(None)):
    """Save tidied steps as a new version, recorded as a recipe_text change."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        if not latest:
            raise HTTPException(status_code=404, detail="Recipe not found")
        text = "\n".join(line_text.rstrip() for line_text in recipe_text.splitlines()).strip()
        if not brew.is_standard(text):
            raise HTTPException(status_code=400, detail='Each line must look like "1:40 — Pour (to 200g)", with optional "Prep:" lines first')
        if text != "\n".join((latest.recipe_text or "").splitlines()).strip():
            tidied = crud.create_recipe(
                session, bean_id=latest.bean_id, brewer_id=latest.brewer_id, grinder_id=latest.grinder_id,
                line_id=line_id, dose_g=latest.dose_g, water_ml=latest.water_ml, temp_c=latest.temp_c,
                grind_size=latest.grind_size, recipe_text=text, previous_recipe_id=latest.id,
                keeps_next_change=True,  # tidying only reformats: the planned change is still to come
            )
            crud.create_delta(session, from_recipe_id=latest.id, to_recipe_id=tidied.id, changed_param="recipe_text",  # type: ignore[arg-type]
                              delta_amount=0.0, rationale=brew.TIDY_RATIONALE)
        bag = session.get(models.BeanBag, bag_id) if bag_id else None
        destination = f"/lines/{line_id}/brew?bag_id={bag.id}" if bag and bag.bean_id == line.bean_id else "/"
    return RedirectResponse(url=destination, status_code=303)


@app.get("/lines/{line_id}/export.md")
def export_line(line_id: int, request: Request, download: bool = False):
    """The named recipe as Markdown: shown as plain text (to copy into a chat),
    or with ?download=1 as a .md file."""
    with Session(db.engine) as session:
        line = _owned(session, _require_user(request, session), models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        if not latest or not latest.bean:
            raise HTTPException(status_code=404, detail="Recipe not found")
        text = export.to_markdown(line, latest, crud.get_line_history(session, line_id))
        if download:
            return PlainTextResponse(text, media_type="text/markdown; charset=utf-8", headers={
                "Content-Disposition": f'attachment; filename="{export.filename(line, latest.bean)}"'})
        return PlainTextResponse(text)


@app.get("/lines/{line_id}/share-image", response_class=HTMLResponse)
def share_image(line_id: int, request: Request, curve: Optional[int] = None, notes: Optional[int] = None,
                format: Optional[str] = None):
    """The named recipe as an Instagram-sized image, drawn in the browser from
    export.card_data (the server has no imaging library). `curve=1` adds the weight
    curve of the newest brew of this version that has one; `notes=1` offers this
    recipe's tasting notes to put one on the card (picked and trimmed in the browser,
    so the text never goes into a URL); both are off unless asked for.
    `format=story` draws it 9:16 instead of 4:5."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
        if not latest or not latest.bean:
            raise HTTPException(status_code=404, detail="Recipe not found")
        last_curve = crud.latest_curve_for_recipe(session, latest.id)  # type: ignore[arg-type]
        noted = crud.line_brews_with_notes(session, line_id)
        offered = [{
            "when": _brew_label(b, session.get(models.Recipe, b.recipe_id), latest),
            "text": crud.tasting_note(b.notes),
            "rating": b.rating,
        } for b in noted] if notes else []
        story = format == "story"
        state = {"curve": bool(curve and last_curve), "notes": bool(offered), "story": story}

        def link(**change) -> str:  # this page with one thing switched
            on = {**state, **change}
            query = "&".join(p for p, v in (("curve=1", on["curve"]), ("notes=1", on["notes"]), ("format=story", on["story"])) if v)
            return f"/lines/{line_id}/share-image" + (f"?{query}" if query else "")

        return templates.TemplateResponse("share_image.html", {
            "request": request,
            "current_user": user,
            "line": line,
            "title": export.title(line, latest.bean),
            "has_curve": last_curve is not None,
            "has_notes": bool(noted),
            "state": state,
            "link": link,
            "card": json.dumps(export.card_data(line, latest, last_curve if state["curve"] else None, offered, story)),
        })


def _curve_page_data(curve: dict, recipe: models.Recipe) -> dict:
    """A curve plus the step targets of the version it was brewed with."""
    return {**curve, "targets": export.targets(recipe)}


@app.get("/brews/{brew_id}/graph", response_class=HTMLResponse)
def brew_graph(brew_id: int, request: Request, compare: Optional[int] = None):
    """A logged brew's weight and flow curves, optionally over another brew of the same
    named recipe, with PNG and CSV downloads."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        this = _owned(session, user, models.Brew, brew_id)
        curve = crud.get_curve(session, brew_id)
        recipe = session.get(models.Recipe, this.recipe_id)
        if curve is None or not recipe or not recipe.bean:
            raise HTTPException(status_code=404, detail="This brew has no graph")
        others = [b for b in crud.line_brews_with_curves(session, recipe.line_id) if b.id != brew_id] if recipe.line_id else []  # type: ignore[arg-type]
        compare_brew = None
        if compare is None:  # by default, the one brewed just before it
            compare_brew = next((b for b in others if (b.brewed_at, b.id) < (this.brewed_at, this.id)), None)
        elif compare:  # compare=0 means "compare with nothing"
            compare_brew = next((b for b in others if b.id == compare), None)
            if compare_brew is None:
                raise HTTPException(status_code=404, detail="Not found")
        compare_data = None
        if compare_brew:
            compare_recipe = session.get(models.Recipe, compare_brew.recipe_id)
            compare_data = {**crud.get_curve(session, compare_brew.id),  # type: ignore[dict-item]
                            "label": _brew_label(compare_brew, compare_recipe, recipe)}
        line = session.get(models.RecipeLine, recipe.line_id) if recipe.line_id else None
        return templates.TemplateResponse("brew_graph.html", {
            "request": request,
            "current_user": user,
            "brew": this,
            "recipe": recipe,
            "title": export.title(line, recipe.bean) if line else recipe.bean.name,
            "others": [(b, _brew_label(b, session.get(models.Recipe, b.recipe_id), recipe)) for b in others],
            "compare_brew": compare_brew,
            "graph": json.dumps({
                "brew": {**_curve_page_data(curve, recipe), "label": _brew_label(this, recipe, recipe)},
                "compare": compare_data,
                "filename": f"brew-{brew_id}-{this.brewed_at:%Y-%m-%d}.png",
                "title": export.title(line, recipe.bean) if line else recipe.bean.name,
            }),
        })


_LABEL_PARAMS = (("dose", "dose_g"), ("water", "water_ml"), ("temp", "temp_c"), ("grind", "grind_size"))


def _brew_label(b: models.Brew, recipe: Optional[models.Recipe], current: models.Recipe) -> str:
    """'12 Nov, 08:14' (India time), plus what differed from the version being viewed,
    which by the one-parameter rule is usually exactly one thing ("grind 12")."""
    when = crud.local_time(b.brewed_at)
    label = f"{when.day} {when:%b, %H:%M}"
    if recipe and recipe.id != current.id:
        changed = [f"{name} {getattr(recipe, attr)}" for name, attr in _LABEL_PARAMS
                   if getattr(recipe, attr) != getattr(current, attr)]
        if recipe.recipe_text != current.recipe_text:
            changed.append("other method")
        if changed:
            label += " (" + ", ".join(changed) + ")"
    return label


@app.get("/brews/{brew_id}/curve.csv")
def brew_curve_csv(brew_id: int, request: Request):
    """The raw readings, for a spreadsheet."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        this = _owned(session, user, models.Brew, brew_id)
        curve = crud.get_curve(session, brew_id)
        if curve is None:
            raise HTTPException(status_code=404, detail="This brew has no graph")
        lines = ["seconds,grams,grams_per_second"] + [
            f"{t:g},{g:g},{f:g}" for t, g, f in zip(curve["t"], curve["g"], curve["f"])
        ]
        return Response("\n".join(lines) + "\n", media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="brew-{brew_id}-{this.brewed_at:%Y-%m-%d}.csv"',
        })


@app.post("/lines/{line_id}/delete")
def delete_line(request: Request, line_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.RecipeLine, line_id)
        crud.delete_line(session, line_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/plan/{plan_id}/cancel")
def cancel_plan(plan_id: int, request: Request):
    with Session(db.engine) as session:
        _owned(session, _require_user(request, session), models.PlannedBrew, plan_id)
        crud.delete_plan(session, plan_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/brews")
def create_brew(
    request: Request,
    recipe_id: int = Form(...),
    bag_id: int = Form(...),
    notes: str = Form(None),
    rating: str = Form(None),
    recommended_param: str = Form(None),
    recommended_delta: str = Form(None),
    recommended_rationale: str = Form(None),
    planned_brew_id: int = Form(None),
    curve: str = Form(None),
    then: str = Form(None),
    finish_bag: str = Form(None),
    try_param: str = Form(None),
    try_value: str = Form(None),
    try_rationale: str = Form(None),
):
    rec_delta: Optional[float] = None
    if recommended_delta and recommended_delta.strip():
        try:
            rec_delta = float(recommended_delta)
        except ValueError:
            pass
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Recipe, recipe_id)
        _owned(session, user, models.BeanBag, bag_id)
        if planned_brew_id:
            _owned(session, user, models.PlannedBrew, planned_brew_id)
        if try_param:  # brewed with the Next time change: that change becomes the next version now
            base = session.get(models.Recipe, recipe_id)
            if try_param not in ("dose_g", "water_ml", "temp_c", "grind_size") or crud.get_latest_recipe(session, base.line_id).id != base.id:  # type: ignore[union-attr,arg-type]
                raise HTTPException(status_code=400, detail="That change can't be saved: the recipe has a newer version now.")
            value = (try_value or "").strip() if try_param == "grind_size" else _parse_amount(try_value)
            if value in (None, ""):
                raise HTTPException(status_code=400, detail="The change to save is missing its value.")
            saved = crud.save_variation(session, base, try_param, value, (try_rationale or "").strip() or None)  # type: ignore[arg-type]
            if not saved:
                raise HTTPException(status_code=400, detail="That change is the same as the current recipe.")
            recipe_id = saved.id  # type: ignore[assignment]
        new_brew = crud.create_brew(
            session,
            recipe_id=recipe_id,
            bag_id=bag_id,
            notes=notes,
            rating=_parse_rating(rating),
            recommended_param=recommended_param or None,
            recommended_delta=rec_delta,
            recommended_rationale=recommended_rationale or None,
        )
        samples = crud.parse_curve(curve)  # brew mode's scale readings, if any
        if samples:
            crud.save_curve(session, new_brew.id, samples)  # type: ignore[arg-type]
        if planned_brew_id:
            crud.delete_plan(session, planned_brew_id)
        if finish_bag:  # the cup used the last of the bag
            crud.complete_bag(session, bag_id)
        if then == "change":  # "Save and edit the steps now", with this brew's real timings beside them
            line_id = session.get(models.Recipe, recipe_id).line_id  # type: ignore[union-attr]
            return RedirectResponse(url=f"/lines/{line_id}/change?bag_id={bag_id}&method=1&actual={new_brew.id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# A deleted cup can be put back for a couple of minutes ("Undo" on the next page).
# Kept in memory: prod runs one process, and losing it on a restart only loses the Undo.
_UNDO: dict = {}
UNDO_SECONDS = 120


def _parse_amount(value: Optional[str]) -> Optional[float]:
    """A typed amount ("-1", "−0.5", "+2"); None for blank, 400 for anything else."""
    if not value or not value.strip():
        return None
    try:
        return float(value.strip().replace("\u2212", "-"))
    except ValueError:
        raise HTTPException(status_code=400, detail="The amount must be a number, like -1 or 0.5")


@app.get("/brews/{brew_id}/edit", response_class=HTMLResponse)
def edit_brew_page(request: Request, brew_id: int, cooled: int = 0):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        brew = _owned(session, user, models.Brew, brew_id)
        recipe = brew.recipe
        bags = [bag for bag in crud.get_bags_for_bean(session, recipe.bean_id)  # type: ignore[union-attr]
                if not bag.is_completed or bag.id == brew.bag_id]
        return templates.TemplateResponse("brew_edit.html", {
            "request": request, "current_user": user, "brew": brew, "recipe": recipe,
            "version": crud.version_number(session, recipe),  # type: ignore[arg-type]
            "bags": bags, "cooled": bool(cooled),
            "has_curve": bool(crud.brews_with_curves(session, [brew.id])),  # type: ignore[list-item]
        })


@app.post("/brews/{brew_id}/edit")
def edit_brew(
    request: Request,
    brew_id: int,
    notes: str = Form(None),
    rating: str = Form(None),
    recommended_param: str = Form(None),
    recommended_delta: str = Form(None),
    recommended_rationale: str = Form(None),
    bag_id: int = Form(None),
    then: str = Form(None),
):
    param = (recommended_param or "").strip() or None
    if param and param not in SUGGESTABLE_PARAMS:
        raise HTTPException(status_code=400, detail="Unknown setting to change")
    amount = _parse_amount(recommended_delta) if param and param != "recipe_text" else None
    with Session(db.engine) as session:
        user = _require_user(request, session)
        brew = _owned(session, user, models.Brew, brew_id)
        fields = {
            "notes": (notes or "").strip() or None,
            "rating": _parse_rating(rating),
            "recommended_param": param,
            "recommended_delta": amount,
            "recommended_rationale": (recommended_rationale or "").strip() or None if param else None,
        }
        if bag_id and bag_id != brew.bag_id:
            bag = _owned(session, user, models.BeanBag, bag_id)
            if bag.bean_id != brew.recipe.bean_id:  # type: ignore[union-attr]
                raise HTTPException(status_code=400, detail="That bag is a different coffee")
            fields["bag_id"] = bag_id
        crud.update_brew(session, brew, **fields)
        if then == "change":  # "Save and edit the steps now": Try a change, with this cup's timings
            return RedirectResponse(
                url=f"/lines/{brew.recipe.line_id}/change?bag_id={brew.bag_id}&method=1&actual={brew.id}",  # type: ignore[union-attr]
                status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.post("/brews/{brew_id}/delete")
def delete_brew(request: Request, brew_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        brew = _owned(session, user, models.Brew, brew_id)
        snapshot = crud.delete_brew(session, brew)
        now = time.time()
        for token in [t for t, (_, _, expires) in _UNDO.items() if expires < now]:
            del _UNDO[token]
        token = secrets.token_urlsafe(12)
        _UNDO[token] = (user.id, snapshot, now + UNDO_SECONDS)
    return RedirectResponse(url=f"/?undo={token}", status_code=303)


@app.post("/brews/undo")
def undo_delete_brew(request: Request, token: str = Form(...)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        entry = _UNDO.get(token)
        if not entry or entry[0] != user.id or entry[2] < time.time():
            raise HTTPException(status_code=400, detail="That cup can't be brought back any more")
        if not crud.restore_brew(session, entry[1]):
            raise HTTPException(status_code=400, detail="That cup's recipe or bag has been deleted since")
        del _UNDO[token]
    return RedirectResponse(url="/", status_code=303)


@app.post("/recipes")
def create_recipe(
    request: Request,
    bean_id: int = Form(...),
    brewer_id: int = Form(...),
    grinder_id: int = Form(...),
    dose_g: float = Form(...),
    water_ml: float = Form(...),
    temp_c: float = Form(...),
    grind_size: str = Form(...),
    recipe_text: str = Form(None),
    previous_recipe_id: int = Form(None),
    changed_param: str = Form(None),
    delta_amount: str = Form(None),
    rationale: str = Form(None),
    bag_id: int = Form(None),
    brew_notes: str = Form(None),
    brew_rating: str = Form(None),
    brew_recommended_param: str = Form(None),
    brew_recommended_delta: str = Form(None),
    brew_recommended_rationale: str = Form(None),
    planned_brew_id: int = Form(None),
    line_name: str = Form(None),
):
    delta_amount_f: Optional[float] = None
    if delta_amount and delta_amount.strip():
        try:
            delta_amount_f = float(delta_amount)
        except ValueError:
            pass

    brew_rec_delta: Optional[float] = None
    if brew_recommended_delta and brew_recommended_delta.strip():
        try:
            brew_rec_delta = float(brew_recommended_delta)
        except ValueError:
            pass

    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        _owned(session, user, models.Brewer, brewer_id)
        _owned(session, user, models.Grinder, grinder_id)
        if previous_recipe_id and session.get(models.Recipe, previous_recipe_id):
            _owned(session, user, models.Recipe, previous_recipe_id)
        if bag_id:
            _owned(session, user, models.BeanBag, bag_id)
        if planned_brew_id:
            _owned(session, user, models.PlannedBrew, planned_brew_id)
        if previous_recipe_id:
            prev = session.get(models.Recipe, previous_recipe_id)
            if not prev:
                raise HTTPException(status_code=400, detail="Previous recipe not found")
            valid, changed = crud.validate_one_parameter_delta(prev, {
                "dose_g": dose_g, "water_ml": water_ml,
                "temp_c": temp_c, "grind_size": grind_size,
                "recipe_text": recipe_text,
            })
            if not valid:
                names = " and ".join(words.label(c) for c in changed) or "nothing"
                raise HTTPException(status_code=400, detail=f"A new version changes exactly one thing. This changes {names}.")
            # What changed, and by how much, come from the values themselves, so they can't disagree
            changed_param = changed[0]
            new_value = {"dose_g": dose_g, "water_ml": water_ml, "temp_c": temp_c, "grind_size": grind_size}.get(changed_param)
            try:
                delta_amount_f = round(float(new_value) - float(getattr(prev, changed_param)), 3)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                delta_amount_f = 0.0 if changed_param == "recipe_text" else delta_amount_f
            # A variation always stays in its parent's named recipe
            line_id = prev.line_id
        else:
            # A recipe with no parent starts a new named recipe. The first one
            # for a combination may be left unnamed ("Default"); later ones need a name.
            name = (line_name or "").strip()
            if not name:
                if crud.get_lines_for_combo(session, bean_id, brewer_id, grinder_id):
                    raise HTTPException(status_code=400, detail="Give the new recipe a name")
                name = db.DEFAULT_LINE_NAME
            if crud.line_name_taken(session, bean_id, brewer_id, grinder_id, name):
                raise HTTPException(status_code=400, detail=f'There is already a recipe called "{name}" for this combination')
            line_id = crud.create_line(session, bean_id, brewer_id, grinder_id, name).id

        recipe = crud.create_recipe(
            session,
            bean_id=bean_id,
            brewer_id=brewer_id,
            grinder_id=grinder_id,
            line_id=line_id,  # type: ignore[arg-type]
            dose_g=dose_g,
            water_ml=water_ml,
            temp_c=temp_c,
            grind_size=grind_size,
            recipe_text=recipe_text,
            previous_recipe_id=previous_recipe_id,
        )

        if previous_recipe_id and changed_param and recipe.id is not None:
            crud.create_delta(
                session,
                from_recipe_id=previous_recipe_id,
                to_recipe_id=recipe.id,
                changed_param=changed_param,
                delta_amount=delta_amount_f if delta_amount_f is not None else 0.0,
                rationale=rationale,
            )

        if bag_id and recipe.id is not None:
            crud.create_brew(
                session,
                recipe_id=recipe.id,
                bag_id=bag_id,
                notes=brew_notes or None,
                rating=_parse_rating(brew_rating),
                recommended_param=brew_recommended_param or None,
                recommended_delta=brew_rec_delta,
                recommended_rationale=brew_recommended_rationale or None,
            )

        if planned_brew_id and bag_id:
            crud.delete_plan(session, planned_brew_id)
        saved_id = recipe.id

    if previous_recipe_id and not bag_id:
        return RedirectResponse(url=f"/?saved={saved_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)
