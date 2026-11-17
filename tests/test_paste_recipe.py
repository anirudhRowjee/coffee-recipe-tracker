"""
Paste a recipe: a chatbot's answer (or any written recipe) read into the new-recipe form.
/recipes/paste only reads; the page fills the form and the person saves it as usual.
"""
from app import brew
from test_accounts import add_user
from test_flows import BASELINE, app, post  # noqa: F401 — app is a fixture

CHATBOT = """Here's a recipe for your Ethiopian on the Switch!

**Coffee:** 15 g
**Water:** 250 ml
**Temperature:** 93 °C
**Grind:** 18 clicks on the Comandante.

### Method:
- Prep: Rinse paper, valve open.
- 0:00 — Bloom (to 50g)
- 0:45 — Pour (to 150g)
- 1:30 — Pour (to 250g)
- 2:00 — Close valve, swirl
- 2:45 — Open valve, drawdown

Enjoy your cup!"""


def test_a_chatbot_answer_in_the_asked_for_format_is_read_exactly():
    found = brew.read_pasted(CHATBOT)
    assert (found.dose_g, found.water_ml, found.temp_c, found.grind_size) == (15, 250, 93, "18 clicks on the Comandante")
    assert found.method.splitlines()[0] == "Prep: Rinse paper, valve open."
    assert found.method.splitlines()[-1] == "2:45 — Open valve, drawdown"
    assert brew.is_standard(found.method) and found.checks == [] and found.missing == []


def test_a_looser_answer_is_read_with_its_guesses_flagged():
    found = brew.read_pasted("Dose = 18g\nRatio: 1:16\nWater temp: 200°F\nGrind size: medium-fine\n"
                             "1. Bloom with 50g water for 45s\n2. Pour to 150g at 0:45\n3. At 1:30 pour to 288g")
    assert (found.dose_g, found.water_ml, found.temp_c, found.grind_size) == (18, 288, 93, "medium-fine")
    assert brew.is_standard(found.method) and found.checks  # rows it had to guess are marked


def test_nothing_is_made_up():
    found = brew.read_pasted("Some thoughts on coffee, with no numbers at all.")
    assert found.dose_g is None and found.water_ml is None and found.grind_size is None
    assert brew.read_pasted("").missing == ["Coffee", "Water", "Temp", "Grind", "Method"]


def test_the_route_fills_the_form_and_saves_nothing(app):
    before = app.scalar("select count(*) from recipe")
    r = app.client.post("/recipes/paste", data={"text": CHATBOT})
    body = r.json()
    assert body["dose_g"] == 15 and body["grind_size"] == "18 clicks on the Comandante" and body["missing"] == []
    assert 'name="recipe_text"' in body["method_html"] and "0:45 — Pour (to 150g)" in body["method_html"]
    assert app.scalar("select count(*) from recipe") == before
    app.client.cookies.clear()
    assert app.client.post("/recipes/paste", data={"text": CHATBOT}, follow_redirects=False).status_code in (302, 303)


def test_the_box_is_offered_with_a_prompt_naming_the_coffee_and_gear(app):
    uid = add_user(app)
    app.sign_in(uid)
    post(app, "/beans", {"name": "Attikan", "initial_quantity_g": "250", "roast_level": "Medium"})
    post(app, "/brewers", {"name": "Hario Switch", "method": "Switch"})
    post(app, "/grinders", {"name": "Comandante"})
    ids = {k: app.scalar(f"select max(id) from {t}") for k, t in (("bag_id", "beanbag"), ("brewer_id", "brewer"), ("grinder_id", "grinder"))}
    html = app.client.get("/", params=ids).text
    assert "Paste a recipe from a chatbot" in html and "data-method-field" in html
    assert "for Attikan (Medium roast)" in html and "on a Hario Switch with a Comandante" in html
    # and once there's a recipe, in New recipe too
    post(app, "/recipes", {**BASELINE, "bean_id": app.scalar("select max(id) from bean"),
                           "brewer_id": ids["brewer_id"], "grinder_id": ids["grinder_id"]})
    assert "Paste a recipe from a chatbot" in app.client.get("/", params=ids).text
