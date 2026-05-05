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


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session(db.engine) as session:
        user = _require_user(request, session)
        bags = crud.get_active_bags_for_user(session, user.id)  # type: ignore[arg-type]
        bags_with_remaining = [(bag, crud.get_remaining_quantity(session, bag)) for bag in bags]
        brewers = crud.get_brewers(session, user.id)  # type: ignore[arg-type]
        grinders = crud.get_grinders(session, user.id)  # type: ignore[arg-type]
        return templates.TemplateResponse("index.html", {
            "request": request,
            "bags_with_remaining": bags_with_remaining,
            "brewers": brewers,
            "grinders": grinders,
            "current_user": user,
        })


@app.get("/recipes/latest", response_class=HTMLResponse)
def latest_recipe_partial(request: Request, bag_id: Optional[str] = None, brewer_id: Optional[str] = None, grinder_id: Optional[str] = None):
    bag_id_int = int(bag_id) if bag_id and bag_id.isdigit() else None
    brewer_id_int = int(brewer_id) if brewer_id and brewer_id.isdigit() else None
    grinder_id_int = int(grinder_id) if grinder_id and grinder_id.isdigit() else None

    if not bag_id_int or not brewer_id_int or not grinder_id_int:
        return templates.TemplateResponse("partials/latest_recipe.html", {
            "request": request,
            "latest": None,
            "recent_brews": [],
            "recent_deltas": [],
            "bag": None,
            "bag_id": bag_id_int,
            "bean_id": None,
            "brewer_id": brewer_id_int,
            "grinder_id": grinder_id_int,
            "message": "Select a bag, brewer, and grinder to show recipes.",
        })

    with Session(db.engine) as session:
        bag = session.get(models.BeanBag, bag_id_int)
        if not bag:
            raise HTTPException(status_code=404, detail="Bag not found")

        bean_id = bag.bean_id
        latest = crud.get_latest_recipe(session, bean_id, brewer_id_int, grinder_id_int)
        recent_brews = crud.get_recent_brews(session, latest.id) if latest and latest.id else []
        recent_deltas = crud.get_recent_deltas(session, bean_id, brewer_id_int, grinder_id_int)
        return templates.TemplateResponse("partials/latest_recipe.html", {
            "request": request,
            "latest": latest,
            "recent_brews": recent_brews,
            "recent_deltas": recent_deltas,
            "bag": bag,
            "bag_id": bag_id_int,
            "bean_id": bean_id,
            "brewer_id": brewer_id_int,
            "grinder_id": grinder_id_int,
            "message": "",
        })


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
        return templates.TemplateResponse("browse.html", {
            "request": request,
            "bean_recipes": bean_recipes,
            "archived_bean_recipes": archived_bean_recipes,
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


@app.post("/brews")
def create_brew(
    recipe_id: int = Form(...),
    bag_id: int = Form(...),
    notes: str = Form(None),
    recommended_param: str = Form(None),
    recommended_delta: str = Form(None),
    recommended_rationale: str = Form(None),
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

        recipe = crud.create_recipe(
            session,
            bean_id=bean_id,
            brewer_id=brewer_id,
            grinder_id=grinder_id,
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

    return RedirectResponse(url="/", status_code=303)
