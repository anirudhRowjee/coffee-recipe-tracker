from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Session, select

from . import models


def get_beans(session: Session) -> List[models.Bean]:
    return session.exec(select(models.Bean).order_by(models.Bean.name)).all()


def get_brewers(session: Session) -> List[models.Brewer]:
    return session.exec(select(models.Brewer).order_by(models.Brewer.name)).all()


def get_grinders(session: Session) -> List[models.Grinder]:
    return session.exec(select(models.Grinder).order_by(models.Grinder.name)).all()


def get_bags_for_bean(session: Session, bean_id: int) -> List[models.BeanBag]:
    return session.exec(
        select(models.BeanBag)
        .where(models.BeanBag.bean_id == bean_id)
        .order_by(models.BeanBag.purchase_date.desc())  # type: ignore[union-attr]
    ).all()


def get_all_bags(session: Session) -> List[models.BeanBag]:
    return session.exec(
        select(models.BeanBag).order_by(models.BeanBag.purchase_date.desc())  # type: ignore[union-attr]
    ).all()


def get_remaining_quantity(session: Session, bag: models.BeanBag) -> float:
    used = session.exec(
        select(func.sum(models.Recipe.dose_g))
        .join(models.Brew, models.Brew.recipe_id == models.Recipe.id)  # type: ignore[arg-type]
        .where(models.Brew.bag_id == bag.id)
    ).first()
    return bag.initial_quantity_g - (used or 0.0)


def get_latest_recipe(session: Session, bean_id: int, brewer_id: int, grinder_id: int) -> Optional[models.Recipe]:
    return session.exec(
        select(models.Recipe)
        .where(models.Recipe.bean_id == bean_id)
        .where(models.Recipe.brewer_id == brewer_id)
        .where(models.Recipe.grinder_id == grinder_id)
        .order_by(models.Recipe.created_at.desc())  # type: ignore[union-attr]
    ).first()


