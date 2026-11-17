// Labels for frozen portions as an A4 PDF, made in the browser (portion_labels.html): ten
// labels to a sheet (2 × 5, 99 × 57 mm) with dashed lines to cut along, for a vinyl sticker
// sheet from any print shop. Each label: the QR code (static/qr.js) for its /b/<code> page,
// the code, the coffee, its dates, the weight and the best recipe's numbers. Written by
// hand rather than with a PDF library: Helvetica and Courier are built into every PDF
// reader, and the QR code is plain rectangles. LabelsPDF.build(labels, shortUrl) returns
// the file as a string of bytes (also run under node by tests/test_portions.py).
(function (root) {
    var MM = 72 / 25.4, W = 595.28, H = 841.89;
    var COLS = 2, ROWS = 5, LW = 99 * MM, LH = 57 * MM;
    var X0 = (W - COLS * LW) / 2, Y0 = (H - ROWS * LH) / 2;

    // WinAnsi (the PDF's standard Latin encoding) for the few non-ASCII characters we use
    var WIN = { '·': 0xB7, '°': 0xB0, '—': 0x97, '–': 0x96, '×': 0xD7, '’': 0x92, '‘': 0x91, '“': 0x93, '”': 0x94, '…': 0x85, '€': 0x80 };
    function pdfString(text) {
        var out = '';
        for (var i = 0; i < text.length; i++) {
            var ch = text.charAt(i), code = text.charCodeAt(i);
            if (ch === '\\' || ch === '(' || ch === ')') out += '\\' + ch;
            else if (code >= 32 && code < 127) out += ch;
            else {
                var b = WIN[ch] !== undefined ? WIN[ch] : (code >= 160 && code <= 255 ? code : 63);
                out += '\\' + ('00' + b.toString(8)).slice(-3);
            }
        }
        return '(' + out + ')';
    }
    // rough Helvetica widths (per 1 pt of font size), enough to wrap and trim lines
    function width(text, size, bold) {
        var w = 0;
        for (var i = 0; i < text.length; i++) {
            var ch = text.charAt(i);
            if (/[il.,:;'|!·]/.test(ch)) w += 0.28;
            else if (/[ftjrI\- ()]/.test(ch)) w += 0.33;
            else if (/[mwMW]/.test(ch)) w += 0.85;
            else if (/[A-Z]/.test(ch)) w += 0.68;
            else if (/[0-9]/.test(ch)) w += 0.556;
            else w += 0.54;
        }
        return w * size * (bold ? 1.07 : 1);
    }
    function wrap(text, size, bold, maxW, maxLines) {
        var words = String(text || '').split(/\s+/).filter(Boolean), lines = [], line = '';
        words.forEach(function (word) {
            var next = line ? line + ' ' + word : word;
            if (width(next, size, bold) <= maxW || !line) line = next;
            else { lines.push(line); line = word; }
        });
        if (line) lines.push(line);
        if (lines.length > maxLines) {
            lines = lines.slice(0, maxLines);
            var last = lines[maxLines - 1];
            while (last && width(last + '…', size, bold) > maxW) last = last.slice(0, -1);
            lines[maxLines - 1] = last.replace(/\s+$/, '') + '…';
        }
        return lines.map(function (l) {  // a single word longer than the line is cut
            while (width(l, size, bold) > maxW && l.length > 1) l = l.slice(0, -2) + '…';
            return l;
        });
    }
    function num(n) { return (Math.round(n * 100) / 100).toString(); }

    function label(l, x, y, shortUrl, ops) {
        // y is the label's top edge in PDF space (origin bottom-left)
        var pad = 4 * MM, qrSide = 33 * MM;
        var QR = root.QR || require('./qr.js');
        var modules = QR.matrix(l.url), n = modules.length, cell = qrSide / (n + 4);
        var qx = x + pad, qy = y - pad - qrSide;
        ops.push('0 g');
        for (var r = 0; r < n; r++) {
            for (var c = 0; c < n; c++) {
                if (!modules[r][c]) continue;
                var run = 1;
                while (c + run < n && modules[r][c + run]) run++;
                ops.push(num(qx + (c + 2) * cell) + ' ' + num(qy + qrSide - (r + 3) * cell) + ' ' + num(run * cell + 0.05) + ' ' + num(cell + 0.05) + ' re');
                c += run - 1;
            }
        }
        ops.push('f');
        function text(str, tx, ty, font, size, grey) {
            ops.push('BT /' + font + ' ' + size + ' Tf ' + (grey ? '0.42 g' : '0 g') + ' ' + num(tx) + ' ' + num(ty) + ' Td ' + pdfString(str) + ' Tj ET');
        }
        // the code under the QR code, centred
        var codeSize = 15, codeW = l.code.length * 0.6 * codeSize;
        text(l.code, qx + (qrSide - codeW) / 2, qy - 5 * MM, 'F3', codeSize);

        var tx = qx + qrSide + 3 * MM, tw = x + LW - pad - tx, ty = y - pad - 11;
        wrap(l.name, 13, true, tw, 2).forEach(function (line) { text(line, tx, ty, 'F2', 13); ty -= 14; });
        var about = [l.about, l.flavour].filter(Boolean).join(' · ');
        if (about) { wrap(about, 7.5, false, tw, 2).forEach(function (line) { text(line, tx, ty, 'F1', 7.5, true); ty -= 9; }); }
        ty -= 3;
        var dates = [l.roasted_short ? 'Roasted ' + l.roasted_short : '', l.frozen_short ? 'Frozen ' + l.frozen_short : ''].filter(Boolean).join(' · ');
        if (dates) { text(dates, tx, ty, 'F1', 9); ty -= 13; }
        text(l.grams + ' g' + (l.cups ? ' · about ' + l.cups + ' cup' + (l.cups === 1 ? '' : 's') : ''), tx, ty, 'F2', 11); ty -= 13;
        if (l.recipe_short) {
            wrap('Best: ' + l.recipe_short, 7.5, false, tw, 2).forEach(function (line) { text(line, tx, ty, 'F1', 7.5); ty -= 9; });
        }
        text(shortUrl, tx, y - LH + pad + 2, 'F1', 7, true);
        text('Scan or type the code', tx, y - LH + pad + 10, 'F1', 7, true);
    }

    function cutLines(ops) {
        ops.push('0.75 G 0.4 w [3 3] 0 d');
        for (var c = 0; c <= COLS; c++) ops.push(num(X0 + c * LW) + ' ' + num(Y0) + ' m ' + num(X0 + c * LW) + ' ' + num(Y0 + ROWS * LH) + ' l S');
        for (var r = 0; r <= ROWS; r++) ops.push(num(X0) + ' ' + num(Y0 + r * LH) + ' m ' + num(X0 + COLS * LW) + ' ' + num(Y0 + r * LH) + ' l S');
        ops.push('[] 0 d');
    }

    function build(labels, shortUrl) {
        var perPage = COLS * ROWS, pages = [];
        for (var i = 0; i < labels.length; i += perPage) pages.push(labels.slice(i, i + perPage));
        if (!pages.length) pages.push([]);
        var objects = [];  // index 0 is object 1
        function add(body) { objects.push(body); return objects.length; }
        var catalog = add(null), pagesObj = add(null);
        var fonts = [add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'),
                     add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'),
                     add('<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>')];
        var kids = [];
        pages.forEach(function (page) {
            var ops = [];
            cutLines(ops);
            page.forEach(function (l, k) {
                var col = k % COLS, row = Math.floor(k / COLS);
                label(l, X0 + col * LW, H - Y0 - row * LH, shortUrl, ops);
            });
            var stream = ops.join('\n');
            var content = add('<< /Length ' + stream.length + ' >>\nstream\n' + stream + '\nendstream');
            kids.push(add('<< /Type /Page /Parent ' + pagesObj + ' 0 R /MediaBox [0 0 ' + W + ' ' + H + '] ' +
                '/Resources << /Font << /F1 ' + fonts[0] + ' 0 R /F2 ' + fonts[1] + ' 0 R /F3 ' + fonts[2] + ' 0 R >> >> /Contents ' + content + ' 0 R >>'));
        });
        objects[catalog - 1] = '<< /Type /Catalog /Pages ' + pagesObj + ' 0 R >>';
        objects[pagesObj - 1] = '<< /Type /Pages /Kids [' + kids.map(function (k) { return k + ' 0 R'; }).join(' ') + '] /Count ' + kids.length + ' >>';
        var out = '%PDF-1.4\n%âãÏÓ\n', offsets = [];
        objects.forEach(function (body, idx) {
            offsets.push(out.length);
            out += (idx + 1) + ' 0 obj\n' + body + '\nendobj\n';
        });
        var xref = out.length;
        out += 'xref\n0 ' + (objects.length + 1) + '\n0000000000 65535 f \n';
        offsets.forEach(function (o) { out += ('0000000000' + o).slice(-10) + ' 00000 n \n'; });
        out += 'trailer\n<< /Size ' + (objects.length + 1) + ' /Root ' + catalog + ' 0 R >>\nstartxref\n' + xref + '\n%%EOF\n';
        return out;
    }

    function toBlob(pdf) {
        var bytes = new Uint8Array(pdf.length);
        for (var i = 0; i < pdf.length; i++) bytes[i] = pdf.charCodeAt(i) & 0xFF;
        return new Blob([bytes], { type: 'application/pdf' });
    }

    root.LabelsPDF = { build: build };
    if (typeof module !== 'undefined' && module.exports) { module.exports = root.LabelsPDF; return; }

    document.addEventListener('DOMContentLoaded', function () {
        var button = document.getElementById('labels-pdf');
        if (!button) return;
        var note = document.getElementById('labels-pdf-note');
        button.addEventListener('click', function () {
            var labels = JSON.parse(button.getAttribute('data-labels'));
            var name = button.getAttribute('data-filename') || 'labels.pdf';
            var blob = toBlob(build(labels, button.getAttribute('data-short-url') || ''));
            var file = window.File ? new File([blob], name, { type: 'application/pdf' }) : null;
            var touch = 'ontouchstart' in window;
            if (touch && file && navigator.canShare && navigator.canShare({ files: [file] })) {
                navigator.share({ files: [file], title: name })['catch'](function () { /* closed the share sheet */ });
            } else {
                var url = URL.createObjectURL(blob), a = document.createElement('a');
                a.href = url; a.download = name;
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
            }
            note.textContent = 'Print at 100% ("actual size"), not "fit to page", so the labels keep their size.';
            note.hidden = false;
        });
    });
})(typeof window !== 'undefined' ? window : this);
