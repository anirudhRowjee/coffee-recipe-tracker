"""
What was happening during a brew (static/brew_phases.js): pours, valve flicks (the Hario
Switch's lever: a spike that comes straight back) and the brewer off the scale, and the
readings with flicks smoothed out so they never show as flow. The classifier is the
browser's own JavaScript, run here with node (skipped where node isn't installed, as on
the VPS). Shapes are modelled on real Switch brews: a flick is one or two readings
10-46 g above the level, a pour about 8 g/s.
"""
import json
import shutil
import sqlite3
import subprocess

import pytest

from conftest import ROOT, copy_db

SCRIPT = ROOT / "app" / "static" / "brew_phases.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def classify(samples):
    js = f"const P = require({json.dumps(str(SCRIPT))}); console.log(JSON.stringify(P.classify({json.dumps(samples)})));"
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def switch_brew(rate=2.0, flicks=((80.0, 18.0), (125.0, 10.0)), lift_at=None, flick_len=0.5):
    """A Switch brew read `rate` times a second: bloom to 45 g, pours to 115 and 225 g,
    valve flicks (time, grams up) in the still parts, and optionally the brewer lifted off."""
    pours = [(0, 6, 0, 45), (50, 59, 45, 115), (86, 100, 115, 225)]
    samples, t, step = [], 0.0, 1 / rate
    while t <= 170:
        g = 0.0
        for a, b, g0, g1 in pours:
            if t >= b:
                g = g1
            elif t >= a:
                g = g0 + (g1 - g0) * (t - a) / (b - a)
        flow = next(((g1 - g0) / (b - a) for a, b, g0, g1 in pours if a <= t < b), 0.0)
        for at, up in flicks:
            if at <= t < at + flick_len:
                g, flow = g + up, 50.0  # the scale's own flow swings with it
        if lift_at and t >= lift_at:
            g, flow = -170.0, -250.0
        samples.append([round(t, 2), round(g, 1), round(flow, 2)])
        t += step
    return samples


@needs_node
@pytest.mark.parametrize("rate", [2.0, 10.0])
def test_valve_flicks_are_found_and_smoothed_out(rate):
    r = classify(switch_brew(rate=rate))
    kinds = [p["kind"] for p in r["phases"]]
    assert r["valves"] == 2 and r["pours"] == 3, kinds
    assert kinds == ["pour", "pour", "valve", "pour", "valve"]
    near = [s for s in r["samples"] if 79 <= s[0] <= 82]
    assert all(abs(s[1] - 115) < 1 for s in near)                # the weight stays put through the flick
    assert max(s[2] for s in r["samples"]) < 15                  # and no 50 g/s "flow"


@needs_node
def test_a_long_press_is_not_a_flick_and_a_pour_is_never_one():
    # held down for 3 s: not a quick flick, so it's left as it was rather than guessed at
    r = classify(switch_brew(flicks=((80.0, 18.0),), flick_len=3.0))
    assert r["valves"] == 0
    r = classify(switch_brew(flicks=()))
    assert r["valves"] == 0 and r["pours"] == 3


@needs_node
def test_the_brewer_lifted_off_at_the_end_is_cut_off():
    r = classify(switch_brew(lift_at=160))
    assert r["phases"][-1]["kind"] == "off" and r["phases"][-1]["from"] >= 159
    assert min(s[1] for s in r["samples"]) >= 0 and r["samples"][-1][1] == 225  # what's in the cup
    assert min(s[2] for s in r["samples"]) >= -3


@needs_node
def test_every_real_curve_reads_sensibly(reference_db, tmp_path):
    """On real brews: no flow faster than a kettle pours, nothing below zero, weights kept."""
    path = tmp_path / "ref.db"
    copy_db(reference_db, path)
    conn = sqlite3.connect(path)
    try:
        if "brewcurve" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}:
            pytest.skip("no curves in the reference database")
        curves = conn.execute("SELECT brew_id, samples FROM brewcurve").fetchall()
    finally:
        conn.close()
    for brew_id, raw in curves:
        d = json.loads(raw)
        r = classify([[t, g, f] for t, g, f in zip(d["t"], d["g"], d["f"])])
        flows = [s[2] for s in r["samples"]]
        assert max(flows) < 30 and min(flows) >= -3, brew_id
        assert min(s[1] for s in r["samples"]) > -5, brew_id
        assert len(r["samples"]) >= len(d["t"]) * 0.8, brew_id  # only an "off" end is ever dropped


def test_the_graphs_and_share_card_use_it_and_the_scale_holds_before_trusting_a_reading(app_on):
    for page in ("brew.html", "brew_graph.html", "share_image.html"):
        html = (ROOT / "app" / "templates" / page).read_text()
        tags = [html.find("static('%s')" % name) for name in ("brew_phases.js", "brew_graphs.js", "share_image.js")]
        assert 0 <= tags[0] < max(tags[1:]), page
    scale = (ROOT / "app" / "static" / "scale.js").read_text()
    assert "HOLD_MS = 800" in scale and "POUR_HOLD_MS = 1000" in scale and "steadyRecent" in scale
