import functools
import hashlib
import json
import random
import secrets
import time
from datetime import date as date_type, datetime, timezone

from fastapi import FastAPI, File, Form, Request, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from pathlib import Path
from typing import NamedTuple, Optional

from . import auth, brew, crud, db, export, models, theme, tips, words

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


class _Rec(NamedTuple):
    recommended_param: str
    recommended_delta: Optional[float]
    recommended_rationale: Optional[str]
    from_plan: bool


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
    elif is_current_plan and pending_plan.suggested_param:  # type: ignore[union-attr]
        rec = _Rec(pending_plan.suggested_param, pending_plan.suggested_delta, pending_plan.suggested_rationale, True)  # type: ignore[union-attr,arg-type]
    # For an hour after a cup is logged, offer to add how it tastes once cooled
    cooling_brew, cooling_minutes = None, 0
    if recent_brews:
        brewed = recent_brews[0].brewed_at
        minutes = int((datetime.now(timezone.utc) - (brewed if brewed.tzinfo else brewed.replace(tzinfo=timezone.utc))).total_seconds() // 60)
        if 0 <= minutes < 60:
            cooling_brew, cooling_minutes = recent_brews[0], max(minutes, 1)
    return {
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
def index(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bags = crud.get_active_bags_for_user(session, user.id)  # type: ignore[arg-type]
        bags_with_remaining = [
            (bag, rem) for bag in bags
            if (rem := crud.get_remaining_quantity(session, bag)) > 0
        ]
        brewers = crud.get_brewers(session, user.id)  # type: ignore[arg-type]
        grinders = crud.get_grinders(session, user.id)  # type: ignore[arg-type]

        pending_plan = crud.get_pending_plan(session, user.id)  # type: ignore[arg-type]
        context = {
            "request": request,
            "bags_with_remaining": bags_with_remaining,
            "brewers": brewers,
            "grinders": grinders,
            "current_user": user,
            "pending_plan": pending_plan,
            "show_welcome": not crud.user_has_recipes(session, user.id),  # type: ignore[arg-type]
            "pixel_art_svg": _generate_pixel_art_svg(cell=4),
            "morning_quote": random.choice(QUOTES),
        }
        if pending_plan:
            context.update(_latest_recipe_context(session, pending_plan.bag_id, pending_plan.brewer_id, pending_plan.grinder_id, user.id, pending_plan.line_id))  # type: ignore[arg-type]
            if context.get("bag"):
                context["planned_bag_remaining"] = crud.get_remaining_quantity(session, context["bag"])
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
def browse(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        all_bean_recipes = crud.get_latest_recipe_per_bean(session, user.id)  # type: ignore[arg-type]
        # the coffee you brewed most recently first; never-brewed ones after, by name
        all_bean_recipes.sort(key=lambda e: max((b.brewed_at for b in e[3]), default=datetime.min), reverse=True)
        bean_recipes = [
            entry for entry in all_bean_recipes
            if not entry[2] or any(not bag.is_completed for bag, _ in entry[2])
        ]
        archived_bean_recipes = [
            entry for entry in all_bean_recipes
            if entry[2] and all(bag.is_completed for bag, _ in entry[2])
        ]
        brewers = crud.get_brewers(session, user.id)  # type: ignore[arg-type]
        grinders = crud.get_grinders(session, user.id)  # type: ignore[arg-type]
        active_bags_by_bean = {
            bean.id: [(bag, rem) for bag, rem in bags_with_remaining if not bag.is_completed]
            for bean, _, bags_with_remaining, _, _ in bean_recipes
        }
        recipe_options_by_bean = {
            bean.id: [
                (line.id, f"{line.name} · {session.get(models.Brewer, line.brewer_id).name} · {session.get(models.Grinder, line.grinder_id).name}",  # type: ignore[union-attr]
                 crud.line_recommendation(session, line.id) is not None)  # type: ignore[arg-type]
                for line in crud.get_lines_for_bean(session, bean.id)  # type: ignore[arg-type]
            ]
            for bean, _, _, _, _ in bean_recipes
        }
        return templates.TemplateResponse("browse.html", {
            "request": request,
            "bean_recipes": bean_recipes,
            "archived_bean_recipes": archived_bean_recipes,
            "brewers": brewers,
            "grinders": grinders,
            "active_bags_by_bean": active_bags_by_bean,
            "recipe_options_by_bean": recipe_options_by_bean,
            "curve_ids": crud.brews_with_curves(session, [  # brews with a scale graph
                b.id for entry in all_bean_recipes for b in entry[3]  # type: ignore[misc]
            ]),
            "current_user": user,
        })


@app.post("/beans")
def create_bean(request: Request, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_bean(session, user_id=user.id, name=name, origin=origin, roast_level=roast_level, flavor_notes=flavor_notes, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url="/manage", status_code=303)


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
    return RedirectResponse(url="/manage", status_code=303)


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
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/beans/{bean_id}/image/delete")
def delete_bean_image(request: Request, bean_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.delete_bean_image(session, bean_id)
    return RedirectResponse(url="/manage", status_code=303)


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
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/beans/{bean_id}/edit")
def edit_bean(request: Request, bean_id: int, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.update_bean(session, bean_id, name=name, origin=origin or None, roast_level=roast_level or None, flavor_notes=flavor_notes or None, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/beans/{bean_id}/delete")
def delete_bean(request: Request, bean_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Bean, bean_id)
        crud.delete_bean(session, bean_id)
    return RedirectResponse(url="/manage", status_code=303)


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
        _owned(session, user, models.BeanBag, bag_id)
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
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/bags/{bag_id}/complete")
def complete_bag(request: Request, bag_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.BeanBag, bag_id)
        crud.complete_bag(session, bag_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/bags/{bag_id}/delete")
def delete_bag(request: Request, bag_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.BeanBag, bag_id)
        crud.delete_bag(session, bag_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers/{brewer_id}/edit")
def edit_brewer(request: Request, brewer_id: int, name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Brewer, brewer_id)
        crud.update_brewer(session, brewer_id, name=name, method=method or None, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers/{brewer_id}/delete")
def delete_brewer(request: Request, brewer_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Brewer, brewer_id)
        crud.delete_brewer(session, brewer_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders/{grinder_id}/edit")
def edit_grinder(request: Request, grinder_id: int, name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Grinder, grinder_id)
        crud.update_grinder(session, grinder_id, name=name, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders/{grinder_id}/delete")
def delete_grinder(request: Request, grinder_id: int):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        _owned(session, user, models.Grinder, grinder_id)
        crud.delete_grinder(session, grinder_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers")
def create_brewer(request: Request, name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_brewer(session, user_id=user.id, name=name, method=method, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders")
def create_grinder(request: Request, name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_grinder(session, user_id=user.id, name=name, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url="/manage", status_code=303)


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
        # Only when the recipe has no recommendation yet: its own always wins
        if line and crud.line_recommendation(session, line.id):  # type: ignore[arg-type]
            suggestion = {}
        crud.create_plan(session, user_id=user.id, bag_id=bag_id, brewer_id=brewer_id, grinder_id=grinder_id, notes=notes or None, line_id=line.id if line else None, **suggestion)  # type: ignore[arg-type,union-attr]
    return RedirectResponse(url="/", status_code=303)


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
def brew_mode(line_id: int, request: Request, bag_id: Optional[int] = None, plan_id: Optional[int] = None):
    """Brew mode: the named recipe's current version in large type, with a
    timer that follows the times written in the method, and the log form."""
    with Session(db.engine) as session:
        user = _require_user(request, session)
        line = _owned(session, user, models.RecipeLine, line_id)
        latest = crud.get_latest_recipe(session, line_id)
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
        return templates.TemplateResponse("brew.html", {
            "request": request,
            "current_user": user,
            "line": line,
            "latest": latest,
            "title": export.title(line, latest.bean),
            "ratio": export.ratio(latest),
            "steps": brew.parse_steps(latest.recipe_text),
            "prep": brew.prep_text(latest.recipe_text),
            "auto_stop": brew.ends_timer(latest.recipe_text),
            "animation": brew.animation_data(latest.recipe_text, latest.brewer.name, latest.brewer.method)
                         if user.show_brew_animation else "",
            "live_graph": user.show_live_graph,
            "last_curve": _last_curve(session, line, latest),
            "bag": bag,
            "plan_id": plan.id if plan else None,
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
def change_recipe_page(request: Request, line_id: int, bag_id: Optional[int] = None, plan_id: Optional[int] = None):
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
        elif plan and plan.suggested_param:
            rec = _Rec(plan.suggested_param, plan.suggested_delta, plan.suggested_rationale, True)
        return templates.TemplateResponse("change_recipe.html", {
            "request": request, "current_user": user, "line": line, "latest": latest, "bag": bag, "plan": plan,
            "rec": rec, "version": crud.version_number(session, latest),
            "deltas": crud.get_recent_deltas(session, line_id, limit=5),
            "limits": CHANGE_LIMITS, "grind_step": _grind_step(latest.grind_size),
        })


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
