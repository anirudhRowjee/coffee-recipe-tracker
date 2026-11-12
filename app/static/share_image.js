// Share as image: draws a recipe card (1080×1350, Instagram's 4:5 post size, or
// 1080×1920 for a story) on a canvas from the data export.card_data put in data-card,
// then offers the phone's share sheet and a download. Drawn here because the server
// has no imaging library. A tasting note, when offered (?notes=1), is picked and
// trimmed on the page and redrawn here: the text never leaves the browser.
(function () {
    var host = document.getElementById('share-card');
    if (!host) return;
    var card = JSON.parse(host.getAttribute('data-card'));

    var W = 1080, H = card.story ? 1920 : 1350;
    var BORDER = 32, PAD = 56;  // the bag's colours around the card; space inside it
    var SERIF = "Georgia, 'Palatino Linotype', Palatino, serif";
    var SANS = "-apple-system, system-ui, 'Segoe UI', Helvetica, Arial, sans-serif";
    var INK = '#2c1810', MUTED = '#7a5a44', LABEL = '#8c6a4f', VALUE = '#3b1f0e', PAPER = '#faf6f0';
    var PLAN = '#a8927c', LINE = '#e3d5c3', NOTE_BG = '#fffdf9';
    // the note on the card: {text, when, rating}, or null; set from the page's controls
    var note = null;
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

        // with a note or a curve on a post, everything above the method is a little smaller,
        // so the method still gets room
        compact = !card.story && !!(note || card.curve);
        var photoSize = compact ? 190 : 210, textW = CW;
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

        var heading = fitLines(card.title, textW, compact ? 2 : 3, 'normal', compact ? 60 : 66, 44, SERIF);
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
        var top0 = y + 36;

        var footerY = H - BORDER - PAD + 12;
        var bottom = footerY - 34;
        if (card.story) {
            // a story: the note and the brew up top, the whole recipe under them
            drawSteps(X, CW, drawMethodHeading(X, drawParams(X, CW, drawCurveBlock(X, CW, drawNoteBlock(X, CW, top0), STORY_CURVE_H))), bottom);
        } else {
            y = drawParams(X, CW, top0);
            var curveH = note ? 180 : CURVE_H;
            if (card.curve) { bottom -= curveH + 16; drawCurve(X, CW, bottom + 16, curveH); }
            if (note) { var nh = noteHeight(CW); bottom -= nh + 28; drawNote(X, CW, bottom + 12, nh); }
            if (card.steps.length) drawSteps(X, CW, drawMethodHeading(X, y), bottom);
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

    // Every parameter, as tiles; returns the y below them
    var compact = false;
    function drawParams(X, CW, y) {
        var gap = compact ? 14 : 16, cols = 3, tileW = (CW - gap * (cols - 1)) / cols, tileH = compact ? 100 : 128;
        card.params.forEach(function (param, i) {
            var tx = X + (i % cols) * (tileW + gap), ty = y + Math.floor(i / cols) * (tileH + gap);
            ctx.fillStyle = soft;
            roundRect(tx, ty, tileW, tileH, 18);
            ctx.fill();
            font('normal', 24, SANS);
            ctx.fillStyle = LABEL;
            ctx.fillText(param[0], tx + 22, ty + (compact ? 34 : 40));
            var size = compact ? 48 : 52;
            do { font('bold', size, SANS); size -= 2; } while (ctx.measureText(param[1]).width > tileW - 44 && size > 22);
            ctx.fillStyle = VALUE;
            ctx.fillText(param[1], tx + 22, ty + (compact ? 82 : 100));
        });
        return y + Math.ceil(card.params.length / cols) * (tileH + gap) + (compact ? 18 : 26);
    }

    function drawMethodHeading(X, y) {
        if (!card.steps.length) return y;
        font('normal', 38, SERIF);
        ctx.fillStyle = INK;
        ctx.fillText('Method', X, y + 38);
        return y + 60;
    }

    // The tasting note: on the plain card (never on the colours), the bag's colour down its edge
    var NOTE_PAD = 26;
    function noteLines(CW) {
        var text = note.text.replace(/\s+/g, ' ').trim();
        return card.story ? fitLines(text, CW - 2 * NOTE_PAD - 12, 5, 'italic', 46, 30, SERIF)
                          : fitLines(text, CW - 2 * NOTE_PAD - 12, 2, 'italic', 38, 32, SERIF);
    }
    function noteHeight(CW) {
        var fitted = noteLines(CW);
        return NOTE_PAD + fitted.lines.length * fitted.size * 1.32 + 16 + 26 + NOTE_PAD - 6;
    }
    function drawNote(X, CW, top, h) {
        ctx.fillStyle = NOTE_BG;
        roundRect(X, top, CW, h, 18);
        ctx.fill();
        ctx.strokeStyle = LINE;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.save();
        roundRect(X, top, CW, h, 18);
        ctx.clip();
        ctx.fillStyle = accent;
        ctx.fillRect(X, top, 10, h);
        ctx.restore();
        var fitted = noteLines(CW), y = top + NOTE_PAD;
        ctx.fillStyle = INK;
        font('italic', fitted.size, SERIF);
        fitted.lines.forEach(function (line) {
            y += fitted.size * 1.32;
            ctx.fillText(line, X + NOTE_PAD + 12, y - fitted.size * 0.25);
        });
        y += 16;
        font('normal', 24, SANS);
        ctx.fillStyle = LABEL;
        var label = 'From my notes' + (note.when ? ' · ' + note.when : '');
        ctx.fillText(label, X + NOTE_PAD + 12, y + 14);
        if (note.rating) {
            var lx = X + NOTE_PAD + 12 + ctx.measureText(label + '   ').width;
            font('normal', 28, SANS);
            for (var i = 0; i < 5; i++) {
                ctx.fillStyle = i < note.rating ? '#c68a3d' : '#e2d3bd';
                ctx.fillText('★', lx + i * 30, y + 16);
            }
        }
    }
    function drawNoteBlock(X, CW, y) {  // the story's: returns the y below it
        if (!note) return y;
        var h = noteHeight(CW);
        drawNote(X, CW, y, h);
        return y + h + 30;
    }
    var STORY_CURVE_H = 330;
    function drawCurveBlock(X, CW, y, h) {
        if (!card.curve) return y;
        drawCurve(X, CW, y, h);
        return y + h + 26;
    }

    // The weight through one brew, against this version's step targets (dashed)
    var CURVE_H = 200;
    function drawCurve(X, CW, top, height) {
        var t = card.curve.t, g = card.curve.g, plan = card.curve.targets || [];
        var end = Math.max(t[t.length - 1] || 1, plan.length ? plan[plan.length - 1][0] + 15 : 0);
        var max = Math.max.apply(null, g.concat(plan.map(function (p) { return p[1]; })).concat([1]));
        var plotTop = top + 44, plotH = height - 56, plotW = CW - 120;
        font('normal', 24, SANS);
        ctx.fillStyle = LABEL;
        ctx.fillText(plan.length ? 'My brew against the plan (dashed)' : 'Weight through a brew', X, top + 26);
        if (plan.length) {
            ctx.strokeStyle = PLAN;
            ctx.lineWidth = 3;
            ctx.setLineDash([12, 10]);
            ctx.beginPath();
            plan.forEach(function (p, i) {
                var until = i + 1 < plan.length ? plan[i + 1][0] : end, py = plotTop + plotH - p[1] / max * plotH;
                ctx.moveTo(X + p[0] / end * plotW, py);
                ctx.lineTo(X + until / end * plotW, py);
            });
            ctx.stroke();
            ctx.setLineDash([]);
        }
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
        var last = g[g.length - 1], secs = Math.round(t[t.length - 1] || 0);
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
        var size, layout, shown, smallest = compact ? 26 : card.story ? 26 : 22;
        for (size = card.story ? 34 : 32; size >= smallest; size -= 2) {
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
        size = Math.max(size, smallest);
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

    var file = null, lastUrl = null;
    function finish() {
        canvas.toBlob(function (blob) {
            var url = URL.createObjectURL(blob);
            if (lastUrl) URL.revokeObjectURL(lastUrl);
            lastUrl = url;
            var preview = document.getElementById('share-preview');
            preview.src = url;
            preview.hidden = false;
            document.getElementById('share-status').hidden = true;
            document.getElementById('share-hint').hidden = false;

            var save = document.getElementById('share-save');
            save.href = url;
            save.download = card.filename;
            save.hidden = false;

            var first = !file;
            file = window.File ? new File([blob], card.filename, { type: 'image/png' }) : null;
            var button = document.getElementById('share-button');
            if (first && file && navigator.canShare && navigator.canShare({ files: [file] })) {
                button.hidden = false;
                button.addEventListener('click', function () {
                    navigator.share({ files: [file], title: card.title })['catch'](function () { /* closed the sheet */ });
                });
            }
        }, 'image/png');
    }

    // The note controls (only on the page with ?notes=1): pick one, trim it, rating on or off
    var pick = document.getElementById('share-note-pick'), text = document.getElementById('share-note-text');
    var ratingRow = document.getElementById('share-note-rating-row'), ratingBox = document.getElementById('share-note-rating');
    var notes = card.notes || [];
    function chosen() {
        var n = notes[pick ? +pick.value : 0];
        return n || null;
    }
    function readNote() {
        var n = chosen();
        if (!n || !text || !text.value.trim()) { note = null; return; }
        note = { text: text.value, when: n.when.replace(/, \d\d:\d\d/, ''), rating: ratingBox && ratingBox.checked ? n.rating : null };
    }
    function choose() {
        var n = chosen();
        if (!n) return;
        text.value = n.text;
        ratingRow.hidden = !n.rating;
        ratingBox.checked = false;
    }

    var photoImg = null, redraw = null;
    function start(photo) {
        photoImg = photo;
        if (pick && notes.length) {
            notes.forEach(function (n, i) {
                var o = document.createElement('option');
                o.value = i;
                o.textContent = n.when + ' — “' + (n.text.length > 60 ? n.text.slice(0, 57) + '…' : n.text) + '”';
                pick.appendChild(o);
            });
            choose();
            function again() { clearTimeout(redraw); redraw = setTimeout(function () { readNote(); draw(photoImg); finish(); }, 250); }
            pick.addEventListener('change', function () { choose(); again(); });
            text.addEventListener('input', again);
            ratingBox.addEventListener('change', again);
        }
        readNote();
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
