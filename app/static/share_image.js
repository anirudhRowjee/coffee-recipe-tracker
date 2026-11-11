// Share as image: draws a recipe card (1080×1350, Instagram's 4:5 post size) on a
// canvas from the data export.card_data put in data-card, then offers the phone's
// share sheet and a download. Drawn here because the server has no imaging library.
(function () {
    var host = document.getElementById('share-card');
    if (!host) return;
    var card = JSON.parse(host.getAttribute('data-card'));

    var W = 1080, H = 1350;
    var BORDER = 32, PAD = 56;  // the bag's colours around the card; space inside it
    var SERIF = "Georgia, 'Palatino Linotype', Palatino, serif";
    var SANS = "-apple-system, system-ui, 'Segoe UI', Helvetica, Arial, sans-serif";
    var INK = '#2c1810', MUTED = '#7a5a44', LABEL = '#8c6a4f', VALUE = '#3b1f0e', PAPER = '#faf6f0';
    var accent = card.colors.accent, soft = card.colors.soft;

    var canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    function font(weight, size, family) { ctx.font = weight + ' ' + size + 'px ' + family; }

    // Lines of `text` no wider than maxW in the current font (very long words are split)
    function wrap(text, maxW) {
        var lines = [], line = '';
        text.split(/\s+/).forEach(function (word) {
            if (!word) return;
            while (ctx.measureText(word).width > maxW && word.length > 1) {
                var cut = word.length;
                while (cut > 1 && ctx.measureText(word.slice(0, cut)).width > maxW) cut--;
                if (line) { lines.push(line); line = ''; }
                lines.push(word.slice(0, cut));
                word = word.slice(cut);
            }
            var tryLine = line ? line + ' ' + word : word;
            if (ctx.measureText(tryLine).width > maxW && line) { lines.push(line); line = word; } else { line = tryLine; }
        });
        if (line) lines.push(line);
        return lines;
    }

    // Wrapped lines, shrinking the font until they fit in maxLines (ellipsis if they never do)
    function fitLines(text, maxW, maxLines, weight, size, minSize, family) {
        var lines;
        for (; size >= minSize; size -= 2) {
            font(weight, size, family);
            lines = wrap(text, maxW);
            if (lines.length <= maxLines) return { lines: lines, size: size };
        }
        size += 2;
        lines = lines.slice(0, maxLines);
        var last = lines[maxLines - 1];
        while (last.length > 1 && ctx.measureText(last + '…').width > maxW) last = last.slice(0, -1);
        lines[maxLines - 1] = last + '…';
        return { lines: lines, size: size };
    }

    function roundRect(x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function background() {
        var mesh = card.colors.mesh;
        if (mesh) {
            // a 2×2 image of the four corner colours, stretched: the browser blends them smoothly
            var tiny = document.createElement('canvas');
            tiny.width = 2;
            tiny.height = 2;
            var t = tiny.getContext('2d');
            [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(function (p, i) {
                t.fillStyle = mesh[i];
                t.fillRect(p[0], p[1], 1, 1);
            });
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            ctx.drawImage(tiny, 0.5, 0.5, 1, 1, 0, 0, W, H);
        } else {
            var g = ctx.createLinearGradient(0, 0, W, H);
            g.addColorStop(0, accent);
            g.addColorStop(1, '#2c1810');
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, W, H);
        }
    }

    function draw(photo) {
        background();
        // Text only ever sits on the plain card, never on the colours
        ctx.fillStyle = PAPER;
        roundRect(BORDER, BORDER, W - 2 * BORDER, H - 2 * BORDER, 36);
        ctx.fill();

        var X = BORDER + PAD, CW = W - 2 * (BORDER + PAD), y = BORDER + PAD;
        ctx.textBaseline = 'alphabetic';

        var photoSize = 210, textW = CW;
        if (photo) {
            textW = CW - photoSize - 32;
            var px = X + CW - photoSize, scale = Math.max(photoSize / photo.width, photoSize / photo.height);
            var sw = photoSize / scale, sh = photoSize / scale;
            ctx.save();
            roundRect(px, y, photoSize, photoSize, 22);
            ctx.clip();
            ctx.drawImage(photo, (photo.width - sw) / 2, (photo.height - sh) / 2, sw, sh, px, y, photoSize, photoSize);
            ctx.restore();
        }

        var heading = fitLines(card.title, textW, 3, 'normal', 66, 44, SERIF);
        ctx.fillStyle = INK;
        heading.lines.forEach(function (line) {
            y += heading.size * 1.12;
            ctx.fillText(line, X, y);
        });
        y += 14;

        [[card.gear, MUTED, 'normal'], [card.about, MUTED, 'normal'], [card.flavour, INK, 'italic']].forEach(function (row) {
            if (!row[0]) return;
            var fitted = fitLines(row[0], textW, 2, row[2], 28, 24, SANS);
            ctx.fillStyle = row[1];
            fitted.lines.forEach(function (line) {
                y += fitted.size * 1.35;
                ctx.fillText(line, X, y);
            });
        });
        if (photo) y = Math.max(y, BORDER + PAD + photoSize);
        y += 36;

        // Every parameter, as tiles
        var gap = 16, cols = 3, tileW = (CW - gap * (cols - 1)) / cols, tileH = 128;
        card.params.forEach(function (param, i) {
            var tx = X + (i % cols) * (tileW + gap), ty = y + Math.floor(i / cols) * (tileH + gap);
            ctx.fillStyle = soft;
            roundRect(tx, ty, tileW, tileH, 18);
            ctx.fill();
            font('normal', 24, SANS);
            ctx.fillStyle = LABEL;
            ctx.fillText(param[0], tx + 22, ty + 40);
            var size = 52;
            do { font('bold', size, SANS); size -= 2; } while (ctx.measureText(param[1]).width > tileW - 44 && size > 22);
            ctx.fillStyle = VALUE;
            ctx.fillText(param[1], tx + 22, ty + 100);
        });
        y += Math.ceil(card.params.length / cols) * (tileH + gap) + 26;

        var footerY = H - BORDER - PAD + 12;
        var stepsBottom = footerY - 34;
        if (card.curve) {  // only when asked for (?curve=1): the weight through one brew
            stepsBottom -= CURVE_H + 20;
            drawCurve(X, CW, stepsBottom + 20);
        }
        if (card.steps.length) {
            font('normal', 38, SERIF);
            ctx.fillStyle = INK;
            y += 38;
            ctx.fillText('Method', X, y);
            y += 22;
            drawSteps(X, CW, y, stepsBottom);
        }

        ctx.strokeStyle = '#e3d5c3';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(X, footerY - 28);
        ctx.lineTo(X + CW, footerY - 28);
        ctx.stroke();
        font('normal', 24, SANS);
        ctx.fillStyle = MUTED;
        ctx.fillText('Coffee Recipe Tracker', X, footerY + 8);
        ctx.textAlign = 'right';
        ctx.fillText(card.date, X + CW, footerY + 8);
        ctx.textAlign = 'left';
    }

    var CURVE_H = 200;
    function drawCurve(X, CW, top) {
        var t = card.curve.t, g = card.curve.g, end = t[t.length - 1] || 1;
        var max = Math.max.apply(null, g.concat([1]));
        var plotTop = top + 44, plotH = CURVE_H - 56, plotW = CW - 120;
        font('normal', 24, SANS);
        ctx.fillStyle = LABEL;
        ctx.fillText('Weight through a brew', X, top + 26);
        ctx.strokeStyle = '#e3d5c3';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(X, plotTop + plotH);
        ctx.lineTo(X + plotW, plotTop + plotH);
        ctx.stroke();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 5;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        t.forEach(function (s, i) {
            var px = X + s / end * plotW, py = plotTop + plotH - Math.max(0, g[i]) / max * plotH;
            if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
        });
        ctx.stroke();
        var last = g[g.length - 1], secs = Math.round(end);
        font('bold', 36, SANS);
        ctx.fillStyle = VALUE;
        ctx.fillText(Math.round(last) + ' g', X + plotW + 20, plotTop + plotH - Math.max(0, last) / max * plotH + 12);
        font('normal', 24, SANS);
        ctx.fillStyle = LABEL;
        ctx.fillText(Math.floor(secs / 60) + ':' + ('0' + secs % 60).slice(-2), X + plotW + 20, plotTop + plotH);
    }

    // The method, at the largest size that fits; any steps that still don't are counted
    function drawSteps(X, CW, top, bottom) {
        var timed = card.steps.some(function (s) { return s.time; });
        var size, layout, shown;
        for (size = 32; size >= 22; size -= 2) {
            font('bold', size, SANS);
            var timeW = timed ? ctx.measureText('00:00').width + 24 : 0;
            font('normal', size, SANS);
            layout = card.steps.map(function (s) { return wrap(s.text, CW - timeW); });
            var height = 0;
            shown = 0;
            for (var i = 0; i < layout.length; i++) {
                var h = layout[i].length * size * 1.3 + size * 0.5;
                if (top + height + h > bottom - (i < layout.length - 1 ? size * 1.6 : 0)) break;
                height += h;
                shown++;
            }
            if (shown === layout.length) break;
        }
        size = Math.max(size, 22);
        font('bold', size, SANS);
        var timeW2 = timed ? ctx.measureText('00:00').width + 24 : 0;
        var y = top;
        for (var k = 0; k < shown; k++) {
            if (card.steps[k].time) {
                font('bold', size, SANS);
                ctx.fillStyle = accent;
                ctx.fillText(card.steps[k].time, X, y + size);
            }
            font('normal', size, SANS);
            ctx.fillStyle = INK;
            layout[k].forEach(function (line, j) { ctx.fillText(line, X + timeW2, y + size + j * size * 1.3); });
            y += layout[k].length * size * 1.3 + size * 0.5;
        }
        if (shown < card.steps.length) {
            font('italic', size, SANS);
            ctx.fillStyle = MUTED;
            var left = card.steps.length - shown;
            ctx.fillText('+ ' + left + ' more step' + (left === 1 ? '' : 's'), X + timeW2, y + size);
        }
    }

    function finish() {
        canvas.toBlob(function (blob) {
            var url = URL.createObjectURL(blob);
            var preview = document.getElementById('share-preview');
            preview.src = url;
            preview.hidden = false;
            document.getElementById('share-status').hidden = true;
            document.getElementById('share-hint').hidden = false;

            var save = document.getElementById('share-save');
            save.href = url;
            save.download = card.filename;
            save.hidden = false;

            var file = window.File ? new File([blob], card.filename, { type: 'image/png' }) : null;
            var button = document.getElementById('share-button');
            if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
                button.hidden = false;
                button.addEventListener('click', function () {
                    navigator.share({ files: [file], title: card.title })['catch'](function () { /* closed the sheet */ });
                });
            }
        }, 'image/png');
    }

    function start(photo) {
        draw(photo);
        finish();
    }

    if (card.photo) {
        var img = new Image();
        var done = false;
        img.onload = function () { if (!done) { done = true; start(img); } };
        img.onerror = function () { if (!done) { done = true; start(null); } };
        img.src = card.photo;
    } else {
        start(null);
    }
})();
