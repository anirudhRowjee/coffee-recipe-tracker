import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Session, select

from . import auth, brew, models


def get_users(session: Session) -> List[models.User]:
    return list(session.exec(select(models.User).order_by(models.User.name)).all())


def get_user_by_session_token(session: Session, token: str) -> Optional[models.User]:
    row = session.get(models.UserSession, auth.session_token_hash(token))
    return session.get(models.User, row.user_id) if row else None


def create_user_session(session: Session, user_id: int) -> str:
    token = auth.new_session_token()
    session.add(models.UserSession(token_hash=auth.session_token_hash(token), user_id=user_id))
    session.commit()
    return token


def delete_user_session(session: Session, token: str) -> None:
    row = session.get(models.UserSession, auth.session_token_hash(token))
    if row:
        session.delete(row)
    session.commit()


def delete_sessions_for_user(session: Session, user_id: int, except_token: Optional[str] = None) -> None:
    keep = auth.session_token_hash(except_token) if except_token else None
    for row in session.exec(select(models.UserSession).where(models.UserSession.user_id == user_id)).all():
        if row.token_hash != keep:
            session.delete(row)
    session.commit()


def set_user_password(session: Session, user: models.User, password: str, must_change: bool) -> None:
    user.password_hash = auth.hash_password(password)
    user.must_change_password = must_change
    session.commit()


def name_taken(session: Session, name: str) -> bool:
    return any(u.name.strip().lower() == name.strip().lower() for u in get_users(session))


def set_brew_settings(session: Session, user: models.User, animation: bool, live_graph: bool) -> None:
    user.show_brew_animation = animation
    user.show_live_graph = live_graph
    session.add(user)
    session.commit()


def create_user(session: Session, name: str, password: str) -> models.User:
    user = models.User(name=name, password_hash=auth.hash_password(password), must_change_password=True)
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
    delete_sessions_for_user(session, user_id)
    for plan in session.exec(select(models.PlannedBrew).where(models.PlannedBrew.user_id == user_id)).all():
        session.delete(plan)
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


def get_brew_totals(session: Session, user_id: int) -> Tuple[int, Optional[datetime]]:
    """How many brews this user has logged, ever, and when the first was."""
    count, first = session.exec(
        select(func.count(models.Brew.id), func.min(models.Brew.brewed_at))  # type: ignore[arg-type]
        .join(models.BeanBag, models.BeanBag.id == models.Brew.bag_id)  # type: ignore[arg-type]
        .join(models.Bean, models.Bean.id == models.BeanBag.bean_id)  # type: ignore[arg-type]
        .where(models.Bean.user_id == user_id)
    ).one()
    return count, first


# Brew times are stored in UTC; days are counted where the app's people live.
# India has no daylight saving, so a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30))


