// Weight and flow graphs after a brew with the scale connected (static/scale.js hands
// over the readings when the timer stops). Two charts on one time axis, never one chart
// with two scales; the step targets are drawn as a dashed line on the weight chart.
// Hover or touch shows the reading at that moment on both. Nothing is saved.
(function () {
    var box = document.getElementById('brew-graphs');
    if (!box) return;
    var NS = 'http://www.w3.org/2000/svg';
    var W = 640, M = { left: 46, right: 14, top: 12, bottom: 26 };
    var charts = [];

    function el(name, attrs, parent) {
        var node = document.createElementNS(NS, name);
        for (var k in attrs) node.setAttribute(k, attrs[k]);
        if (parent) parent.appendChild(node);
        return node;
    }

    function num(v) { return Math.abs(v) < 0.05 ? '0.0' : v.toFixed(1); }  // never "-0.0"

    function fmt(s) { s = Math.round(s); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }

    // 0, step, 2·step… up to at least max, about four gridlines
    function ticks(lo, hi) {
        var span = Math.max(hi - lo, 1e-6), raw = span / 4, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
        var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).filter(function (s) { return s >= raw; })[0];
        var out = [];
        for (var v = Math.floor(lo / step) * step; v < hi + step * 0.999; v += step) out.push(Math.round(v * 1000) / 1000);
        return out;
    }

    function timeTicks(end) {
        var step = end <= 90 ? 15 : end <= 240 ? (W < 450 ? 60 : 30) : end <= 600 ? 60 : 120, out = [];  // fewer labels on a phone
        for (var t = 0; t <= end + 0.01; t += step) out.push(t);
        return out;
    }

    function chart(host, height, values, unit, end, targets) {
        host.innerHTML = '';
        var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
        if (targets) targets.forEach(function (t) { hi = Math.max(hi, t[1]); });
        // a scale's jitter around zero (−0.2 g) isn't worth a band below the axis
        lo = lo < -0.05 * Math.abs(hi) ? lo : 0;
        var yt = ticks(lo, hi * 1.05 || 1), y0 = yt[0], y1 = yt[yt.length - 1];
        var plotH = height - M.top - M.bottom, plotW = W - M.left - M.right;
        var x = function (t) { return M.left + t / end * plotW; };
        var y = function (v) { return M.top + (1 - (v - y0) / (y1 - y0)) * plotH; };

        var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + height, 'class': 'brew-graph', role: 'img' }, host);
        yt.forEach(function (v) {
            el('line', { x1: M.left, x2: W - M.right, y1: y(v), y2: y(v), 'class': v === 0 ? 'bg-base' : 'bg-grid' }, svg);
            el('text', { x: M.left - 6, y: y(v) + 4, 'class': 'bg-label', 'text-anchor': 'end' }, svg).textContent = v + (v === y1 ? ' ' + unit : '');
        });
        timeTicks(end).forEach(function (t) {
            el('text', { x: x(t), y: height - 8, 'class': 'bg-label', 'text-anchor': t === 0 ? 'start' : 'middle' }, svg).textContent = fmt(t);
        });
        if (targets && targets.length) {
            var d = '';
            targets.forEach(function (t, i) {
                var until = i + 1 < targets.length ? targets[i + 1][0] : end;
                if (t[0] > end) return;
                d += 'M' + x(t[0]).toFixed(1) + ',' + y(t[1]).toFixed(1) + 'H' + x(Math.min(until, end)).toFixed(1);
            });
            el('path', { d: d, 'class': 'bg-target' }, svg);
        }
        return { svg: svg, x: x, y: y, plotTop: M.top, plotBottom: M.top + plotH,
                 line: el('path', { 'class': 'bg-line' }, svg),
                 cross: el('line', { 'class': 'bg-cross', y1: M.top, y2: M.top + plotH, visibility: 'hidden' }, svg),
                 dot: el('circle', { r: 5, 'class': 'bg-dot', visibility: 'hidden' }, svg) };
    }

    function path(c, samples, k) {
        c.line.setAttribute('d', samples.map(function (s, i) {
            return (i ? 'L' : 'M') + c.x(s[0]).toFixed(1) + ',' + c.y(s[k]).toFixed(1);
        }).join(''));
    }

    window.BrewGraphs = {
        show: function (samples, targets) {
            box.hidden = false;  // shown first, so the charts can be drawn at its real width (labels stay 12px on a phone)
            W = Math.max(280, document.getElementById('brew-graph-weight').clientWidth || 640);
            var end = Math.max(samples[samples.length - 1][0], 10);
            var weights = samples.map(function (s) { return s[1]; }), flows = samples.map(function (s) { return s[2]; });
            var weight = chart(document.getElementById('brew-graph-weight'), 210, weights, 'g', end, targets);
            var flow = chart(document.getElementById('brew-graph-flow'), 150, flows, 'g/s', end, null);
            path(weight, samples, 1);
            path(flow, samples, 2);
            charts = [[weight, 1], [flow, 2]];

            var last = weights[weights.length - 1], peak = Math.max.apply(null, flows);
            var pouring = samples.filter(function (s) { return s[2] > 0.5; });
            var avg = pouring.length ? pouring.reduce(function (a, s) { return a + s[2]; }, 0) / pouring.length : 0;
            document.getElementById('brew-graphs-summary').textContent =
                fmt(end) + ' · ' + Math.round(last) + ' g in the cup · peak flow ' + peak.toFixed(1) +
                ' g/s · ' + avg.toFixed(1) + ' g/s while pouring';
            var readout = document.getElementById('brew-graphs-readout');
            var hint = 'Hover or touch the graphs for the reading at any moment.';
            readout.textContent = hint;

            function at(evt) {
                var svg = evt.currentTarget, rect = svg.getBoundingClientRect();
                var px = (evt.clientX - rect.left) / rect.width * W;
                var t = (px - M.left) / (W - M.left - M.right) * end;
                var lo = 0, hi = samples.length - 1;  // nearest sample by time
                while (lo < hi) { var mid = (lo + hi) >> 1; if (samples[mid][0] < t) lo = mid + 1; else hi = mid; }
                if (lo > 0 && t - samples[lo - 1][0] < samples[lo][0] - t) lo--;
                var s = samples[lo];
                charts.forEach(function (pair) {
                    var c = pair[0], cx = c.x(s[0]);
                    c.cross.setAttribute('x1', cx); c.cross.setAttribute('x2', cx);
                    c.dot.setAttribute('cx', cx); c.dot.setAttribute('cy', c.y(s[pair[1]]));
                    c.cross.setAttribute('visibility', 'visible'); c.dot.setAttribute('visibility', 'visible');
                });
                readout.textContent = fmt(s[0]) + ' · ' + num(s[1]) + ' g · ' + num(s[2]) + ' g/s';
            }
            function leave() {
                charts.forEach(function (pair) {
                    pair[0].cross.setAttribute('visibility', 'hidden'); pair[0].dot.setAttribute('visibility', 'hidden');
                });
                readout.textContent = hint;
            }
            charts.forEach(function (pair) {
                pair[0].svg.addEventListener('pointermove', at);
                pair[0].svg.addEventListener('pointerdown', at);
                pair[0].svg.addEventListener('pointerleave', leave);
            });
            box.hidden = false;
            if (box.scrollIntoView) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
        },
        hide: function () { box.hidden = true; }
    };
})();
