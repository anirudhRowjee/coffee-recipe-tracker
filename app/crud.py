from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Session, select

from . import models


def get_users(session: Session) -> List[models.User]:
    return list(session.exec(select(models.User).order_by(models.User.name)).all())


def create_user(session: Session, name: str) -> models.User:
    user = models.User(name=name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_user(session: Session, user_id: int) -> None:
    for bean in session.exec(select(models.Bean).where(models.Bean.user_id == user_id)).all():
        delete_bean(session, bean.id)  # type: ignore[arg-type]
    for brewer in session.exec(select(models.Brewer).where(models.Brewer.user_id == user_id)).all():
        delete_brewer(session, brewer.id)  # type: ignore[arg-type]
    for grinder in session.exec(select(models.Grinder).where(models.Grinder.user_id == user_id)).all():
        delete_grinder(session, grinder.id)  # type: ignore[arg-type]
    user = session.get(models.User, user_id)
    if user:
        session.delete(user)
    session.commit()


def get_beans(session: Session, user_id: int) -> List[models.Bean]:
    return list(session.exec(
        select(models.Bean)
        .where(models.Bean.user_id == user_id)
        .order_by(models.Bean.name)
    ).all())


def get_brewers(session: Session, user_id: int) -> List[models.Brewer]:
    return list(session.exec(
        select(models.Brewer)
        .where(models.Brewer.user_id == user_id)
        .order_by(models.Brewer.name)
    ).all())


def get_grinders(session: Session, user_id: int) -> List[models.Grinder]:
    return list(session.exec(
        select(models.Grinder)
        .where(models.Grinder.user_id == user_id)
        .order_by(models.Grinder.name)
    ).all())


def get_bags_for_bean(session: Session, bean_id: int) -> List[models.BeanBag]:
    return session.exec(
        select(models.BeanBag)
        .where(models.BeanBag.bean_id == bean_id)
        .order_by(models.BeanBag.purchase_date.desc())  # type: ignore[union-attr]
    ).all()


def get_active_bags_for_user(session: Session, user_id: int) -> List[models.BeanBag]:
    return session.exec(
        select(models.BeanBag)
        .join(models.Bean, models.Bean.id == models.BeanBag.bean_id)  # type: ignore[arg-type]
        .where(models.Bean.user_id == user_id)
        .where(models.BeanBag.is_completed == False)  # noqa: E712
        .order_by(models.BeanBag.purchase_date.desc())  # type: ignore[union-attr]
    ).all()


def get_remaining_quantity(session: Session, bag: models.BeanBag) -> float:
    used = session.exec(
        select(func.sum(models.Recipe.dose_g))
        .join(models.Brew, models.Brew.recipe_id == models.Recipe.id)  # type: ignore[arg-type]
        .where(models.Brew.bag_id == bag.id)
    ).first()
    return bag.initial_quantity_g - (used or 0.0)


def get_lines_for_combo(session: Session, bean_id: int, brewer_id: int, grinder_id: int) -> List[models.RecipeLine]:
    """Named recipes for a combination, most recently used first.

    "Used" is the newest version or brew in the line, so the first entry is
    the one the brew page opens by default.
    """
    lines = session.exec(
        select(models.RecipeLine)
        .where(models.RecipeLine.bean_id == bean_id)
        .where(models.RecipeLine.brewer_id == brewer_id)
        .where(models.RecipeLine.grinder_id == grinder_id)
    ).all()

    def last_used(line: models.RecipeLine):
        recipe_at = session.exec(
            select(func.max(models.Recipe.created_at)).where(models.Recipe.line_id == line.id)
        ).first()
        brew_at = session.exec(
            select(func.max(models.Brew.brewed_at))
            .join(models.Recipe, models.Recipe.id == models.Brew.recipe_id)  # type: ignore[arg-type]
            .where(models.Recipe.line_id == line.id)
        ).first()
        # SQLite hands back naive datetimes; a just-created line may be aware
        return max(t.replace(tzinfo=None) for t in (recipe_at, brew_at, line.created_at) if t is not None)

    return sorted(lines, key=lambda line: (last_used(line), line.id or 0), reverse=True)


def get_latest_recipe(session: Session, line_id: int) -> Optional[models.Recipe]:
    return session.exec(
        select(models.Recipe)
        .where(models.Recipe.line_id == line_id)
        .order_by(models.Recipe.created_at.desc())  # type: ignore[union-attr]
    ).first()


def line_name_taken(session: Session, bean_id: int, brewer_id: int, grinder_id: int, name: str, exclude_line_id: Optional[int] = None) -> bool:
    return any(
        line.name.strip().lower() == name.strip().lower() and line.id != exclude_line_id
        for line in get_lines_for_combo(session, bean_id, brewer_id, grinder_id)
    )


def create_line(session: Session, bean_id: int, brewer_id: int, grinder_id: int, name: str) -> models.RecipeLine:
    line = models.RecipeLine(bean_id=bean_id, brewer_id=brewer_id, grinder_id=grinder_id, name=name)
    session.add(line)
    session.commit()
    session.refresh(line)
    return line


def rename_line(session: Session, line_id: int, name: str) -> Optional[models.RecipeLine]:
    line = session.get(models.RecipeLine, line_id)
    if not line:
        return None
    line.name = name
    session.commit()
    return line


def delete_line(session: Session, line_id: int) -> None:
    recipe_ids = [r.id for r in session.exec(
        select(models.Recipe).where(models.Recipe.line_id == line_id)
    ).all()]
    _delete_recipes(session, recipe_ids)  # type: ignore[arg-type]
    _delete_lines(session, [line_id])
    session.commit()


def get_recent_brews(session: Session, recipe_id: int, limit: int = 5) -> List[models.Brew]:
    return session.exec(
        select(models.Brew)
        .where(models.Brew.recipe_id == recipe_id)
        .order_by(models.Brew.brewed_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def get_line_history(session: Session, line_id: int) -> List[Tuple[models.Delta, models.Recipe, models.Recipe]]:
    """Every change in a named recipe, oldest first, as (delta, from_version, to_version)."""
    rows = []
    for delta in session.exec(
        select(models.Delta)
        .join(models.Recipe, models.Recipe.id == models.Delta.to_recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.line_id == line_id)
        .order_by(models.Delta.created_at)
    ).all():
        before = session.get(models.Recipe, delta.from_recipe_id)
        after = session.get(models.Recipe, delta.to_recipe_id)
        if before and after:
            rows.append((delta, before, after))
    return rows


def get_recent_deltas(session: Session, line_id: int, limit: int = 10) -> List[models.Delta]:
    return session.exec(
        select(models.Delta)
        .join(models.Recipe, models.Recipe.id == models.Delta.to_recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.line_id == line_id)
        .order_by(models.Delta.created_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    ).all()


def create_bean(session: Session, user_id: int, name: str, origin: Optional[str] = None, roast_level: Optional[str] = None, flavor_notes: Optional[str] = None, notes: Optional[str] = None) -> models.Bean:
    bean = models.Bean(user_id=user_id, name=name, origin=origin, roast_level=roast_level, flavor_notes=flavor_notes, notes=notes)
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


def create_brewer(session: Session, user_id: int, name: str, method: Optional[str] = None, notes: Optional[str] = None) -> models.Brewer:
    brewer = models.Brewer(user_id=user_id, name=name, method=method, notes=notes)
    session.add(brewer)
    session.commit()
    session.refresh(brewer)
    return brewer


def create_grinder(session: Session, user_id: int, name: str, notes: Optional[str] = None) -> models.Grinder:
    grinder = models.Grinder(user_id=user_id, name=name, notes=notes)
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


def _delete_recipes(session: Session, recipe_ids: List[int]) -> None:
    """Delete recipes plus the deltas and brews that reference them. No commit."""
    if not recipe_ids:
        return
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
        select(models.Recipe).where(models.Recipe.id.in_(recipe_ids))  # type: ignore[union-attr]
    ).all():
        session.delete(recipe)


def _delete_lines(session: Session, line_ids: List[int]) -> None:
    """Delete named recipes and plans pointing at them (their recipes must already be gone). No commit."""
    if not line_ids:
        return
    for plan in session.exec(
        select(models.PlannedBrew).where(models.PlannedBrew.line_id.in_(line_ids))  # type: ignore[union-attr]
    ).all():
        session.delete(plan)
    for line in session.exec(
        select(models.RecipeLine).where(models.RecipeLine.id.in_(line_ids))  # type: ignore[union-attr]
    ).all():
        session.delete(line)


def delete_bean(session: Session, bean_id: int) -> None:
    _delete_recipes(session, [r.id for r in session.exec(  # type: ignore[misc]
        select(models.Recipe).where(models.Recipe.bean_id == bean_id)
    ).all()])
    _delete_lines(session, [line.id for line in session.exec(  # type: ignore[misc]
        select(models.RecipeLine).where(models.RecipeLine.bean_id == bean_id)
    ).all()])

    for bag in session.exec(select(models.BeanBag).where(models.BeanBag.bean_id == bean_id)).all():
        for brew in session.exec(select(models.Brew).where(models.Brew.bag_id == bag.id)).all():
            session.delete(brew)
        _delete_plans_for_bag(session, bag.id)  # type: ignore[arg-type]
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
    for brew in session.exec(select(models.Brew).where(models.Brew.bag_id == bag_id)).all():
        session.delete(brew)
    _delete_plans_for_bag(session, bag_id)
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
    _delete_recipes(session, [r.id for r in session.exec(  # type: ignore[misc]
        select(models.Recipe).where(models.Recipe.brewer_id == brewer_id)
    ).all()])
    _delete_lines(session, [line.id for line in session.exec(  # type: ignore[misc]
        select(models.RecipeLine).where(models.RecipeLine.brewer_id == brewer_id)
    ).all()])
    for plan in session.exec(select(models.PlannedBrew).where(models.PlannedBrew.brewer_id == brewer_id)).all():
        session.delete(plan)
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
    _delete_recipes(session, [r.id for r in session.exec(  # type: ignore[misc]
        select(models.Recipe).where(models.Recipe.grinder_id == grinder_id)
    ).all()])
    _delete_lines(session, [line.id for line in session.exec(  # type: ignore[misc]
        select(models.RecipeLine).where(models.RecipeLine.grinder_id == grinder_id)
    ).all()])
    for plan in session.exec(select(models.PlannedBrew).where(models.PlannedBrew.grinder_id == grinder_id)).all():
        session.delete(plan)
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
    old_text = base.recipe_text or ""
    new_text = new_values.get("recipe_text") or ""
    if old_text != new_text:
        changed.append("recipe_text")
    return (len(changed) == 1, changed)


def create_recipe(session: Session, bean_id: int, brewer_id: int, grinder_id: int, line_id: int, dose_g: float, water_ml: float, temp_c: float, grind_size: str, recipe_text: Optional[str] = None, previous_recipe_id: Optional[int] = None) -> models.Recipe:
    recipe = models.Recipe(
        bean_id=bean_id,
        brewer_id=brewer_id,
        grinder_id=grinder_id,
        line_id=line_id,
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


def get_pending_plan(session: Session, user_id: int) -> Optional[models.PlannedBrew]:
    return session.exec(
        select(models.PlannedBrew)
        .where(models.PlannedBrew.user_id == user_id)
        .order_by(models.PlannedBrew.created_at.desc())  # type: ignore[union-attr]
    ).first()


def create_plan(session: Session, user_id: int, bag_id: int, brewer_id: int, grinder_id: int, notes: Optional[str] = None, line_id: Optional[int] = None) -> models.PlannedBrew:
    for existing in session.exec(
        select(models.PlannedBrew).where(models.PlannedBrew.user_id == user_id)
    ).all():
        session.delete(existing)
    plan = models.PlannedBrew(user_id=user_id, bag_id=bag_id, brewer_id=brewer_id, grinder_id=grinder_id, line_id=line_id, notes=notes)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def delete_plan(session: Session, plan_id: int) -> None:
    plan = session.get(models.PlannedBrew, plan_id)
    if plan:
        session.delete(plan)
    session.commit()


def _delete_plans_for_bag(session: Session, bag_id: int) -> None:
    for plan in session.exec(select(models.PlannedBrew).where(models.PlannedBrew.bag_id == bag_id)).all():
        session.delete(plan)


def get_latest_recipe_per_bean(session: Session, user_id: int):
    beans = session.exec(
        select(models.Bean)
        .where(models.Bean.user_id == user_id)
        .order_by(models.Bean.name)
    ).all()
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
