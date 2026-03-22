from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from . import models


def get_beans(session: Session) -> List[models.Bean]:
    return session.exec(select(models.Bean).order_by(models.Bean.name)).all()


def get_brewers(session: Session) -> List[models.Brewer]:
    return session.exec(select(models.Brewer).order_by(models.Brewer.name)).all()


def get_latest_recipe(session: Session, bean_id: int, brewer_id: int, grinder_id: int) -> Optional[models.Recipe]:
    statement = (
        select(models.Recipe)
        .where(models.Recipe.bean_id == bean_id)
        .where(models.Recipe.brewer_id == brewer_id)
        .where(models.Recipe.grinder_id == grinder_id)
        .order_by(models.Recipe.created_at.desc())
    )
    return session.exec(statement).first()


def create_bean(session: Session, name: str, origin: Optional[str] = None, roast_level: Optional[str] = None, roast_date=None, flavor_notes: Optional[str] = None, notes: Optional[str] = None) -> models.Bean:
    bean = models.Bean(name=name, origin=origin, roast_level=roast_level, roast_date=roast_date, flavor_notes=flavor_notes, notes=notes)
    session.add(bean)
    session.commit()
    session.refresh(bean)
    return bean


def create_brewer(session: Session, name: str, method: Optional[str] = None, notes: Optional[str] = None) -> models.Brewer:
    brewer = models.Brewer(name=name, method=method, notes=notes)
    session.add(brewer)
    session.commit()
    session.refresh(brewer)
    return brewer


def get_grinders(session: Session) -> List[models.Grinder]:
    return session.exec(select(models.Grinder).order_by(models.Grinder.name)).all()


def create_grinder(session: Session, name: str, notes: Optional[str] = None) -> models.Grinder:
    grinder = models.Grinder(name=name, notes=notes)
    session.add(grinder)
    session.commit()
    session.refresh(grinder)
    return grinder


def validate_one_parameter_delta(base: models.Recipe, new_values: Dict) -> Tuple[bool, List[str]]:
    fields = ["dose_g", "water_ml", "temp_c", "grind_size"]
    changed = []

    for f in fields:
        old_value = getattr(base, f)
        new_value = new_values.get(f, old_value)

        if f == "grind_size":
            if (old_value or "") != (new_value or ""):
                changed.append(f)
        else:
            try:
                if float(old_value) != float(new_value):
                    changed.append(f)
            except (TypeError, ValueError):
                if old_value != new_value:
                    changed.append(f)

    return (len(changed) == 1, changed)


def create_recipe(session: Session, bean_id: int, brewer_id: int, grinder_id: int, dose_g: float, water_ml: float, temp_c: float, grind_size: str, recipe_text: Optional[str] = None, notes: Optional[str] = None, previous_recipe_id: Optional[int] = None) -> models.Recipe:
    recipe = models.Recipe(
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
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe


def create_delta(session: Session, from_recipe_id: int, to_recipe_id: int, changed_param: str, delta_amount: float, rationale: Optional[str] = None) -> models.Delta:
    delta = models.Delta(
        from_recipe_id=from_recipe_id,
        to_recipe_id=to_recipe_id,
        changed_param=changed_param,
        delta_amount=delta_amount,
        rationale=rationale,
    )
    session.add(delta)
    session.commit()
    session.refresh(delta)
    return delta


def get_latest_recipe_per_bean(session: Session):
    beans = session.exec(select(models.Bean).order_by(models.Bean.name)).all()
    result = []
    for bean in beans:
        stmt = (
            select(models.Recipe)
            .where(models.Recipe.bean_id == bean.id)
            .order_by(models.Recipe.created_at.desc())  # type: ignore[union-attr]
        )
        latest = session.exec(stmt).first()
        result.append((bean, latest))
    return result


def get_recent_deltas(session: Session, bean_id: int, brewer_id: int, grinder_id: int, limit: int = 10) -> List[models.Delta]:
    statement = (
        select(models.Delta)
        .join(models.Recipe, models.Recipe.id == models.Delta.to_recipe_id)
        .where(models.Recipe.bean_id == bean_id)
        .where(models.Recipe.brewer_id == brewer_id)
        .where(models.Recipe.grinder_id == grinder_id)
        .order_by(models.Delta.created_at.desc())
        .limit(limit)
    )
    return session.exec(statement).all()
