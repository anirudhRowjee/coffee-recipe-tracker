// Bag photos on the manage page. The browser does the image work, so the
// server needs no imaging library: shrink the photo, pick an accent colour from
// it, and upload both. Written in ES5 like the other scripts.

var BEAN_ART_MAX_SIDE = 1000;

// The most colourful hue in the photo as "#rrggbb", or null for a mostly
// grey/black/white bag (which then keeps the default palette). Pixels nearer
// the centre count for more, so the bag outweighs the table it's standing on.
function pickBeanAccent(img) {
    var size = 64;
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, size, size);
    var pixels = ctx.getImageData(0, 0, size, size).data;

    var buckets = [];
    for (var b = 0; b < 24; b++) buckets.push({ weight: 0, r: 0, g: 0, b: 0 });

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

        var bucket = buckets[Math.floor(hue * 4) % 24];
        bucket.weight += weight;
        bucket.r += red * weight;
        bucket.g += green * weight;
        bucket.b += blue * weight;
    }

    var best = buckets[0];
    buckets.forEach(function (candidate) { if (candidate.weight > best.weight) best = candidate; });
    // low on purpose: pale illustrated bags have little strong colour, but what
    // they have is what makes them theirs
    if (best.weight < size * size * 0.002) return null;

    function hex(channel) { return ('0' + Math.round(channel / best.weight).toString(16)).slice(-2); }
    return '#' + hex(best.r) + hex(best.g) + hex(best.b);
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
        var accent = pickBeanAccent(img);
        shrinkBeanPhoto(img, function (blob) {
            URL.revokeObjectURL(url);
            var form = new FormData();
            form.append('image', blob, 'bag.jpg');
            if (accent) form.append('accent', accent);
            fetch('/beans/' + box.getAttribute('data-bean-id') + '/image', { method: 'POST', body: form })
                .then(function (response) {
                    if (!response.ok) throw new Error('upload failed');
                    location.reload();
                })['catch'](function () { status.textContent = 'Upload failed, please try again'; });
        });
    };
    img.src = url;
}