def local_time(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC
    return aware.astimezone(IST)


def local_day(moment: datetime) -> date:
    return local_time(moment).date()


def get_brew_days(session: Session, user_id: int) -> List[date]:
    """Every day (India time) this user brewed at least once, oldest first."""
    times = session.exec(
        select(models.Brew.brewed_at)
        .join(models.BeanBag, models.BeanBag.id == models.Brew.bag_id)  # type: ignore[arg-type]
        .join(models.Bean, models.Bean.id == models.BeanBag.bean_id)  # type: ignore[arg-type]
        .where(models.Bean.user_id == user_id)
    ).all()
    return sorted({local_day(t) for t in times})


@dataclass
class Streaks:
    current: int            # days in a row up to today (or yesterday, if today's cup is still to come)
    brewed_today: bool
    longest: int
    longest_start: Optional[date]
    longest_end: Optional[date]
    this_month: int         # days brewed this calendar month


def streaks(days: List[date], today: date) -> Streaks:
    """Runs of consecutive brewing days. A streak isn't broken until a whole day passes
    without a brew, so this morning it still counts yesterday's."""
    longest, longest_start, longest_end = 0, None, None
    run_start, previous = None, None
    for day in days:
        if previous is None or day != previous + timedelta(days=1):
            run_start = day
        length = (day - run_start).days + 1  # type: ignore[operator]
        if length > longest:
            longest, longest_start, longest_end = length, run_start, day
        previous = day
    current = 0
    if previous is not None and previous >= today - timedelta(days=1):
        current = (previous - run_start).days + 1  # type: ignore[operator]
    return Streaks(
        current=current, brewed_today=previous == today, longest=longest,
        longest_start=longest_start, longest_end=longest_end,
        this_month=sum(1 for day in days if (day.year, day.month) == (today.year, today.month)),
    )


def user_has_recipes(session: Session, user_id: int) -> bool:
    return session.exec(
        select(models.Recipe.id).join(models.Bean).where(models.Bean.user_id == user_id).limit(1)  # type: ignore[arg-type]
    ).first() is not None


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


def pick_bag(session: Session, bean_id: int, exclude_empty: bool = True) -> Optional[models.BeanBag]:
    """Which bag of a coffee to brew from: the oldest open one that isn't frozen
    (by roast date, then purchase date), else a frozen one, else None."""
    bags = [b for b in get_bags_for_bean(session, bean_id) if not b.is_completed]
    if exclude_empty:
        bags = [b for b in bags if get_remaining_quantity(session, b) > 0]
    bags.sort(key=lambda b: (bool(b.is_frozen), b.roast_date or b.purchase_date or date.max, b.id or 0))
    return bags[0] if bags else None


def last_brewed_at(session: Session, bean_id: int) -> Optional[datetime]:
    return session.exec(
        select(func.max(models.Brew.brewed_at))
        .join(models.Recipe, models.Recipe.id == models.Brew.recipe_id)  # type: ignore[arg-type]
        .where(models.Recipe.bean_id == bean_id)
    ).first()


def coffees_to_brew(session: Session, user_id: int) -> List[Tuple[models.BeanBag, float, Optional[datetime]]]:
    """One entry per coffee with coffee left: (the bag to use, grams left, last brewed),
    the most recently brewed first, then the rest by name."""
    out = []
    for bean in session.exec(select(models.Bean).where(models.Bean.user_id == user_id).order_by(models.Bean.name)).all():
        bag = pick_bag(session, bean.id)  # type: ignore[arg-type]
        if bag:
            out.append((bag, get_remaining_quantity(session, bag), last_brewed_at(session, bean.id)))  # type: ignore[arg-type]
    out.sort(key=lambda e: (e[2] is None, -(e[2].timestamp() if e[2] else 0)))
    return out


def gear_for_bean(session: Session, bean_id: int) -> Optional[models.RecipeLine]:
    """The named recipe last used with a coffee: its brewer and grinder are the ones to suggest."""
    lines = get_lines_for_bean(session, bean_id)
    return lines[0] if lines else None


def copy_line(session: Session, source: models.RecipeLine, bean_id: int, brewer_id: int, grinder_id: int) -> models.RecipeLine:
    """Start a new named recipe for another coffee or gear from an existing one's current
    version (version 1 of the copy). Keeps the name if it's free there."""
    latest = get_latest_recipe(session, source.id)  # type: ignore[arg-type]
    name = source.name
    if get_lines_for_combo(session, bean_id, brewer_id, grinder_id):
        bean = session.get(models.Bean, source.bean_id)
        base = name if name != "Default" else f"From {bean.name if bean else 'another coffee'}"
        name, n = base, 2
        while line_name_taken(session, bean_id, brewer_id, grinder_id, name):
            name, n = f"{base} {n}", n + 1
    line = create_line(session, bean_id, brewer_id, grinder_id, name)
    create_recipe(session, bean_id=bean_id, brewer_id=brewer_id, grinder_id=grinder_id, line_id=line.id,  # type: ignore[arg-type]
                  dose_g=latest.dose_g, water_ml=latest.water_ml, temp_c=latest.temp_c,  # type: ignore[union-attr]
                  grind_size=latest.grind_size, recipe_text=latest.recipe_text)  # type: ignore[union-attr]
    return line


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
    return _most_recently_used_first(session, lines)


def get_lines_for_bean(session: Session, bean_id: int) -> List[models.RecipeLine]:
    """Every named recipe for a bean, across all its brewers and grinders, most recently used first."""
    lines = session.exec(select(models.RecipeLine).where(models.RecipeLine.bean_id == bean_id)).all()
    return _most_recently_used_first(session, lines)


def _most_recently_used_first(session: Session, lines) -> List[models.RecipeLine]:
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


def _version_it_was_tidied_from(session: Session, recipe: models.Recipe) -> Optional[models.Recipe]:
    delta = session.exec(
        select(models.Delta)
        .where(models.Delta.to_recipe_id == recipe.id)
        .where(models.Delta.changed_param == "recipe_text")
        .where(models.Delta.rationale == brew.TIDY_RATIONALE)
    ).first()
    return session.get(models.Recipe, delta.from_recipe_id) if delta else None


def get_recent_brews_for_panel(session: Session, recipe: models.Recipe) -> List[models.Brew]:
    """The version's brews. Tidying only reformats a method, so a freshly tidied
    version shows the brews (and recommendation) of the version it came from."""
    brews = get_recent_brews(session, recipe.id)  # type: ignore[arg-type]
    while not brews:
        source = _version_it_was_tidied_from(session, recipe)
        if not source:
            break
        recipe = source
        brews = get_recent_brews(session, recipe.id)  # type: ignore[arg-type]
    return brews


def line_recommendation(session: Session, line_id: int) -> Optional[models.Brew]:
    """The brew whose recommendation the panel shows for this named recipe: the newest
    brew of its current version (or the version it was tidied from), if it has one."""
    latest = get_latest_recipe(session, line_id)
    brews = get_recent_brews_for_panel(session, latest) if latest else []
    return brews[0] if brews and brews[0].recommended_param else None


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


def create_brew(session: Session, recipe_id: int, bag_id: int, notes: Optional[str] = None, recommended_param: Optional[str] = None, recommended_delta: Optional[float] = None, recommended_rationale: Optional[str] = None, rating: Optional[int] = None) -> models.Brew:
    brew = models.Brew(recipe_id=recipe_id, bag_id=bag_id, notes=notes, rating=rating, recommended_param=recommended_param, recommended_delta=recommended_delta, recommended_rationale=recommended_rationale)
    session.add(brew)
    session.commit()
    session.refresh(brew)
    return brew


# --- scale curves (brew mode's weight and flow readings, one per brew) -------------

MAX_CURVE_CHARS = 300_000   # ~2 readings/s for over an hour; a real brew is ~10 KB
MAX_CURVE_POINTS = 10_000


def parse_curve(raw: Optional[str]) -> Optional[str]:
    """The curve brew mode sent, checked and re-encoded compactly; None if it's missing
    or malformed. Malformed means a bug, not the user's fault, so the brew is still
    logged without it rather than losing the tasting notes."""
    if not raw or len(raw) > MAX_CURVE_CHARS:
        return None
    try:
        data = json.loads(raw)
        t, g, f = data["t"], data["g"], data["f"]
    except (ValueError, TypeError, KeyError):
        return None
    if not all(isinstance(xs, list) for xs in (t, g, f)) or not (2 <= len(t) == len(g) == len(f) <= MAX_CURVE_POINTS):
        return None
    try:
        t = [round(float(x), 1) for x in t]
        g = [round(float(x), 1) for x in g]
        f = [round(float(x), 2) for x in f]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in t + g + f):
        return None
    if t[0] < 0 or t[-1] > 7200 or any(b < a for a, b in zip(t, t[1:])):
        return None
    if any(abs(x) > 10_000 for x in g) or any(abs(x) > 1_000 for x in f):
        return None
    return json.dumps({"t": t, "g": g, "f": f}, separators=(",", ":"))


