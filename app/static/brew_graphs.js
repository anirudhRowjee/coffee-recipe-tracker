// Weight and flow graphs of a brew: right after it in brew mode (static/scale.js hands
// over the readings when the timer stops), and later on a logged brew's graph page
// (/brews/{id}/graph, data in data-graph), where another brew can be laid over it.
// Two charts on one time axis, never one chart with two scales; step targets dashed
// on the weight chart; hover or touch shows the reading at that moment on both.
// "Save as image" draws both charts into a PNG in the browser.
(function () {
    var NS = 'http://www.w3.org/2000/svg';
    var M = { left: 46, right: 14, top: 12, bottom: 26 };
    var INK = '#3b1f0e', MUTED = '#8c6a4f', COMPARE = '#b9a58f', PAPER = '#faf6f0';
    // the charts' look, also written into the SVG when it's saved as an image
    var CSS = '.bg-grid{stroke:#efe5d8;stroke-width:1}.bg-base{stroke:#d8c6b0;stroke-width:1}' +
        '.bg-label{font:12px -apple-system,system-ui,sans-serif;fill:' + MUTED + ';font-variant-numeric:tabular-nums}' +
        '.bg-target{fill:none;stroke:' + MUTED + ';stroke-width:1.5;stroke-dasharray:5 4}' +
        '.bg-line{fill:none;stroke:ACCENT;stroke-width:2;stroke-linejoin:round}' +
        '.bg-compare{fill:none;stroke:' + COMPARE + ';stroke-width:2;stroke-linejoin:round}' +
        '.bg-cross{stroke:' + MUTED + ';stroke-width:1}.bg-dot{fill:ACCENT;stroke:#fff;stroke-width:2}';

    function el(name, attrs, parent) {
        var node = document.createElementNS(NS, name);
        for (var k in attrs) node.setAttribute(k, attrs[k]);
        if (parent) parent.appendChild(node);
        return node;
    }
    function fmt(s) { s = Math.round(s); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
    function num(v) { return Math.abs(v) < 0.05 ? '0.0' : v.toFixed(1); }  // never "-0.0"
    function zip(c) { return c.t.map(function (t, i) { return [t, c.g[i], c.f[i]]; }); }
    function maxOf(xs) { return xs.reduce(function (a, b) { return b > a ? b : a; }, -Infinity); }
    function minOf(xs) { return xs.reduce(function (a, b) { return b < a ? b : a; }, Infinity); }

    // round gridlines from lo to at least hi, about four of them
    function ticks(lo, hi) {
        var span = Math.max(hi - lo, 1e-6), raw = span / 4, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
        var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).filter(function (s) { return s >= raw; })[0];
        var out = [];
        for (var v = Math.floor(lo / step) * step; v < hi + step * 0.999; v += step) out.push(Math.round(v * 1000) / 1000);
        return out;
    }
    function timeTicks(end, W) {
        var step = end <= 90 ? 15 : end <= 240 ? (W < 450 ? 60 : 30) : end <= 600 ? 60 : 120, out = [];  // fewer on a phone
        for (var t = 0; t <= end + 0.01; t += step) out.push(t);
        return out;
    }

    // one chart: series is [[samples, k, className], …], drawn in order (the main one last)
    function chart(host, W, height, series, unit, end, targets) {
        host.innerHTML = '';
        var values = [];
        series.forEach(function (s) { s[0].forEach(function (p) { values.push(p[s[1]]); }); });
        var lo = minOf(values), hi = maxOf(values);
        if (targets) targets.forEach(function (t) { hi = Math.max(hi, t[1]); });
        lo = lo < -0.05 * Math.abs(hi) ? lo : 0;  // a scale's jitter around zero isn't worth a band below the axis
        var yt = ticks(lo, hi * 1.05 || 1), y0 = yt[0], y1 = yt[yt.length - 1];
        var plotH = height - M.top - M.bottom, plotW = W - M.left - M.right;
        var x = function (t) { return M.left + t / end * plotW; };
        var y = function (v) { return M.top + (1 - (v - y0) / (y1 - y0)) * plotH; };

        var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + height, width: W, height: height, 'class': 'brew-graph', role: 'img' }, host);
        var every = plotH / (yt.length - 1) < 18 ? 2 : 1;  // a short chart (the live one) labels every other line
        yt.forEach(function (v, i) {
            el('line', { x1: M.left, x2: W - M.right, y1: y(v), y2: y(v), 'class': v === 0 ? 'bg-base' : 'bg-grid' }, svg);
            if ((yt.length - 1 - i) % every) return;
            el('text', { x: M.left - 6, y: y(v) + 4, 'class': 'bg-label', 'text-anchor': 'end' }, svg).textContent = v + (v === y1 ? ' ' + unit : '');
        });
        timeTicks(end, W).forEach(function (t) {
            el('text', { x: x(t), y: height - 8, 'class': 'bg-label', 'text-anchor': t === 0 ? 'start' : 'middle' }, svg).textContent = fmt(t);
        });
        if (targets && targets.length) {
            var d = '';
            targets.forEach(function (t, i) {
                if (t[0] > end) return;
                var until = i + 1 < targets.length ? targets[i + 1][0] : end;
                d += 'M' + x(t[0]).toFixed(1) + ',' + y(t[1]).toFixed(1) + 'H' + x(Math.min(until, end)).toFixed(1);
            });
            el('path', { d: d, 'class': 'bg-target' }, svg);
        }
        series.forEach(function (s) {
            el('path', { 'class': s[2], d: s[0].map(function (p, i) {
                return (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ',' + y(p[s[1]]).toFixed(1);
            }).join('') }, svg);
        });
        return { svg: svg, x: x, y: y,
                 cross: el('line', { 'class': 'bg-cross', y1: M.top, y2: M.top + plotH, visibility: 'hidden' }, svg),
                 dot: el('circle', { r: 5, 'class': 'bg-dot', visibility: 'hidden' }, svg) };
    }

    function nearest(samples, t) {
        var lo = 0, hi = samples.length - 1;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (samples[mid][0] < t) lo = mid + 1; else hi = mid; }
        if (lo > 0 && t - samples[lo - 1][0] < samples[lo][0] - t) lo--;
        return samples[lo];
    }

    function summary(samples) {
        var flows = samples.map(function (s) { return s[2]; });
        var pouring = samples.filter(function (s) { return s[2] > 0.5; });
        var avg = pouring.length ? pouring.reduce(function (a, s) { return a + s[2]; }, 0) / pouring.length : 0;
        return fmt(samples[samples.length - 1][0]) + ' · ' + Math.round(samples[samples.length - 1][1]) + ' g in the cup · peak flow ' +
            maxOf(flows).toFixed(1) + ' g/s · ' + avg.toFixed(1) + ' g/s while pouring';
    }

    // Draws into root's [data-graph=weight|flow], .bg-summary, .bg-legend and .bg-readout.
    // opts (brew mode's live graph): heights [weight, flow], and end, the time axis's length.
    function draw(root, samples, targets, compare, opts) {
        opts = opts || {};
        var weightHost = root.querySelector('[data-graph=weight]'), flowHost = root.querySelector('[data-graph=flow]');
        var W = Math.max(280, weightHost.clientWidth || 640);  // drawn at its real width, so labels stay 12px on a phone
        var other = compare ? compare.samples : null;
        var end = Math.max(samples[samples.length - 1][0], other ? other[other.length - 1][0] : 0, opts.end || 0, 10);
        var heights = opts.heights || [210, 150];
        var weightSeries = (other ? [[other, 1, 'bg-compare']] : []).concat([[samples, 1, 'bg-line']]);
        var flowSeries = (other ? [[other, 2, 'bg-compare']] : []).concat([[samples, 2, 'bg-line']]);
        var weight = chart(weightHost, W, heights[0], weightSeries, 'g', end, targets);
        var flow = chart(flowHost, W, heights[1], flowSeries, 'g/s', end, null);
        var charts = [[weight, 1], [flow, 2]];

        root.querySelector('.bg-summary').textContent = summary(samples);
        var legend = root.querySelector('.bg-legend');
        if (legend) {
            legend.hidden = !other;
            if (other) {
                legend.innerHTML = '';
                [['bg-key-main', root.getAttribute('data-label') || 'This brew'], ['bg-key-compare', compare.label]].forEach(function (k) {
                    var item = document.createElement('span');
                    var swatch = document.createElement('i');
                    swatch.className = k[0];
                    item.appendChild(swatch);
                    item.appendChild(document.createTextNode(k[1]));
                    legend.appendChild(item);
                });
            }
        }
        var readout = root.querySelector('.bg-readout');
        var hint = 'Hover or touch the graphs for the reading at any moment.';
        readout.textContent = hint;

        function at(evt) {
            var rect = evt.currentTarget.getBoundingClientRect();
            var t = ((evt.clientX - rect.left) / rect.width * W - M.left) / (W - M.left - M.right) * end;
            var s = nearest(samples, t);
            charts.forEach(function (pair) {
                var c = pair[0], cx = c.x(s[0]);
                c.cross.setAttribute('x1', cx); c.cross.setAttribute('x2', cx);
                c.dot.setAttribute('cx', cx); c.dot.setAttribute('cy', c.y(s[pair[1]]));
                c.cross.setAttribute('visibility', 'visible'); c.dot.setAttribute('visibility', 'visible');
            });
            var text = fmt(s[0]) + ' · ' + num(s[1]) + ' g · ' + num(s[2]) + ' g/s';
            if (other && t <= other[other.length - 1][0] + 1) {
                var o = nearest(other, s[0]);
                text += '  (other: ' + num(o[1]) + ' g · ' + num(o[2]) + ' g/s)';
            }
            readout.textContent = text;
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
    }

    // Both charts, a title and the summary in one PNG, drawn on a canvas (no server imaging)
    function savePng(root, title, filename, done) {
        var accent = getComputedStyle(root).getPropertyValue('--accent').trim() || '#6b3d2e';
        var svgs = Array.prototype.slice.call(root.querySelectorAll('svg.brew-graph'));
        var scale = 2, W = parseFloat(svgs[0].getAttribute('width')), pad = 24;
        var legend = root.querySelector('.bg-legend');
        var keys = legend && !legend.hidden ? Array.prototype.map.call(legend.children, function (n) { return n.textContent; }) : [];
        var heights = svgs.map(function (s) { return parseFloat(s.getAttribute('height')); });
        var canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');

        // The heading is laid out first (it wraps on a phone-width chart), then drawn
        var SANS = '-apple-system, system-ui, sans-serif', head = [];
        function lines(text, font, maxW) {  // words onto lines no wider than maxW
            ctx.font = font;
            var out = [], line = '';
            text.split(' ').forEach(function (word) {
                var tryLine = line ? line + ' ' + word : word;
                if (line && ctx.measureText(tryLine).width > maxW) { out.push(line); line = word; } else { line = tryLine; }
            });
            if (line) out.push(line);
            return out;
        }
        lines(title, '22px Georgia, serif', W).forEach(function (l) { head.push([l, '22px Georgia, serif', INK, 28]); });
        lines(root.querySelector('.bg-summary').textContent, '600 14px ' + SANS, W).forEach(function (l, i) {
            head.push([l, '600 14px ' + SANS, INK, i ? 19 : 26]);
        });
        var headH = head.reduce(function (a, h) { return a + h[3]; }, 0) + (keys.length ? keys.length * 22 + 6 : 0) + 16;
        var total = pad + headH + heights.reduce(function (a, b) { return a + b + 28; }, 0) + pad;
        canvas.width = (W + 2 * pad) * scale;
        canvas.height = total * scale;
        ctx.scale(scale, scale);
        ctx.fillStyle = PAPER;
        ctx.fillRect(0, 0, W + 2 * pad, total);
        var y = pad;
        head.forEach(function (h) {
            y += h[3];
            ctx.font = h[1];
            ctx.fillStyle = h[2];
            ctx.fillText(h[0], pad, y);
        });
        y += 6;
        keys.forEach(function (key, i) {  // one per row, so a long label never runs off
            y += 22;
            ctx.fillStyle = i ? COMPARE : accent;
            ctx.fillRect(pad, y - 6, 14, 4);
            ctx.font = '13px ' + SANS;
            ctx.fillStyle = MUTED;
            ctx.fillText(key, pad + 20, y);
        });
        y = pad + headH;
        var names = ['Weight', 'Flow rate'], loaded = 0;
        var images = svgs.map(function (svg) {
            var copy = svg.cloneNode(true);
            Array.prototype.forEach.call(copy.querySelectorAll('.bg-cross, .bg-dot'), function (n) { n.parentNode.removeChild(n); });
            var style = document.createElementNS(NS, 'style');
            style.textContent = CSS.replace(/ACCENT/g, accent);
            copy.insertBefore(style, copy.firstChild);
            copy.setAttribute('xmlns', NS);
            var img = new Image();
            img.onload = function () { if (++loaded === svgs.length) finish(); };
            img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(copy));
            return img;
        });
        function finish() {
            images.forEach(function (img, i) {
                ctx.fillStyle = INK;
                ctx.font = '600 13px -apple-system, system-ui, sans-serif';
                ctx.fillText(names[i], pad, y + 14);
                ctx.drawImage(img, pad, y + 22, W, heights[i]);
                y += heights[i] + 28;
            });
            canvas.toBlob(function (blob) { done(blob, filename); }, 'image/png');
        }
    }

    function offerPng(root, title, filename, button) {
        if (!button) return;
        button.addEventListener('click', function () {
            savePng(root, title, filename, function (blob) {
                var file = window.File ? new File([blob], filename, { type: 'image/png' }) : null;
                if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
                    navigator.share({ files: [file], title: title })['catch'](function () { /* closed the sheet */ });
                    return;
                }
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            });
        });
    }

    // Brew mode: scale.js calls show() when the timer stops (laid over this recipe's last
    // saved brew, if there is one), hide() on Reset, and live() while brewing when the
    // live graph is on in Manage
    var box = document.getElementById('brew-graphs');
    var liveBox = document.getElementById('brew-live');
    var last = null;
    if (box) {
        offerPng(box, box.getAttribute('data-title'), box.getAttribute('data-filename'), document.getElementById('brew-graphs-png'));
        try {
            var saved = box.getAttribute('data-compare');
            if (saved) { saved = JSON.parse(saved); last = { samples: zip(saved), label: saved.label }; }
        } catch (e) { last = null; }
    }
    window.BrewGraphs = {
        show: function (samples, targets) {
            if (!box) return;
            box.hidden = false;  // shown first, so the charts can be drawn at its real width
            draw(box, samples, targets, last);
        },
        hide: function () { if (box) box.hidden = true; },
        live: function (samples, targets, end) {
            if (liveBox && !liveBox.hidden) draw(liveBox, samples, targets, null, { heights: [170, 90], end: end });
        }
    };

    // A logged brew's graph page
    var page = document.getElementById('brew-graph-page');
    if (page) {
        var data = JSON.parse(page.getAttribute('data-graph'));
        var compare = data.compare ? { samples: zip(data.compare), label: data.compare.label } : null;
        draw(page, zip(data.brew), data.brew.targets, compare);
        offerPng(page, data.title, data.filename, document.getElementById('brew-graph-png'));
    }
})();
