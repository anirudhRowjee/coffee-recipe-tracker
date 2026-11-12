"""
Form checks: a refused form shows a page that says what was wrong (and goes back with
the typed values kept); the pages carry what the page-side checks need; finishing a
bag can be done while logging.
"""
from test_flows import BASELINE, COMBO, app, latest, post  # noqa: F401 — app is a fixture


def test_a_refused_form_says_what_was_wrong(app):
    post(app, "/recipes", BASELINE)
    r = app.client.post("/recipes", data={**BASELINE, "previous_recipe_id": 1, "temp_c": "96", "dose_g": "16"},
                        headers={"accept": "text/html"})
    assert r.status_code == 400 and "Not saved" in r.text and "Coffee and Temp" in r.text and "history.back()" in r.text


def test_a_missing_field_is_named(app):
    r = app.client.post("/recipes", data={"bean_id": 1, "brewer_id": 1, "grinder_id": 1, "dose_g": "lots"},
                        headers={"accept": "text/html"})
    assert r.status_code == 422 and "Coffee needs to be a number." in r.text and "Water is missing." in r.text


def test_api_style_requests_still_get_plain_errors(app):
    r = app.client.post("/recipes", data={"bean_id": 1}, headers={"accept": "application/json"})
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/json")


def test_pages_carry_what_the_checks_need(app):
    post(app, "/recipes", BASELINE)
    html = latest(app)
    assert 'data-taken="[&#34;Default&#34;]"' in html  # names you already use
    assert 'data-draft="log-1"' in html  # tasting notes kept as a draft
    assert 'min="70" max="100"' in app.client.get("/lines/1/change", params={"bag_id": 1}).text


def test_logging_the_last_of_a_bag_offers_to_finish_it(app):
    post(app, "/bags", {"bean_id": 1, "initial_quantity_g": 20})
    small = app.scalar("select max(id) from beanbag")
    post(app, "/recipes", BASELINE)
    html = latest(app, bag_id=small)
    assert "not enough for another" in html and 'name="finish_bag"' in html
    post(app, "/brews", {"recipe_id": 1, "bag_id": small, "finish_bag": "1"})
    assert app.scalar(f"select is_completed from beanbag where id = {small}") == 1
    assert 'name="finish_bag"' not in latest(app)  # the big bag has plenty
