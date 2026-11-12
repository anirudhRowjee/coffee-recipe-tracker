"""
Putting gear away: out of the pickers, its recipes and cups kept, and back again.
"""
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture


def test_put_away_and_bring_back(app):
    post(app, "/recipes", BASELINE)
    post(app, "/brewers/1/archive", {})
    assert app.scalar("select archived from brewer where id = 1") == 1
    assert app.scalar("select count(*) from recipe") == 1  # kept
    settings = app.client.get("/manage").text
    assert "Put away (1)" in settings and "Bring back" in settings
    page = app.client.get("/", params={"bag_id": 1}).text
    assert 'href="/?bag_id=1&amp;brewer_id=1' not in page.split('id="gear-sheet"')[-1]  # not offered as a chip
    post(app, "/brewers/1/archive", {"archived": "0"})
    assert app.scalar("select archived from brewer where id = 1") == 0


def test_only_brewers_and_grinders(app):
    assert app.client.post("/beans/1/archive", data={}).status_code == 404