def get_recent_brews(session: Session, recipe_id: int, limit: int = 5) -> List[models.Brew]:
    return session.exec(
        select(models.Brew)
        .where(models.Brew.recipe_id == recipe_id)
        .order_by(models.Brew.brewed_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def get_recent_deltas(session: Session, bean_id: int, brewer_id: int, grinder_id: int, limit: int = 10) -> List[models.Delta]:
    return session.exec(
        select(models.Delta)
        .join(models.Recipe, models.Recipe.id == models.Delta.to_recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.bean_id == bean_id)
        .where(models.Recipe.brewer_id == brewer_id)
        .where(models.Recipe.grinder_id == grinder_id)
        .order_by(models.Delta.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def create_bean(session: Session, name: str, origin: Optional[str] = None, roast_level: Optional[str] = None, flavor_notes: Optional[str] = None, notes: Optional[str] = None) -> models.Bean:
    bean = models.Bean(name=name, origin=origin, roast_level=roast_level, flavor_notes=flavor_notes, notes=notes)
    session.add(bean)
    session.commit()
    session.refresh(bean)
    return bean


def create_bag(session: Session, bean_id: int, initial_quantity_g: float, roast_date=None, purchase_date=None, low_threshold_g: float = 50.0, is_frozen: bool = False, frozen_date=None, notes: Optional[str] = None) -> models.BeanBag:
    bag = models.BeanBag(
        bean_id=bean_id,
        initial_quantity_g=initial_quantity_g,
        roast_date=roast_date,
        purchase_date=purchase_date,
        low_threshold_g=low_threshold_g,
        is_frozen=is_frozen,
        frozen_date=frozen_date,
        notes=notes,
    )
    session.add(bag)
    session.commit()
    session.refresh(bag)
    return bag


def create_brew(session: Session, recipe_id: int, bag_id: int, notes: Optional[str] = None, recommended_param: Optional[str] = None, recommended_delta: Optional[float] = None, recommended_rationale: Optional[str] = None) -> models.Brew:
    brew = models.Brew(recipe_id=recipe_id, bag_id=bag_id, notes=notes, recommended_param=recommended_param, recommended_delta=recommended_delta, recommended_rationale=recommended_rationale)
    session.add(brew)
    session.commit()
    session.refresh(brew)
    return brew


def create_brewer(session: Session, name: str, method: Optional[str] = None, notes: Optional[str] = None) -> models.Brewer:
    brewer = models.Brewer(name=name, method=method, notes=notes)
    session.add(brewer)
    session.commit()
    session.refresh(brewer)
    return brewer


def create_grinder(session: Session, name: str, notes: Optional[str] = None) -> models.Grinder:
    grinder = models.Grinder(name=name, notes=notes)
    session.add(grinder)
    session.commit()
    session.refresh(grinder)
    return grinder


def update_bean(session: Session, bean_id: int, name: str, origin: Optional[str], roast_level: Optional[str], flavor_notes: Optional[str], notes: Optional[str]) -> Optional[models.Bean]:
    bean = session.get(models.Bean, bean_id)
    if not bean:
        return None
    bean.name = name
    bean.origin = origin
    bean.roast_level = roast_level
    bean.flavor_notes = flavor_notes
    bean.notes = notes
    session.commit()
    return bean


def delete_bean(session: Session, bean_id: int) -> None:
    """Delete a bean and cascade to its recipes (+ their brews/deltas) and bags (+ their brews)."""
    recipe_ids = [r.id for r in session.exec(
        select(models.Recipe).where(models.Recipe.bean_id == bean_id)
    ).all()]

    if recipe_ids:
        # Deltas referencing these recipes
        for delta in session.exec(
            select(models.Delta).where(
                (models.Delta.from_recipe_id.in_(recipe_ids)) |  # type: ignore[union-attr]
                (models.Delta.to_recipe_id.in_(recipe_ids))      # type: ignore[union-attr]
            )
        ).all():
            session.delete(delta)
        # Brews referencing these recipes
        for brew in session.exec(
            select(models.Brew).where(models.Brew.recipe_id.in_(recipe_ids))  # type: ignore[union-attr]
        ).all():
            session.delete(brew)
        for recipe in session.exec(
            select(models.Recipe).where(models.Recipe.bean_id == bean_id)
        ).all():
            session.delete(recipe)

    # Bags and any remaining brews linked to them
    for bag in session.exec(select(models.BeanBag).where(models.BeanBag.bean_id == bean_id)).all():
        for brew in session.exec(select(models.Brew).where(models.Brew.bag_id == bag.id)).all():
            session.delete(brew)
        session.delete(bag)

    bean = session.get(models.Bean, bean_id)
    if bean:
        session.delete(bean)
    session.commit()


def update_bag(session: Session, bag_id: int, initial_quantity_g: float, roast_date, purchase_date, low_threshold_g: float, is_frozen: bool, frozen_date, notes: Optional[str]) -> Optional[models.BeanBag]:
    bag = session.get(models.BeanBag, bag_id)
    if not bag:
        return None
    bag.initial_quantity_g = initial_quantity_g
    bag.roast_date = roast_date
    bag.purchase_date = purchase_date
    bag.low_threshold_g = low_threshold_g
    bag.is_frozen = is_frozen
    bag.frozen_date = frozen_date
    bag.notes = notes
    session.commit()
    return bag


def complete_bag(session: Session, bag_id: int) -> Optional[models.BeanBag]:
    bag = session.get(models.BeanBag, bag_id)
    if not bag:
        return None
    bag.is_completed = True
    session.commit()
    return bag


def delete_bag(session: Session, bag_id: int) -> None:
    """Delete a bag and its brews. Recipes are preserved (they belong to the bean type)."""
    for brew in session.exec(select(models.Brew).where(models.Brew.bag_id == bag_id)).all():
        session.delete(brew)
    bag = session.get(models.BeanBag, bag_id)
    if bag:
        session.delete(bag)
    session.commit()


def update_brewer(session: Session, brewer_id: int, name: str, method: Optional[str], notes: Optional[str]) -> Optional[models.Brewer]:
    brewer = session.get(models.Brewer, brewer_id)
    if not brewer:
        return None
    brewer.name = name
    brewer.method = method
    brewer.notes = notes
    session.commit()
    return brewer


def delete_brewer(session: Session, brewer_id: int) -> None:
    """Delete a brewer and cascade to its recipes (+ their brews/deltas)."""
    recipe_ids = [r.id for r in session.exec(
        select(models.Recipe).where(models.Recipe.brewer_id == brewer_id)
    ).all()]
    if recipe_ids:
        for delta in session.exec(
            select(models.Delta).where(
                (models.Delta.from_recipe_id.in_(recipe_ids)) |  # type: ignore[union-attr]
                (models.Delta.to_recipe_id.in_(recipe_ids))      # type: ignore[union-attr]
            )
        ).all():
            session.delete(delta)
        for brew in session.exec(
            select(models.Brew).where(models.Brew.recipe_id.in_(recipe_ids))  # type: ignore[union-attr]
        ).all():
            session.delete(brew)
        for recipe in session.exec(
            select(models.Recipe).where(models.Recipe.brewer_id == brewer_id)
        ).all():
            session.delete(recipe)
    brewer = session.get(models.Brewer, brewer_id)
    if brewer:
        session.delete(brewer)
    session.commit()


def update_grinder(session: Session, grinder_id: int, name: str, notes: Optional[str]) -> Optional[models.Grinder]:
    grinder = session.get(models.Grinder, grinder_id)
    if not grinder:
        return None
    grinder.name = name
    grinder.notes = notes
    session.commit()
    return grinder


def delete_grinder(session: Session, grinder_id: int) -> None:
    """Delete a grinder and cascade to its recipes (+ their brews/deltas)."""
    recipe_ids = [r.id for r in session.exec(
        select(models.Recipe).where(models.Recipe.grinder_id == grinder_id)
    ).all()]
    if recipe_ids:
        for delta in session.exec(
            select(models.Delta).where(
                (models.Delta.from_recipe_id.in_(recipe_ids)) |  # type: ignore[union-attr]
                (models.Delta.to_recipe_id.in_(recipe_ids))      # type: ignore[union-attr]
            )
        ).all():
            session.delete(delta)
        for brew in session.exec(
            select(models.Brew).where(models.Brew.recipe_id.in_(recipe_ids))  # type: ignore[union-attr]
        ).all():
            session.delete(brew)
        for recipe in session.exec(
            select(models.Recipe).where(models.Recipe.grinder_id == grinder_id)
        ).all():
            session.delete(recipe)
    grinder = session.get(models.Grinder, grinder_id)
    if grinder:
        session.delete(grinder)
    session.commit()


def validate_one_parameter_delta(base: models.Recipe, new_values: Dict) -> Tuple[bool, List[str]]:
    changed = []
    for f in ["dose_g", "water_ml", "temp_c", "grind_size"]:
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
    # recipe_text is a string comparison
    old_text = base.recipe_text or ""
    new_text = new_values.get("recipe_text") or ""
    if old_text != new_text:
        changed.append("recipe_text")
    return (len(changed) == 1, changed)


def create_recipe(session: Session, bean_id: int, brewer_id: int, grinder_id: int, dose_g: float, water_ml: float, temp_c: float, grind_size: str, recipe_text: Optional[str] = None, previous_recipe_id: Optional[int] = None) -> models.Recipe:
    recipe = models.Recipe(
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


def get_brews_for_bean(session: Session, bean_id: int, limit: int = 30) -> List[models.Brew]:
    return session.exec(
        select(models.Brew)
        .join(models.Recipe, models.Recipe.id == models.Brew.recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.bean_id == bean_id)
        .order_by(models.Brew.brewed_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def get_deltas_for_bean(session: Session, bean_id: int, limit: int = 30) -> List[models.Delta]:
    return session.exec(
        select(models.Delta)
        .join(models.Recipe, models.Recipe.id == models.Delta.to_recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.bean_id == bean_id)
        .order_by(models.Delta.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def get_latest_recipe_per_bean(session: Session):
    beans = session.exec(select(models.Bean).order_by(models.Bean.name)).all()
    result = []
    for bean in beans:
        latest = session.exec(
            select(models.Recipe)
            .where(models.Recipe.bean_id == bean.id)
            .order_by(models.Recipe.created_at.desc())  # type: ignore[union-attr]
        ).first()
        bags = get_bags_for_bean(session, bean.id)  # type: ignore[arg-type]
        bags_with_remaining = [(bag, get_remaining_quantity(session, bag)) for bag in bags]
        brews = get_brews_for_bean(session, bean.id)  # type: ignore[arg-type]
        deltas = get_deltas_for_bean(session, bean.id)  # type: ignore[arg-type]
        result.append((bean, latest, bags_with_remaining, brews, deltas))
    return result
