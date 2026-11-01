import random
from datetime import date as date_type

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from typing import Optional

from . import crud, db, models

app = FastAPI(title="Coffee Recipe Tracker")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

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


def _get_current_user(request: Request, session: Session) -> Optional[models.User]:
    uid = request.cookies.get("user_id")
    if not uid or not uid.isdigit():
        return None
    return session.get(models.User, int(uid))


def _require_user(request: Request, session: Session):
    user = _get_current_user(request, session)
    if not user:
        raise _redirect_to_select()
    return user


class _redirect_to_select(Exception):
    pass


@app.middleware("http")
async def user_redirect_middleware(request, call_next):
    try:
        return await call_next(request)
    except _redirect_to_select:
        r = RedirectResponse(url="/select-user", status_code=302)
        r.delete_cookie("user_id")
        return r


@app.get("/select-user", response_class=HTMLResponse)
def select_user(request: Request):
    with Session(db.engine) as session:
        users = crud.get_users(session)
        return templates.TemplateResponse("select_user.html", {
            "request": request,
            "users": users,
            "current_user": None,
        })


@app.post("/set-user")
def set_user(user_id: int = Form(...)):
    r = RedirectResponse(url="/", status_code=303)
    r.set_cookie("user_id", str(user_id), max_age=60 * 60 * 24 * 365)
    return r


@app.post("/users")
def create_user(request: Request, name: str = Form(...)):
    with Session(db.engine) as session:
        user = _get_current_user(request, session)
        if not user:
            return RedirectResponse(url="/select-user", status_code=303)
        crud.create_user(session, name=name)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/users/{target_user_id}/delete")
def delete_user(target_user_id: int, request: Request):
    current_uid = request.cookies.get("user_id")
    with Session(db.engine) as session:
        crud.delete_user(session, target_user_id)
    if current_uid and current_uid.isdigit() and int(current_uid) == target_user_id:
        r = RedirectResponse(url="/select-user", status_code=303)
        r.delete_cookie("user_id")
        return r
    return RedirectResponse(url="/manage", status_code=303)


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
    recent_brews = crud.get_recent_brews(session, latest.id) if latest and latest.id else []
    recent_deltas = crud.get_recent_deltas(session, line.id) if line and line.id else []  # type: ignore[arg-type]

    # A plan without a line (made from the browse page) means "the default one"
    is_current_plan = bool(
        pending_plan and line
        and pending_plan.bag_id == bag_id_int
        and pending_plan.brewer_id == brewer_id_int
        and pending_plan.grinder_id == grinder_id_int
        and (pending_plan.line_id == line.id or (pending_plan.line_id is None and line is lines[0]))
    )
    return {
        "latest": latest,
        "recent_brews": recent_brews,
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
            "pixel_art_svg": _generate_pixel_art_svg(),
            "morning_quote": random.choice(QUOTES),
        }
        if pending_plan:
            context.update(_latest_recipe_context(session, pending_plan.bag_id, pending_plan.brewer_id, pending_plan.grinder_id, user.id, pending_plan.line_id))  # type: ignore[arg-type]
            if context.get("bag"):
                context["planned_bag_remaining"] = crud.get_remaining_quantity(session, context["bag"])
        return templates.TemplateResponse("index.html", context)


@app.get("/recipes/latest", response_class=HTMLResponse)
def latest_recipe_partial(request: Request, bag_id: Optional[str] = None, brewer_id: Optional[str] = None, grinder_id: Optional[str] = None, line_id: Optional[str] = None):
    bag_id_int = int(bag_id) if bag_id and bag_id.isdigit() else None
    brewer_id_int = int(brewer_id) if brewer_id and brewer_id.isdigit() else None
    grinder_id_int = int(grinder_id) if grinder_id and grinder_id.isdigit() else None
    line_id_int = int(line_id) if line_id and line_id.isdigit() else None

    with Session(db.engine) as session:
        user = _get_current_user(request, session)
        context = _latest_recipe_context(session, bag_id_int, brewer_id_int, grinder_id_int, user.id if user else None, line_id_int)  # type: ignore[arg-type]
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
        all_users = crud.get_users(session)
        return templates.TemplateResponse("manage.html", {
            "request": request,
            "beans_with_bags": active_beans_with_bags,
            "archived_beans_with_bags": archived_beans_with_bags,
            "brewers": brewers,
            "grinders": grinders,
            "current_user": user,
            "all_users": all_users,
        })


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        all_bean_recipes = crud.get_latest_recipe_per_bean(session, user.id)  # type: ignore[arg-type]
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
        return templates.TemplateResponse("browse.html", {
            "request": request,
            "bean_recipes": bean_recipes,
            "archived_bean_recipes": archived_bean_recipes,
            "brewers": brewers,
            "grinders": grinders,
            "active_bags_by_bean": active_bags_by_bean,
            "current_user": user,
        })


