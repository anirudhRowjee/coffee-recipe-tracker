"""
Brewing streaks on the manage page: consecutive days with a brew (India time),
the longest run, and days brewed this month.
"""
from datetime import date, datetime, timedelta, timezone

from app import crud, models
from app.main import day_range
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

TODAY = date(2026, 11, 10)


def d(*offsets):
    return [TODAY - timedelta(days=o) for o in sorted(offsets, reverse=True)]


def test_no_brews():
    s = crud.streaks([], TODAY)
    assert (s.current, s.longest, s.this_month, s.brewed_today) == (0, 0, 0, False)


def test_streak_up_to_today():
    s = crud.streaks(d(0, 1, 2, 5, 6), TODAY)
    assert (s.current, s.brewed_today, s.longest) == (3, True, 3)


def test_streak_survives_until_today_ends():
    s = crud.streaks(d(1, 2, 3), TODAY)  # nothing yet today
    assert (s.current, s.brewed_today) == (3, False)


def test_a_missed_day_ends_it():
    s = crud.streaks(d(2, 3, 4, 5), TODAY)
    assert (s.current, s.longest) == (0, 4)
    assert (s.longest_start, s.longest_end) == (TODAY - timedelta(days=5), TODAY - timedelta(days=2))


def test_longest_is_the_first_of_equals_and_this_month_counts_days():
    s = crud.streaks([date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 7)], TODAY)
    assert (s.longest, s.longest_start, s.this_month) == (3, date(2026, 10, 30), 4)


def test_days_are_india_time():
    # 20:00 UTC is 01:30 the next morning in India
    assert crud.local_day(datetime(2026, 11, 9, 20, 0)) == date(2026, 11, 10)
    assert crud.local_day(datetime(2026, 11, 9, 18, 0)) == date(2026, 11, 9)
    assert crud.local_day(datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)) == date(2026, 11, 10)


def test_day_range():
    assert day_range(date(2026, 10, 22), date(2026, 10, 29)) == "22–29 Oct 2026"
    assert day_range(date(2026, 10, 30), date(2026, 11, 2)) == "30 Oct – 2 Nov 2026"
    assert day_range(date(2025, 12, 30), date(2026, 1, 2)) == "30 Dec 2025 – 2 Jan 2026"
    assert day_range(date(2026, 11, 9), date(2026, 11, 9)) == "9 Nov 2026"


def card(app):
    html = app.client.get("/manage").text
    start = html.index('class="card streak-card"')
    return html[start:html.index("</section>", start)]


def set_brew_day(app, brew_id, day):
    with app.session() as s:
        b = s.get(models.Brew, brew_id)
        b.brewed_at = datetime(day.year, day.month, day.day, 3, 0)  # 08:30 in India
        s.add(b)
        s.commit()


def test_card(app):
    assert "<dd>0 days</dd>" in card(app) and "Log a brew today to start a streak." in card(app)
    post(app, "/recipes", BASELINE)
    today = datetime.now(crud.IST).date()
    for i, offset in enumerate([0, 1, 2], start=1):
        post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
        set_brew_day(app, i, today - timedelta(days=offset))
    html = card(app)
    assert "<dt>Current</dt><dd>3 days</dd>" in html
    assert "<dt>Longest</dt><dd>3 days</dd>" in html and day_range(today - timedelta(days=2), today) in html
    assert "Today's cup is in." in html


def test_card_one_day_and_only_your_own(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    assert "<dt>Current</dt><dd>1 day</dd>" in card(app)
    app.sign_in(add_user(app))
    assert "<dt>Current</dt><dd>0 days</dd>" in card(app)
