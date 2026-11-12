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
        var el = form.querySelector('[name="' + name + '"]:checked') || form.querySelector('[name="' + name + '"]');
        return el ? el.value : '';
    }
    function render() {
        var coffee = parseFloat(val('coffee')), ratio = parseFloat(val('ratio'));
        if (!(coffee > 0) || !(ratio > 0)) return;
        var p = plan(coffee, ratio, parseFloat(val('taste')), parseInt(val('pours'), 10));
        var temp = form.querySelector('[name="roast"]:checked').getAttribute('data-temp');
        document.getElementById('fs-water').textContent = p.water + ' g of water at ' + temp + ' °C · done by ' + clock(p.done);
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
