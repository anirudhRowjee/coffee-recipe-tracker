"""
The one-time welcome popup: who gets it, and that it says what to do. Remembering
that it was dismissed happens in the browser and is checked by hand.
"""
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

POPUP = 'id="welcome-overlay"'


def test_someone_with_no_recipes_is_welcomed(app):
    html = app.client.get("/").text
    assert POPUP in html
    assert 'class="bag-modal-overlay hidden" data-user="1"' in html  # only the script opens it
    steps = html[html.index('class="welcome-steps"'):html.index('id="welcome-done"')]
    assert steps.index("Add a bean and a bag") < steps.index("Add a brewer and a grinder") < steps.index("Add a baseline recipe")
    assert "No Grinder" in steps  # the pre-ground option
    assert 'href="/manage"' in steps


def test_gone_once_there_is_a_recipe(app):
    post(app, "/recipes", BASELINE)
    assert POPUP not in app.client.get("/").text


def test_someone_elses_recipes_dont_count(app):
    post(app, "/recipes", BASELINE)
    uid = add_user(app)
    app.sign_in(uid)
    assert f'data-user="{uid}"' in app.client.get("/").text


def test_only_on_the_brew_page(app):
    for page in ["/browse", "/manage"]:
        assert POPUP not in app.client.get(page).text
