"""
Help: every "?" tip has words behind it, the How this works page, and the tour's
targets on Brew.
"""
import markupsafe
import re
from pathlib import Path

from app.tips import TIPS
from test_flows import BASELINE, app, latest, post  # noqa: F401 — app is a fixture

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_every_tip_used_in_a_template_has_text():
    used = set()
    for path in TEMPLATES.rglob("*.html"):
        used |= set(re.findall(r"tip\('([a-z_]+)'", path.read_text()))
        used |= set(re.findall(r"TIPS\.([a-z_]+)", path.read_text()))
    assert used, "no tips found"
    assert used <= set(TIPS), used - set(TIPS)
    assert all(len(text) < 220 for text in TIPS.values())


def test_tips_render_as_popovers_on_the_recipe(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert 'class="tip-btn" popovertarget="tip-grind-' in html
    assert str(markupsafe.escape(TIPS["grind"])) in html


def test_the_tour_points_at_the_recipe_and_start(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert 'data-tour="1"' in html and 'data-tour="2"' in html


def test_how_this_works(app):
    page = app.client.get("/help").text
    assert "How this works" in page and "/?tour=1" in page and str(markupsafe.escape(TIPS["one_change"])) in page
    assert "/help" in app.client.get("/manage").text
