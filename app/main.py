from fastapi import Depends, FastAPI, Form, Request, HTTPException
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
        beans = crud.get_beans(session)
        brewers = crud.get_brewers(session)
        grinders = crud.get_grinders(session)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "beans": beans,
                "brewers": brewers,
                "grinders": grinders,
                "latest_recipe": None,
                "recent_deltas": [],
                "message": "",
            },
        )


@app.get("/recipes/latest", response_class=HTMLResponse)
def latest_recipe_partial(request: Request, bean_id: Optional[str] = None, brewer_id: Optional[str] = None, grinder_id: Optional[str] = None):
    bean_id_int = int(bean_id) if bean_id and bean_id.isdigit() else None
    brewer_id_int = int(brewer_id) if brewer_id and brewer_id.isdigit() else None
    grinder_id_int = int(grinder_id) if grinder_id and grinder_id.isdigit() else None

    if not bean_id_int or not brewer_id_int or not grinder_id_int:
        return templates.TemplateResponse(
            "partials/latest_recipe.html",
            {
                "request": request,
                "latest": None,
                "recent_deltas": [],
                "bean_id": bean_id_int,
                "brewer_id": brewer_id_int,
                "grinder_id": grinder_id_int,
                "message": "Select bean, brewer, and grinder to show recipes.",
            },
        )

    with Session(db.engine) as session:
        latest = crud.get_latest_recipe(session, bean_id_int, brewer_id_int, grinder_id_int)
        recents = crud.get_recent_deltas(session, bean_id_int, brewer_id_int, grinder_id_int)
        return templates.TemplateResponse(
            "partials/latest_recipe.html",
            {
                "request": request,
                "latest": latest,
                "recent_deltas": recents,
                "bean_id": bean_id_int,
                "brewer_id": brewer_id_int,
                "grinder_id": grinder_id_int,
                "message": "",
            },
        )


@app.get("/manage", response_class=HTMLResponse)
def manage(request: Request):
    with Session(db.engine) as session:
        return templates.TemplateResponse(
            "manage.html",
            {
                "request": request,
                "beans": crud.get_beans(session),
                "brewers": crud.get_brewers(session),
                "grinders": crud.get_grinders(session),
            },
        )


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request):
    with Session(db.engine) as session:
        bean_recipes = crud.get_latest_recipe_per_bean(session)
    return templates.TemplateResponse(
        "browse.html",
        {"request": request, "bean_recipes": bean_recipes},
    )


@app.post("/beans")
def create_bean(name: str = Form(...), origin: str = Form(None), roast_level: str = Form(None), roast_date: str = Form(None), flavor_notes: str = Form(None), notes: str = Form(None)):
    from datetime import date as date_type
    parsed_date = date_type.fromisoformat(roast_date) if roast_date else None
    with Session(db.engine) as session:
        bean = crud.create_bean(session, name=name, origin=origin, roast_level=roast_level, roast_date=parsed_date, flavor_notes=flavor_notes, notes=notes)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/brewers")
def create_brewer(name: str = Form(...), method: str = Form(None), notes: str = Form(None)):
    with Session(db.engine) as session:
        brewer = crud.create_brewer(session, name=name, method=method, notes=notes)
    return RedirectResponse(url="/manage", status_code=303)


@app.post("/grinders")
def create_grinder(name: str = Form(...), notes: str = Form(None)):
    with Session(db.engine) as session:
        grinder = crud.create_grinder(session, name=name, notes=notes)
    return RedirectResponse(url="/manage", status_code=303)


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
    notes: str = Form(None),
    previous_recipe_id: int = Form(None),
    changed_param: str = Form(None),
    delta_amount: float = Form(None),
    rationale: str = Form(None),
):
    with Session(db.engine) as session:
        latest = None
        if previous_recipe_id:
            latest = session.get(models.Recipe, previous_recipe_id)
            if not latest:
                raise HTTPException(status_code=400, detail="Previous recipe not found")

            valid, changed = crud.validate_one_parameter_delta(
                latest,
                {
                    "dose_g": dose_g,
                    "water_ml": water_ml,
                    "temp_c": temp_c,
                    "grind_size": grind_size,
                },
            )
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
            notes=notes,
            previous_recipe_id=previous_recipe_id,
        )

        if previous_recipe_id and changed_param and delta_amount is not None:
            crud.create_delta(
                session,
                from_recipe_id=previous_recipe_id,
                to_recipe_id=recipe.id,
                changed_param=changed_param,
                delta_amount=delta_amount,
                rationale=rationale,
            )

    return RedirectResponse(url="/manage", status_code=303)
