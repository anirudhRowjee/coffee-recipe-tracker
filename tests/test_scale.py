"""
Brew mode's Bookoo scale (static/scale.js): the page gives the script what it needs.
The Bluetooth side runs in the browser and is checked by hand with a real scale.
"""
import re

from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

METHOD = "Prep: Rinse the filter\n0:00 — Bloom (to 50g)\n0:45 — Pour (to 152.5g)\n1:30 — Swirl\n3:00 — Done"


def brew_page(app):
    r = app.client.get("/lines/1/brew", params={"bag_id": 1})
    assert r.status_code == 200
    return r.text


def test_steps_carry_their_targets(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    page = brew_page(app)
    assert 'data-times="0" data-grams="50.0">' in page
    assert 'data-times="45" data-grams="152.5">' in page
    assert 'data-times="90">' in page          # no target, no attribute
    assert 'data-times="">Before you start' in page


def test_grams_written_in_a_pour_count_as_its_target(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": "0:00 — Valve OPEN, 90g bloom + swirl\n0:40 — Pour (to 250g)\n1:30 — Add 2g salt? no, swirl"})
    page = brew_page(app)
    assert 'data-times="0" data-grams="90.0">' in page   # as the animation reads it
    assert 'data-times="90">' in page                     # grams in a step that isn't a pour are not a target


def test_scale_controls_are_hidden_until_the_script_shows_them(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    page = brew_page(app)
    assert re.search(r'<script src="/static/scale\.js\?v=[0-9a-f]{10}"></script>', page)
    for marker in ('id="brew-scale" hidden', 'id="brew-scale-connect" class="btn-secondary brew-scale-btn" hidden',
                   'id="brew-scale-tare" class="btn-secondary brew-scale-btn" hidden'):
        assert marker in page


def test_free_text_still_renders(app):
    post(app, "/recipes", BASELINE)
    page = brew_page(app)
    assert "data-grams" not in page
    assert 'id="brew-scale-connect"' in page


def test_script_is_served(app):
    r = app.client.get("/static/scale.js")
    assert r.status_code == 200 and "00000ffe-0000-1000-8000-00805f9b34fb" in r.text


def test_static_urls_change_when_the_file_does(app, tmp_path, monkeypatch):
    # so Bluefy and other browsers never keep running an old copy
    from app import main
    (tmp_path / "x.js").write_text("one")
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path)
    main.static_url.cache_clear()
    first = main.static_url("x.js")
    (tmp_path / "x.js").write_text("two")
    main.static_url.cache_clear()
    assert first.startswith("/static/x.js?v=") and main.static_url("x.js") != first
    main.static_url.cache_clear()


def test_graphs_section_waits_for_a_brew(app):
    post(app, "/recipes", {**BASELINE, "recipe_text": METHOD})
    page = brew_page(app)
    assert 'id="brew-graphs"' in page and 'id="brew-graphs" style=' in page
    assert page.index('id="brew-graphs"') < page.index("Log this brew")  # between the recipe and the log form
    assert page.index('/static/brew_graphs.js') < page.index('/static/scale.js')  # scale.js hands it the readings
    section = page[page.index('id="brew-graphs"'):]
    assert section[:section.index(">")].endswith("hidden")
