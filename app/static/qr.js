// A small QR code encoder for the portion labels (static/labels_pdf.js): byte mode, error
// correction level M, versions 1-10 (up to 213 bytes, far more than a /b/<code> address).
// Follows the QR specification (ISO/IEC 18004) the way Project Nayuki's reference
// generator lays it out. Plain ES5 that also runs under node, for tests/test_portions.py.
//
// QR.matrix(text) returns the modules as rows of booleans (true = dark), no quiet zone.
(function (root) {
    // level M, indexed by version (index 0 unused)
    var ECC_PER_BLOCK = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
    var NUM_BLOCKS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
    var FORMAT_M = 0;  // the two format bits for level M

    function rawModules(ver) {
        var r = (16 * ver + 128) * ver + 64;
        if (ver >= 2) {
            var na = Math.floor(ver / 7) + 2;
            r -= (25 * na - 10) * na - 55;
            if (ver >= 7) r -= 36;
        }
        return r;
    }
    function dataCodewords(ver) { return Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver]; }

    function gfMul(x, y) {
        var z = 0;
        for (var i = 7; i >= 0; i--) {
            z = (z << 1) ^ ((z >>> 7) * 0x11D);
            z ^= ((y >>> i) & 1) * x;
        }
        return z & 0xFF;
    }
    function rsDivisor(degree) {
        var result = [];
        for (var i = 0; i < degree - 1; i++) result.push(0);
        result.push(1);
        var rootV = 1;
        for (i = 0; i < degree; i++) {
            for (var j = 0; j < result.length; j++) {
                result[j] = gfMul(result[j], rootV);
                if (j + 1 < result.length) result[j] ^= result[j + 1];
            }
            rootV = gfMul(rootV, 0x02);
        }
        return result;
    }
    function rsRemainder(data, divisor) {
        var result = divisor.map(function () { return 0; });
        data.forEach(function (b) {
            var factor = b ^ result.shift();
            result.push(0);
            divisor.forEach(function (coef, i) { result[i] ^= gfMul(coef, factor); });
        });
        return result;
    }

    function utf8(text) {
        var out = [], s = unescape(encodeURIComponent(text));
        for (var i = 0; i < s.length; i++) out.push(s.charCodeAt(i));
        return out;
    }

    function matrix(text) {
        var bytes = utf8(text), ver;
        for (ver = 1; ver <= 10; ver++) {
            var countBits = ver <= 9 ? 8 : 16;
            if (4 + countBits + 8 * bytes.length <= dataCodewords(ver) * 8) break;
        }
        if (ver > 10) throw new Error('Too long for a label QR code');
        var countLen = ver <= 9 ? 8 : 16;

        // the data bits, padded
        var bits = [];
        function put(value, len) { for (var i = len - 1; i >= 0; i--) bits.push((value >>> i) & 1); }
        put(4, 4);
        put(bytes.length, countLen);
        bytes.forEach(function (b) { put(b, 8); });
        var capacity = dataCodewords(ver) * 8;
        put(0, Math.min(4, capacity - bits.length));
        put(0, (8 - bits.length % 8) % 8);
        for (var pad = 0xEC; bits.length < capacity; pad ^= 0xEC ^ 0x11) put(pad, 8);
        var data = [];
        for (var i = 0; i < bits.length; i += 8) {
            var byte = 0;
            for (var k = 0; k < 8; k++) byte = (byte << 1) | bits[i + k];
            data.push(byte);
        }

        // error correction, interleaved
        var numBlocks = NUM_BLOCKS[ver], eccLen = ECC_PER_BLOCK[ver];
        var rawCodewords = Math.floor(rawModules(ver) / 8);
        var numShort = numBlocks - rawCodewords % numBlocks;
        var shortLen = Math.floor(rawCodewords / numBlocks);
        var divisor = rsDivisor(eccLen), blocks = [], at = 0;
        for (i = 0; i < numBlocks; i++) {
            var dat = data.slice(at, at + shortLen - eccLen + (i < numShort ? 0 : 1));
            at += dat.length;
            var ecc = rsRemainder(dat, divisor);
            if (i < numShort) dat.push(0);
            blocks.push(dat.concat(ecc));
        }
        var codewords = [];
        for (i = 0; i < blocks[0].length; i++) {
            for (var j = 0; j < blocks.length; j++) {
                if (i !== shortLen - eccLen || j >= numShort) codewords.push(blocks[j][i]);
            }
        }

        // the grid
        var size = ver * 4 + 17, modules = [], isFunc = [];
        for (i = 0; i < size; i++) {
            modules.push([]); isFunc.push([]);
            for (j = 0; j < size; j++) { modules[i].push(false); isFunc[i].push(false); }
        }
        function setFunc(x, y, dark) { modules[y][x] = dark; isFunc[y][x] = true; }
        for (i = 0; i < size; i++) { setFunc(6, i, i % 2 === 0); setFunc(i, 6, i % 2 === 0); }
        function finder(x, y) {
            for (var dy = -4; dy <= 4; dy++) for (var dx = -4; dx <= 4; dx++) {
                var d = Math.max(Math.abs(dx), Math.abs(dy)), xx = x + dx, yy = y + dy;
                if (xx >= 0 && xx < size && yy >= 0 && yy < size) setFunc(xx, yy, d !== 2 && d !== 4);
            }
        }
        finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
        if (ver > 1) {
            var na = Math.floor(ver / 7) + 2;
            var step = Math.ceil((ver * 4 + 4) / (na * 2 - 2)) * 2;
            var pos = [6];
            for (var p = size - 7; pos.length < na; p -= step) pos.splice(1, 0, p);
            for (i = 0; i < na; i++) for (j = 0; j < na; j++) {
                if ((i === 0 && j === 0) || (i === 0 && j === na - 1) || (i === na - 1 && j === 0)) continue;
                for (var ay = -2; ay <= 2; ay++) for (var ax = -2; ax <= 2; ax++) {
                    setFunc(pos[i] + ax, pos[j] + ay, Math.max(Math.abs(ax), Math.abs(ay)) !== 1);
                }
            }
        }
        function bit(x, n) { return ((x >>> n) & 1) !== 0; }
        function formatBits(mask) {
            var d = (FORMAT_M << 3) | mask, rem = d;
            for (var n = 0; n < 10; n++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
            var b = ((d << 10) | rem) ^ 0x5412;
            for (n = 0; n <= 5; n++) setFunc(8, n, bit(b, n));
            setFunc(8, 7, bit(b, 6)); setFunc(8, 8, bit(b, 7)); setFunc(7, 8, bit(b, 8));
            for (n = 9; n < 15; n++) setFunc(14 - n, 8, bit(b, n));
            for (n = 0; n < 8; n++) setFunc(size - 1 - n, 8, bit(b, n));
            for (n = 8; n < 15; n++) setFunc(8, size - 15 + n, bit(b, n));
            setFunc(8, size - 8, true);
        }
        formatBits(0);  // reserve the format areas before placing data
        if (ver >= 7) {
            var rem = ver;
            for (i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
            var vb = (ver << 12) | rem;
            for (i = 0; i < 18; i++) {
                var a = size - 11 + i % 3, b2 = Math.floor(i / 3);
                setFunc(a, b2, bit(vb, i)); setFunc(b2, a, bit(vb, i));
            }
        }
        // data, in the zig-zag
        var n2 = 0;
        for (var right = size - 1; right >= 1; right -= 2) {
            if (right === 6) right = 5;
            for (var vert = 0; vert < size; vert++) {
                for (j = 0; j < 2; j++) {
                    var x = right - j, upward = ((right + 1) & 2) === 0, y = upward ? size - 1 - vert : vert;
                    if (!isFunc[y][x] && n2 < codewords.length * 8) {
                        modules[y][x] = bit(codewords[n2 >>> 3], 7 - (n2 & 7));
                        n2++;
                    }
                }
            }
        }

        function applyMask(mask) {
            for (var yy = 0; yy < size; yy++) for (var xx = 0; xx < size; xx++) {
                var inv;
                switch (mask) {
                    case 0: inv = (xx + yy) % 2 === 0; break;
                    case 1: inv = yy % 2 === 0; break;
                    case 2: inv = xx % 3 === 0; break;
                    case 3: inv = (xx + yy) % 3 === 0; break;
                    case 4: inv = (Math.floor(xx / 3) + Math.floor(yy / 2)) % 2 === 0; break;
                    case 5: inv = xx * yy % 2 + xx * yy % 3 === 0; break;
                    case 6: inv = (xx * yy % 2 + xx * yy % 3) % 2 === 0; break;
                    default: inv = ((xx + yy) % 2 + xx * yy % 3) % 2 === 0;
                }
                if (!isFunc[yy][xx] && inv) modules[yy][xx] = !modules[yy][xx];
            }
        }
        function penalty() {
            var score = 0, dark = 0, line, run, c, yy, xx;
            function runs(get) {
                for (var r = 0; r < size; r++) {
                    run = 1;
                    for (c = 1; c < size; c++) {
                        if (get(r, c) === get(r, c - 1)) { run++; if (run === 5) score += 3; else if (run > 5) score++; }
                        else run = 1;
                    }
                    line = '';
                    for (c = 0; c < size; c++) line += get(r, c) ? '1' : '0';
                    line = '0000' + line + '0000';
                    for (var at2 = line.indexOf('1011101'); at2 !== -1; at2 = line.indexOf('1011101', at2 + 1)) {
                        if (line.substr(at2 - 4, 4) === '0000' || line.substr(at2 + 7, 4) === '0000') score += 40;
                    }
                }
            }
            runs(function (r, c2) { return modules[r][c2]; });
            runs(function (r, c2) { return modules[c2][r]; });
            for (yy = 0; yy < size - 1; yy++) for (xx = 0; xx < size - 1; xx++) {
                var m = modules[yy][xx];
                if (m === modules[yy][xx + 1] && m === modules[yy + 1][xx] && m === modules[yy + 1][xx + 1]) score += 3;
            }
            for (yy = 0; yy < size; yy++) for (xx = 0; xx < size; xx++) if (modules[yy][xx]) dark++;
            var total = size * size;
            score += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
            return score;
        }
        var best = 0, bestScore = Infinity;
        for (var mask = 0; mask < 8; mask++) {
            applyMask(mask); formatBits(mask);
            var s = penalty();
            if (s < bestScore) { best = mask; bestScore = s; }
            applyMask(mask);
        }
        applyMask(best); formatBits(best);
        return modules;
    }

    root.QR = { matrix: matrix };
    if (typeof module !== 'undefined' && module.exports) module.exports = root.QR;
})(typeof window !== 'undefined' ? window : this);