def save_curve(session: Session, brew_id: int, samples: str) -> None:
    session.add(models.BrewCurve(brew_id=brew_id, samples=samples))
    session.commit()


def get_curve(session: Session, brew_id: int) -> Optional[dict]:
    row = session.get(models.BrewCurve, brew_id)
    return json.loads(row.samples) if row else None


def brews_with_curves(session: Session, brew_ids: List[int]) -> set:
    """Which of these brews have a curve, without loading any of them."""
    if not brew_ids:
        return set()
    return set(session.exec(
        select(models.BrewCurve.brew_id).where(models.BrewCurve.brew_id.in_(brew_ids))  # type: ignore[attr-defined]
    ).all())


def line_brews_with_curves(session: Session, line_id: int) -> List[models.Brew]:
    """Brews of any version of this named recipe that have a curve, newest first."""
    return list(session.exec(
        select(models.Brew)
        .join(models.Recipe, models.Brew.recipe_id == models.Recipe.id)  # type: ignore[arg-type]
        .join(models.BrewCurve, models.BrewCurve.brew_id == models.Brew.id)  # type: ignore[arg-type]
        .where(models.Recipe.line_id == line_id)
        .order_by(models.Brew.brewed_at.desc(), models.Brew.id.desc())  # type: ignore[union-attr]
    ).all())


