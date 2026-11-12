// The 4:6 builder's live preview (four_six.html). The same maths as app/four_six.py's plan();
// the server rebuilds the recipe from the settings when it's saved.
(function () {
    var form = document.getElementById('four-six');
    if (!form) return;
    var INTERVAL = 45, DRAIN = 30;
    function plan(coffee, ratio, taste, bodyPours) {
        var water = coffee * ratio;
        var first = 0.5 - taste / 12;
        var parts = [0.4 * first, 0.4 * (1 - first)];
        for (var i = 0; i < bodyPours; i++) parts.push(0.6 / bodyPours);
        var pours = [], sum = 0, previous = 0;
        parts.forEach(function (share, i) {
            sum += share;
            var target = Math.round(water * sum);
            pours.push({ at: i * INTERVAL, add: target - previous, to: target, phase: i < 2 ? 'taste' : 'body' });
            previous = target;
        });
        return { water: Math.round(water), pours: pours, done: (pours.length - 1) * INTERVAL + DRAIN };
    }
    function clock(s) { return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
    function val(name) {
        var el = form.querySelector('[name="' + name + '"]');
        return el ? el.value : '';
    }
    // Roast slider: a name and a suggested temperature, written into the temperature box
    // unless you've set that yourself
    var roast = document.getElementById('fs-roast'), temp = document.getElementById('fs-temp');
    var temps = JSON.parse(roast.getAttribute('data-temps')), names = JSON.parse(roast.getAttribute('data-names'));
    var tempTouched = false;
    temp.addEventListener('input', function () { tempTouched = true; });
    function roastTemp(level) {
        for (var i = 1; i < temps.length; i++) {
            if (level <= temps[i][0]) {
                var a = temps[i - 1], b = temps[i];
                return Math.round(a[1] + (b[1] - a[1]) * (level - a[0]) / (b[0] - a[0]));
            }
        }
        return temps[temps.length - 1][1];
    }
    function roastName(level) {
        var name = names[0][1];
        names.forEach(function (n) { if (level >= n[0]) name = n[1]; });
        return name;
    }
    roast.addEventListener('input', function () {
        if (!tempTouched) temp.value = roastTemp(parseInt(roast.value, 10));
    });
    function render() {
        var coffee = parseFloat(val('coffee')), ratio = parseFloat(val('ratio'));
        var taste = parseFloat(val('taste')), body = parseInt(val('pours'), 10);
        var level = parseInt(roast.value, 10), suggested = roastTemp(level);
        document.getElementById('fs-roast-read').innerHTML = '<b>' + roastName(level) + '</b> · suggests ' + suggested + ' °C';
        if (!(coffee > 0) || !(ratio > 0)) return;
        var p = plan(coffee, ratio, taste, body);
        var word = Math.abs(taste) < 0.05 ? 'Balanced' : taste > 0 ? 'Sweeter' : 'Brighter';
        document.getElementById('fs-taste-read').innerHTML = '<b>' + word + '</b> · first pour ' + p.pours[0].add + ' g, second ' + p.pours[1].add + ' g';
        var bodies = { 1: 'Lightest', 2: 'Lighter', 3: 'Standard', 4: 'Strongest' };
        document.getElementById('fs-body-read').innerHTML = '<b>' + bodies[body] + '</b> · ' + body + ' pour' + (body > 1 ? 's' : '') + ' of ' + p.pours[2].add + ' g for the last 60%';
        document.getElementById('fs-water').textContent = p.water + ' g of water at ' + val('temp_c') + ' °C · done by ' + clock(p.done);
        document.getElementById('fs-bar').innerHTML = p.pours.map(function (pour) {
            return '<span class="' + pour.phase + '" style="flex-grow:' + Math.max(pour.add, 1) + '">' + pour.add + '</span>';
        }).join('');
        document.getElementById('fs-steps').innerHTML = p.pours.map(function (pour, i) {
            var name = i === 0 ? 'Bloom' : i === 1 ? 'Pour, taste' : 'Pour, strength';
            return '<li><span class="t">' + clock(pour.at) + '</span>' + name + '<span class="g">to ' + pour.to + ' g</span></li>';
        }).join('') + '<li><span class="t">' + clock(p.done) + '</span>Done</li>';
    }
    form.addEventListener('input', render);
    form.addEventListener('change', render);
    form.addEventListener('click', function (e) { if (e.target.closest('.stepper-btn')) setTimeout(render, 0); });
    render();
})();
