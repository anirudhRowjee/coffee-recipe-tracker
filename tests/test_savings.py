"""
Lifetime savings on the manage page: every brew you've logged, at the price of a
café cup (₹300), in Indian digit grouping.
"""
import pytest

from app.main import inr
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture


def savings(app):
    html = app.client.get("/manage").text
    start = html.index('class="card savings-card"')
    return html[start:html.index("</section>", start)]


@pytest.mark.parametrize("amount,shown", [
    (0, "₹0"), (300, "₹300"), (1200, "₹1,200"), (26100, "₹26,100"),
    (123456, "₹1,23,456"), (12345678, "₹1,23,45,678"),
])
def test_inr(amount, shown):
    assert inr(amount) == shown


def test_nothing_brewed_yet(app):
    card = savings(app)
    assert "Lifetime savings" in card and '<p class="savings-amount">₹0</p>' in card
    assert "Every brew you log adds ₹300" in card


def test_every_cup_counts(app):
    post(app, "/recipes", BASELINE)
    for _ in range(3):
        post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    card = savings(app)
    assert '<p class="savings-amount">₹900</p>' in card
    assert "3 cups brewed since" in card and "at ₹300 a café cup" in card
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    assert '<p class="savings-amount">₹1,200</p>' in savings(app)


def test_one_cup(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    assert "1 cup brewed since" in savings(app)


def test_only_your_own_cups(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brews", {"recipe_id": 1, "bag_id": 1})
    app.sign_in(add_user(app))
    assert '<p class="savings-amount">₹0</p>' in savings(app)