def latest_curve_for_recipe(session: Session, recipe_id: int) -> Optional[dict]:
    """The newest curve brewed with exactly this version, for the share image."""
    row = session.exec(
        select(models.BrewCurve)
        .join(models.Brew, models.BrewCurve.brew_id == models.Brew.id)  # type: ignore[arg-type]
        .where(models.Brew.recipe_id == recipe_id)
        .order_by(models.Brew.brewed_at.desc(), models.Brew.id.desc())  # type: ignore[union-attr]
    ).first()
    return json.loads(row.samples) if row else None


_BREWED_LINE = re.compile(r"^\s*Brewed \d+:\d\d\b.*$", re.MULTILINE)


def tasting_note(notes: Optional[str]) -> str:
    """A brew's notes as something to share: without brew mode's "Brewed 3:54 · 500 g"
    line, with Windows line ends and runs of blank lines tidied."""
    text = _BREWED_LINE.sub("", (notes or "").replace("\r\n", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def line_brews_with_notes(session: Session, line_id: int, limit: int = 30) -> List[models.Brew]:
    """Brews of any version of this named recipe that have a note worth sharing, newest first."""
    brews = session.exec(
        select(models.Brew)
        .join(models.Recipe, models.Brew.recipe_id == models.Recipe.id)  # type: ignore[arg-type]
        .where(models.Recipe.line_id == line_id)
        .order_by(models.Brew.brewed_at.desc(), models.Brew.id.desc())  # type: ignore[union-attr]
    ).all()
    return [b for b in brews if tasting_note(b.notes)][:limit]


def version_number(session: Session, recipe: models.Recipe) -> int:
    """1 for a named recipe's first version, 2 for the next, ..."""
    return len(session.exec(
        select(models.Recipe.id).where(models.Recipe.line_id == recipe.line_id, models.Recipe.created_at <= recipe.created_at)
    ).all()) or 1


def get_versions(session: Session, line_id: int) -> List[models.Recipe]:
    """A named recipe's versions, oldest first."""
    return session.exec(
        select(models.Recipe).where(models.Recipe.line_id == line_id).order_by(models.Recipe.created_at, models.Recipe.id)  # type: ignore[arg-type]
    ).all()


def delta_into(session: Session, recipe_id: int) -> Optional[models.Delta]:
    return session.exec(select(models.Delta).where(models.Delta.to_recipe_id == recipe_id)).first()


def brews_of(session: Session, recipe_ids: List[int]) -> Dict[int, List[models.Brew]]:
    """Each version's cups, newest first."""
    out: Dict[int, List[models.Brew]] = {i: [] for i in recipe_ids}
    if recipe_ids:
        for b in session.exec(select(models.Brew).where(models.Brew.recipe_id.in_(recipe_ids))  # type: ignore[union-attr]
                              .order_by(models.Brew.brewed_at.desc())).all():  # type: ignore[union-attr]
            out[b.recipe_id].append(b)
    return out


VALUE_FIELDS = ("dose_g", "water_ml", "temp_c", "grind_size", "recipe_text")


def undo_last_change(session: Session, line_id: int) -> Optional[models.Recipe]:
    """A new version with the newest version's one change put back: still a single change.
    None if the newest version is the first."""
    versions = get_versions(session, line_id)
    if len(versions) < 2 or not versions[-1].previous_recipe_id:
        return None
    latest = versions[-1]
    parent = session.get(models.Recipe, latest.previous_recipe_id)
    delta = delta_into(session, latest.id)  # type: ignore[arg-type]
    if not parent or not delta:
        return None
    param = delta.changed_param
    new = create_recipe(session, bean_id=latest.bean_id, brewer_id=latest.brewer_id, grinder_id=latest.grinder_id,
                        line_id=latest.line_id, dose_g=latest.dose_g, water_ml=latest.water_ml, temp_c=latest.temp_c,  # type: ignore[arg-type]
                        grind_size=latest.grind_size, recipe_text=latest.recipe_text, previous_recipe_id=latest.id)
    setattr(new, param, getattr(parent, param))
    session.add(new)
    session.commit()
    try:
        amount = round(float(getattr(parent, param)) - float(getattr(latest, param)), 3)
    except (TypeError, ValueError):
        amount = 0.0
    create_delta(session, from_recipe_id=latest.id, to_recipe_id=new.id, changed_param=param,  # type: ignore[arg-type]
                 delta_amount=amount, rationale=f"Undid version {len(versions)}'s change")
    session.refresh(new)
    return new


def fix_version(session: Session, recipe: models.Recipe, values: Dict, rationale: Optional[str]) -> None:
    """Correct the newest version in place: its values (checked by the caller) and reason;
    the delta into it is rewritten from the real values."""
    for name, value in values.items():
        setattr(recipe, name, value)
    session.add(recipe)
    delta = delta_into(session, recipe.id)  # type: ignore[arg-type]
    if delta:
        parent = session.get(models.Recipe, delta.from_recipe_id)
        valid, changed = validate_one_parameter_delta(parent, {f: getattr(recipe, f) for f in VALUE_FIELDS}) if parent else (False, [])
        if valid:
            delta.changed_param = changed[0]
            try:
                delta.delta_amount = round(float(getattr(recipe, changed[0])) - float(getattr(parent, changed[0])), 3)
            except (TypeError, ValueError):
                delta.delta_amount = 0.0
        delta.rationale = rationale
        session.add(delta)
    session.commit()


def delete_version(session: Session, recipe: models.Recipe) -> None:
    """Remove a version with no cups (the newest, saved by mistake), and the change into it."""
    for d in session.exec(select(models.Delta).where((models.Delta.to_recipe_id == recipe.id) | (models.Delta.from_recipe_id == recipe.id))).all():
        session.delete(d)
    session.delete(recipe)
    session.commit()


def update_brew(session: Session, brew: models.Brew, **fields) -> models.Brew:
    """Correct a logged cup: notes, rating, Next time, or the bag it came out of."""
    for name, value in fields.items():
        setattr(brew, name, value)
    session.add(brew)
    session.commit()
    session.refresh(brew)
    return brew


def delete_brew(session: Session, brew: models.Brew) -> dict:
    """Delete a cup (and its curve); returns everything needed to put it back."""
    curve = session.get(models.BrewCurve, brew.id)
    snapshot = {
        "recipe_id": brew.recipe_id, "bag_id": brew.bag_id, "notes": brew.notes, "rating": brew.rating,
        "recommended_param": brew.recommended_param, "recommended_delta": brew.recommended_delta,
        "recommended_rationale": brew.recommended_rationale, "brewed_at": brew.brewed_at,
        "curve": curve.samples if curve else None,
    }
    _delete_brew(session, brew)
    session.commit()
    return snapshot


def restore_brew(session: Session, snapshot: dict) -> Optional[models.Brew]:
    """Undo delete_brew, if the version and bag it belonged to still exist."""
    if not session.get(models.Recipe, snapshot["recipe_id"]) or not session.get(models.BeanBag, snapshot["bag_id"]):
        return None
    data = {k: v for k, v in snapshot.items() if k != "curve"}
    brew = models.Brew(**data)
    session.add(brew)
    session.commit()
    session.refresh(brew)
    if snapshot.get("curve"):
        session.add(models.BrewCurve(brew_id=brew.id, samples=snapshot["curve"]))  # type: ignore[arg-type]
        session.commit()
    return brew


def _delete_brew(session: Session, brew: models.Brew) -> None:
    """A brew and its curve. No commit."""
    curve = session.get(models.BrewCurve, brew.id)
    if curve:
        session.delete(curve)
    session.delete(brew)


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
        _delete_brew(session, brew)
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


def set_bean_image(session: Session, bean_id: int, data: bytes, content_type: str, accent_color: Optional[str], mesh_colors: Optional[str] = None) -> Optional[models.Bean]:
    bean = session.get(models.Bean, bean_id)
    if not bean:
        return None
    image = session.get(models.BeanImage, bean_id)
    if image:
        image.data = data
        image.content_type = content_type
    else:
        session.add(models.BeanImage(bean_id=bean_id, data=data, content_type=content_type))
    bean.accent_color = accent_color
    bean.mesh_colors = mesh_colors
    # A timestamp, not a counter: photo URLs are cached forever, so a version
    # must never come round again after a photo is removed and re-added
    bean.image_version = max(int(time.time()), (bean.image_version or 0) + 1)
    session.commit()
    return bean


def set_bean_colors(session: Session, bean_id: int, accent_color: Optional[str], mesh_colors: Optional[str]) -> Optional[models.Bean]:
    bean = session.get(models.Bean, bean_id)
    if not bean:
        return None
    bean.accent_color = accent_color
    bean.mesh_colors = mesh_colors
    session.commit()
    return bean


def delete_bean_image(session: Session, bean_id: int) -> None:
    image = session.get(models.BeanImage, bean_id)
    if image:
        session.delete(image)
    bean = session.get(models.Bean, bean_id)
    if bean:
        bean.accent_color = None
        bean.mesh_colors = None
        bean.image_version = None
    session.commit()


def delete_bean(session: Session, bean_id: int) -> None:
    image = session.get(models.BeanImage, bean_id)
    if image:
        session.delete(image)
    _delete_recipes(session, [r.id for r in session.exec(  # type: ignore[misc]
        select(models.Recipe).where(models.Recipe.bean_id == bean_id)
    ).all()])
    _delete_lines(session, [line.id for line in session.exec(  # type: ignore[misc]
        select(models.RecipeLine).where(models.RecipeLine.bean_id == bean_id)
    ).all()])

    for bag in session.exec(select(models.BeanBag).where(models.BeanBag.bean_id == bean_id)).all():
        for brew in session.exec(select(models.Brew).where(models.Brew.bag_id == bag.id)).all():
            _delete_brew(session, brew)
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
        _delete_brew(session, brew)
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
    # browsers submit textareas with \r\n, and the step editor's text is stored with \n
    old_text = "\n".join((base.recipe_text or "").splitlines()).strip()
    new_text = "\n".join((new_values.get("recipe_text") or "").splitlines()).strip()
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


def create_plan(session: Session, user_id: int, bag_id: int, brewer_id: int, grinder_id: int, notes: Optional[str] = None, line_id: Optional[int] = None,
                suggested_param: Optional[str] = None, suggested_delta: Optional[float] = None, suggested_rationale: Optional[str] = None) -> models.PlannedBrew:
    for existing in session.exec(
        select(models.PlannedBrew).where(models.PlannedBrew.user_id == user_id)
    ).all():
        session.delete(existing)
    plan = models.PlannedBrew(user_id=user_id, bag_id=bag_id, brewer_id=brewer_id, grinder_id=grinder_id, line_id=line_id, notes=notes,
                              suggested_param=suggested_param, suggested_delta=suggested_delta, suggested_rationale=suggested_rationale)
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
