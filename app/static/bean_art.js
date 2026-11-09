// Bag photos on the manage page. The browser does the image work, so the
// server needs no imaging library: shrink the photo, pick colours from it, and
// upload them together. Written in ES5 like the other scripts.

var BEAN_ART_MAX_SIDE = 1000;

// How much of each of 24 hue bands the photo has. Grey, black and white pixels
// don't count, and pixels nearer the centre count for more, so the bag outweighs
// the table it's standing on. Null for a mostly colourless bag, which then keeps
// the default palette.
function beanHueBands(img) {
    var size = 64;
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, size, size);
    var pixels = ctx.getImageData(0, 0, size, size).data;

    var bands = [];
    for (var b = 0; b < 24; b++) bands.push({ index: b, weight: 0, r: 0, g: 0, b: 0 });

    for (var i = 0; i < pixels.length; i += 4) {
        var red = pixels[i], green = pixels[i + 1], blue = pixels[i + 2];
        var max = Math.max(red, green, blue), min = Math.min(red, green, blue);
        var chroma = max - min;
        var saturation = max === 0 ? 0 : chroma / max;
        var value = max / 255;
        if (pixels[i + 3] < 128 || saturation < 0.3 || value < 0.25 || chroma === 0) continue;

        var hue;
        if (max === red) hue = ((green - blue) / chroma + 6) % 6;
        else if (max === green) hue = (blue - red) / chroma + 2;
        else hue = (red - green) / chroma + 4;

        var x = (i / 4) % size, y = Math.floor(i / 4 / size);
        var dx = (x - size / 2) / (size / 2), dy = (y - size / 2) / (size / 2);
        var centre = Math.max(0.2, 1 - (dx * dx + dy * dy) / 2);
        var weight = saturation * saturation * centre;

        var band = bands[Math.floor(hue * 4) % 24];
        band.weight += weight;
        band.r += red * weight;
        band.g += green * weight;
        band.b += blue * weight;
    }

    bands.sort(function (a, b) { return b.weight - a.weight; });
    // low on purpose: pale illustrated bags have little strong colour, but what
    // they have is what makes them theirs
    return bands[0].weight < size * size * 0.002 ? null : bands;
}

function beanBandColour(band) {
    return [band.r / band.weight, band.g / band.weight, band.b / band.weight];
}

function beanHex(rgb) {
    return '#' + rgb.map(function (channel) {
        return ('0' + Math.max(0, Math.min(255, Math.round(channel))).toString(16)).slice(-2);
    }).join('');
}

function beanMix(rgb, target, amount) {
    return rgb.map(function (channel) { return channel + (target - channel) * amount; });
}

function beanRotateHue(rgb, degrees) {
    var c = Math.cos(degrees * Math.PI / 180), s = Math.sin(degrees * Math.PI / 180);
    var r = rgb[0], g = rgb[1], b = rgb[2];
    return [
        r * (0.213 + 0.787 * c - 0.213 * s) + g * (0.715 - 0.715 * c - 0.715 * s) + b * (0.072 - 0.072 * c + 0.928 * s),
        r * (0.213 - 0.213 * c + 0.143 * s) + g * (0.715 + 0.285 * c + 0.140 * s) + b * (0.072 - 0.072 * c - 0.283 * s),
        r * (0.213 - 0.213 * c - 0.787 * s) + g * (0.715 - 0.715 * c + 0.715 * s) + b * (0.072 + 0.928 * c + 0.072 * s)
    ];
}

// The photo's main colours: { accent: "#rrggbb", mesh: "#a,#b,#c,#d" }, or null.
// The mesh uses the distinct hues actually in the photo, strongest on the
// diagonal; a bag with fewer than four is filled out with shades of its main
// colour, so a one-colour bag stays one colour.
function pickBeanColours(img) {
    var bands = beanHueBands(img);
    if (!bands) return null;

    var chosen = [];
    bands.forEach(function (band) {
        if (chosen.length === 4 || band.weight < bands[0].weight * 0.06) return;
        var separate = chosen.every(function (other) {
            var gap = Math.abs(other.index - band.index);
            return Math.min(gap, 24 - gap) > 1;
        });
        if (separate) chosen.push(band);
    });

    var colours = chosen.map(beanBandColour);
    var base = colours[0];
    var shades = [beanMix(base, 0, 0.35), beanMix(base, 255, 0.35), beanRotateHue(base, 16)];
    for (var i = 0; colours.length < 4; i++) colours.push(shades[i]);

    var corners = [colours[0], colours[2], colours[3], colours[1]];
    return { accent: beanHex(colours[0]), mesh: corners.map(beanHex).join(',') };
}

function shrinkBeanPhoto(img, done) {
    var scale = Math.min(1, BEAN_ART_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    var canvas = document.createElement('canvas');
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    var ctx = canvas.getContext('2d');
    // JPEG has no transparency: without this, a cut-out product shot turns black
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(done, 'image/jpeg', 0.85);
}

function uploadBeanImage(input) {
    var file = input.files[0];
    if (!file) return;
    var box = input.closest('.bean-art');
    var status = box.querySelector('.bean-art-status');
    status.textContent = 'Uploading…';

    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onerror = function () {
        URL.revokeObjectURL(url);
        status.textContent = "Couldn't read that image";
    };
    img.onload = function () {
        var colours = pickBeanColours(img);
        shrinkBeanPhoto(img, function (blob) {
            URL.revokeObjectURL(url);
            var form = new FormData();
            form.append('image', blob, 'bag.jpg');
            if (colours) {
                form.append('accent', colours.accent);
                form.append('mesh', colours.mesh);
            }
            fetch('/beans/' + box.getAttribute('data-bean-id') + '/image', { method: 'POST', body: form })
                .then(function (response) {
                    if (!response.ok) throw new Error('upload failed');
                    location.reload();
                })['catch'](function () { status.textContent = 'Upload failed, please try again'; });
        });
    };
    img.src = url;
}

// "Edit colours" → back to what the photo itself suggests.
function resetBeanColours(button) {
    var box = button.closest('.bean-art');
    var status = box.querySelector('.bean-art-status');
    var img = new Image();
    img.onerror = function () { status.textContent = "Couldn't read the photo"; };
    img.onload = function () {
        var colours = pickBeanColours(img);
        var form = new FormData();
        if (colours) {
            form.append('accent', colours.accent);
            colours.mesh.split(',').forEach(function (colour, i) { form.append('mesh' + (i + 1), colour); });
        }
        fetch('/beans/' + box.getAttribute('data-bean-id') + '/colors', { method: 'POST', body: form })
            .then(function (response) {
                if (!response.ok) throw new Error('save failed');
                location.reload();
            })['catch'](function () { status.textContent = 'Reset failed, please try again'; });
    };
    img.src = box.querySelector('.bean-art-preview').src;
}