@app.post("/beans")
def create_bean(request: Request, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        crud.create_bean(session, user_id=user.id, name=name, origin=origin, roast_level=roast_level, flavor_notes=flavor_notes, notes=notes)  # type: ignore[arg-type]
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/bags")
def create_bag(
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
def edit_bean(bean_id: int, name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.update_bean(session, bean_id, name=name, origin=origin or None, roast_level=roast_level or None, flavor_notes=flavor_notes or None, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/beans/{bean_id}/delete")
def delete_bean(bean_id: int):
    with Session(db.engine) as session:
        crud.delete_bean(session, bean_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/bags/{bag_id}/edit")
def edit_bag(
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
def complete_bag(bag_id: int):
    with Session(db.engine) as session:
        crud.complete_bag(session, bag_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/bags/{bag_id}/delete")
def delete_bag(bag_id: int):
    with Session(db.engine) as session:
        crud.delete_bag(session, bag_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers/{brewer_id}/edit")
def edit_brewer(brewer_id: int, name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.update_brewer(session, brewer_id, name=name, method=method or None, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers/{brewer_id}/delete")
def delete_brewer(brewer_id: int):
    with Session(db.engine) as session:
        crud.delete_brewer(session, brewer_id)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders/{grinder_id}/edit")
def edit_grinder(grinder_id: int, name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.update_grinder(session, grinder_id, name=name, notes=notes or None)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders/{grinder_id}/delete")
def delete_grinder(grinder_id: int):
    with Session(db.engine) as session:
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
    brewer_id: int = Form(...),
    grinder_id: int = Form(...),
    notes: str = Form(None),
    line_id: int = Form(None),
):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        if line_id:
            line = session.get(models.RecipeLine, line_id)
            bag = session.get(models.BeanBag, bag_id)
            if not line or not bag or (line.bean_id, line.brewer_id, line.grinder_id) != (bag.bean_id, brewer_id, grinder_id):
                line_id = None  # stale or mismatched: fall back to the default line
        crud.create_plan(session, user_id=user.id, bag_id=bag_id, brewer_id=brewer_id, grinder_id=grinder_id, notes=notes or None, line_id=line_id)  # type: ignore[arg-type]
    return RedirectResponse(url="/", status_code=303)


@app.post("/lines/{line_id}/rename")
def rename_line(line_id: int, name: str = Form(...)):
    with Session(db.engine) as session:
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


@app.post("/lines/{line_id}/delete")
def delete_line(line_id: int):
    with Session(db.engine) as session:
        crud.delete_line(session, line_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/plan/{plan_id}/cancel")
def cancel_plan(plan_id: int, request: Request):
    with Session(db.engine) as session:
        _require_user(request, session)
        crud.delete_plan(session, plan_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/brews")
def create_brew(
    recipe_id: int = Form(...),
    bag_id: int = Form(...),
    notes: str = Form(None),
    recommended_param: str = Form(None),
    recommended_delta: str = Form(None),
    recommended_rationale: str = Form(None),
    planned_brew_id: int = Form(None),
):
    rec_delta: Optional[float] = None
    if recommended_delta and recommended_delta.strip():
        try:
            rec_delta = float(recommended_delta)
        except ValueError:
            pass
    with Session(db.engine) as session:
        crud.create_brew(
            session,
            recipe_id=recipe_id,
            bag_id=bag_id,
            notes=notes,
            recommended_param=recommended_param or None,
            recommended_delta=rec_delta,
            recommended_rationale=recommended_rationale or None,
        )
        if planned_brew_id:
            crud.delete_plan(session, planned_brew_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/recipes")
def create_recipe(
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
                raise HTTPException(status_code=400, detail=f"Must change exactly one parameter. Changed: {changed}")
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
                recommended_param=brew_recommended_param or None,
                recommended_delta=brew_rec_delta,
                recommended_rationale=brew_recommended_rationale or None,
            )

        if planned_brew_id:
            crud.delete_plan(session, planned_brew_id)

    return RedirectResponse(url="/", status_code=303)
