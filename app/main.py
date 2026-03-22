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


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session(db.engine) as session:
        bags = crud.get_all_bags(session)
        bags_with_remaining = [(bag, crud.get_remaining_quantity(session, bag)) for bag in bags]
        brewers = crud.get_brewers(session)
        grinders = crud.get_grinders(session)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "bags_with_remaining": bags_with_remaining,
            "brewers": brewers,
            "grinders": grinders,
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
        beans = crud.get_beans(session)
        beans_with_bags = [
            (bean, [(bag, crud.get_remaining_quantity(session, bag)) for bag in crud.get_bags_for_bean(session, bean.id)])  # type: ignore[arg-type]
            for bean in beans
        ]
        brewers = crud.get_brewers(session)
        grinders = crud.get_grinders(session)
        return templates.TemplateResponse("manage.html", {
            "request": request,
            "beans_with_bags": beans_with_bags,
            "brewers": brewers,
            "grinders": grinders,
        })


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request):
    with Session(db.engine) as session:
        bean_recipes = crud.get_latest_recipe_per_bean(session)
        return templates.TemplateResponse("browse.html", {
            "request": request,
            "bean_recipes": bean_recipes,
        })


@app.post("/beans")
def create_bean(name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.create_bean(session, name=name, origin=origin, roast_level=roast_level, flavor_notes=flavor_notes, notes=notes)
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


@app.post("/brewers")
def create_brewer(name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.create_brewer(session, name=name, method=method, notes=notes)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders")
def create_grinder(name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        crud.create_grinder(session, name=name, notes=notes)
    return RedirectResponse(url="/manage", status_code=303)


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
):
    delta_amount_f: Optional[float] = None
    if delta_amount and delta_amount.strip():
        try:
            delta_amount_f = float(delta_amount)
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
            crud.create_brew(session, recipe_id=recipe.id, bag_id=bag_id, notes=brew_notes or None)

    return RedirectResponse(url="/", status_code=303)
