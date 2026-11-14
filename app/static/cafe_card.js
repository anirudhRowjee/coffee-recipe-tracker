// Share a café cup as an image (cafe_share.html): 1080×1350 (an Instagram post) or
// 1080×1920 (a story), drawn here on a canvas because the server has no imaging library.
// The photo across the top, the words on a plain card below it (never on the photo or the
// colours, so they stay readable), the photo's colours around the edge. What goes on it is
// chosen on the page and never leaves the browser.
(function () {
    var host = document.getElementById('share-card');
    if (!host) return;
    var card = JSON.parse(host.getAttribute('data-card'));
    var options = document.getElementById('cafe-share-options');
    var noteBox = document.getElementById('cafe-share-note');
    var handleBox = document.getElementById('cafe-share-handle');
    handleBox.value = card.handle || '';

    var SERIF = "Georgia, 'Palatino Linotype', Palatino, serif";
    var SANS = "-apple-system, system-ui, 'Segoe UI', Helvetica, Arial, sans-serif";
    var INK = '#2c1810', MUTED = '#7a5a44', VALUE = '#3b1f0e', PAPER = '#faf6f0', LINE = '#e3d5c3', NOTE_BG = '#f3ebdf';
    var GOLD = '#d4a24c', GOLD_OFF = '#e6d3b3';
    var BORDER = 32, PAD = 60;

    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    function font(weight, size, family) { ctx.font = weight + ' ' + size + 'px ' + family; }

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
    // wrapped lines, shrinking the font until they fit in maxLines (an ellipsis if they never do)
    function fitLines(text, maxW, maxLines, weight, size, minSize, family) {
        var lines;
        for (; size >= minSize; size -= 2) {
            font(weight, size, family);
            lines = wrap(text, maxW);
            if (lines.length <= maxLines) return { lines: lines, size: size };
        }
        size += 2;
        font(weight, size, family);
        lines = lines.slice(0, Math.max(1, maxLines));
        var last = lines[lines.length - 1];
        while (last.length > 1 && ctx.measureText(last + '…').width > maxW) last = last.slice(0, -1);
        lines[lines.length - 1] = last + '…';
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
    function background(W, H) {
        var mesh = card.colors.mesh;
        if (mesh && mesh.length === 4) {
            var tiny = document.createElement('canvas');
            tiny.width = 2; tiny.height = 2;
            var t = tiny.getContext('2d');
            [[0, 0], [1, 0], [0, 1], [1, 1]].forEach(function (p, i) { t.fillStyle = mesh[i]; t.fillRect(p[0], p[1], 1, 1); });
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            ctx.drawImage(tiny, 0.5, 0.5, 1, 1, 0, 0, W, H);
        } else {
            var g = ctx.createLinearGradient(0, 0, W, H);
            g.addColorStop(0, card.colors.accent);
            g.addColorStop(1, '#2c1810');
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, W, H);
        }
    }

    function chosen() {
        var on = {};
        options.querySelectorAll('[data-show]').forEach(function (box) { on[box.getAttribute('data-show')] = box.checked; });
        var size = options.querySelector('[name="size"]:checked');
        on.story = size && size.value === 'story';
        return on;
    }

    function draw(photo) {
        var on = chosen();
        var W = 1080, H = on.story ? 1920 : 1350;
        canvas.width = W;
        canvas.height = H;
        background(W, H);
        ctx.fillStyle = PAPER;
        roundRect(BORDER, BORDER, W - 2 * BORDER, H - 2 * BORDER, 36);
        ctx.fill();

        var X = BORDER + PAD, CW = W - 2 * (BORDER + PAD), y = BORDER;
        ctx.textBaseline = 'alphabetic';

        // the photo across the top of the card, cropped to fill
        if (photo) {
            var ph = on.story ? 1080 : 700, pw = W - 2 * BORDER;
            var scale = Math.max(pw / photo.width, ph / photo.height);
            var sw = pw / scale, sh = ph / scale;
            ctx.save();
            roundRect(BORDER, BORDER, pw, ph + 36, 36);  // rounded at the top; the bottom edge is cut straight below
            ctx.clip();
            ctx.beginPath();
            ctx.rect(BORDER, BORDER, pw, ph);
            ctx.clip();
            ctx.drawImage(photo, (photo.width - sw) / 2, (photo.height - sh) / 2, sw, sh, BORDER, BORDER, pw, ph);
            ctx.restore();
            y = BORDER + ph;
        }
        y += PAD - 6;

        var footerY = H - BORDER - PAD + 6;
        var roomy = !photo;

        var name = fitLines(card.cafe, CW, 2, 'normal', roomy ? 96 : 72, 48, SERIF);
        ctx.fillStyle = INK;
        name.lines.forEach(function (line) { y += name.size * 1.08; ctx.fillText(line, X, y); });

        var where = [card.area, on.date ? card.date : ''].filter(Boolean).join(' · ');
        if (where) {
            font('normal', roomy ? 34 : 30, SANS);
            ctx.fillStyle = MUTED;
            y += roomy ? 52 : 44;
            ctx.fillText(where, X, y);
        }

        if (on.rating) {
            font('normal', roomy ? 64 : 52, SANS);
            y += roomy ? 84 : 66;
            var sx = X;
            for (var i = 1; i <= 5; i++) {
                ctx.fillStyle = i <= card.rating ? GOLD : GOLD_OFF;
                ctx.fillText('★', sx, y);
                sx += ctx.measureText('★').width + 6;
            }
        }

        var drinkLine = [card.drink, on.beans ? card.beans : '', on.price ? card.price : ''].filter(Boolean).join(' · ');
        if (drinkLine) {
            var drink = fitLines(drinkLine, CW, 2, 'bold', roomy ? 40 : 34, 26, SANS);
            ctx.fillStyle = VALUE;
            y += 18;
            drink.lines.forEach(function (line) { y += drink.size * 1.3; ctx.fillText(line, X, y); });
        }

        var note = on.notes && noteBox ? noteBox.value.trim() : '';
        if (note) {
            y += 30;
            var room = footerY - 70 - y;
            var lineH = 1.4;
            var maxLines = Math.max(1, Math.floor((room - 40) / (36 * lineH)));
            var fitted = fitLines('“' + note + '”', CW - 56, Math.min(maxLines, on.story ? 8 : 6), 'italic', roomy ? 44 : 38, 26, SERIF);
            var boxH = fitted.lines.length * fitted.size * lineH + 36;
            if (y + boxH < footerY - 30) {
                ctx.fillStyle = NOTE_BG;
                roundRect(X, y, CW, boxH, 18);
                ctx.fill();
                ctx.fillStyle = card.colors.accent;
                ctx.fillRect(X, y + 14, 6, boxH - 28);
                ctx.fillStyle = INK;
                var ny = y + 18;
                fitted.lines.forEach(function (line) { ny += fitted.size * lineH; ctx.fillText(line, X + 30, ny - fitted.size * 0.32); });
            }
        }

        // footer: the handle, and where it was made
        ctx.fillStyle = LINE;
        ctx.fillRect(X, footerY - 50, CW, 2);
        var handle = (handleBox.value || '').trim().replace(/^@+/, '');
        font('bold', 30, SANS);
        ctx.fillStyle = INK;
        if (handle) ctx.fillText('@' + handle, X, footerY);
        font('normal', 24, SANS);
        ctx.fillStyle = MUTED;
        var made = 'Coffee Recipe Tracker';
        ctx.fillText(made, X + CW - ctx.measureText(made).width, footerY);
    }

    var file = null, lastUrl = null, photoImg = null, pending = null;
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
                    navigator.share({ files: [file], title: card.cafe })['catch'](function () { /* closed the sheet */ });
                });
            }
        }, 'image/png');
    }
    function redraw() {
        clearTimeout(pending);
        pending = setTimeout(function () { draw(photoImg); finish(); }, 200);
    }
    options.addEventListener('change', redraw);
    options.addEventListener('input', redraw);

    function start(photo) { photoImg = photo; draw(photo); finish(); }
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
