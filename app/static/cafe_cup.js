// The café cup form (cafe_form.html). The phone does the image work, as for bag photos
// (static/bean_art.js, whose colour picker this reuses): shrink the photo to a JPEG,
// pick its colours, and send them with the form. Also: cafés you've been to fill in
// the café and area, and a missing rating is caught before sending.
(function () {
    var form = document.getElementById('cafe-form');
    if (!form) return;
    var input = document.getElementById('cafe-photo');
    var preview = document.getElementById('cafe-photo-preview');
    var status = document.getElementById('cafe-photo-status');
    var label = document.getElementById('cafe-photo-text');
    var removeBox = document.getElementById('cafe-remove-photo');
    var MAX_SIDE = 1200;  // sharp on a 1080-wide share card; ~150-250 KB, so SQLite stays small
    var prepared = null;  // {blob, accent, mesh}

    function say(text) { status.textContent = text; status.hidden = !text; }

    input.addEventListener('change', function () {
        var file = input.files[0];
        prepared = null;
        if (!file) return;
        say('Getting the photo ready…');
        var url = URL.createObjectURL(file);
        var img = new Image();
        img.onerror = function () { URL.revokeObjectURL(url); say("Couldn't read that photo. Try another one."); };
        img.onload = function () {
            var colours = window.pickBeanColours ? pickBeanColours(img) : null;
            var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
            var canvas = document.createElement('canvas');
            canvas.width = Math.round(img.naturalWidth * scale);
            canvas.height = Math.round(img.naturalHeight * scale);
            var ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';  // JPEG has no transparency
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(function (blob) {
                URL.revokeObjectURL(url);
                if (!blob) { say("Couldn't read that photo. Try another one."); return; }
                prepared = { blob: blob, accent: colours && colours.accent, mesh: colours && colours.mesh };
                preview.src = URL.createObjectURL(blob);
                preview.hidden = false;
                label.textContent = '📷 Change the photo';
                if (removeBox) removeBox.checked = false;
                say('');
            }, 'image/jpeg', 0.85);
        };
        img.src = url;
    });

    // the @ is already drawn beside the box: don't let a typed one double it
    var handle = form.querySelector('[name="handle"]');
    if (handle) {
        handle.value = handle.value.replace(/^@+/, '');
        handle.addEventListener('input', function () { if (/^@/.test(handle.value)) handle.value = handle.value.replace(/^@+/, ''); });
    }

    // a café you've been to: its name and the area you gave last time
    form.addEventListener('click', function (e) {
        var chip = e.target.closest('[data-cafe]');
        if (!chip) return;
        form.querySelector('[name="cafe"]').value = chip.getAttribute('data-cafe');
        var area = form.querySelector('[name="area"]');
        if (chip.getAttribute('data-area') && !area.value) area.value = chip.getAttribute('data-area');
    });

    // After forms.js has checked the fields (it runs first): the rating, then send it all
    // with the prepared photo in place of the original file
    document.addEventListener('DOMContentLoaded', function () {
        form.addEventListener('submit', function (e) {
            if (e.defaultPrevented) return;
            var ratingError = document.getElementById('cafe-rating-error');
            if (!form.querySelector('[name="rating"]:checked')) {
                e.preventDefault();
                ratingError.hidden = false;
                ratingError.scrollIntoView({ block: 'center', behavior: 'smooth' });
                setTimeout(function () { form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = false; }); }, 10);
                return;
            }
            ratingError.hidden = true;
            if (!window.fetch || !window.FormData) return;  // the plain form still works
            e.preventDefault();
            var data = new FormData(form);
            data['delete']('photo');
            if (prepared) {
                data.append('photo', prepared.blob, 'cup.jpg');
                if (prepared.accent) data.append('accent', prepared.accent);
                if (prepared.mesh) data.append('mesh', prepared.mesh);
            }
            var error = document.getElementById('cafe-save-error');
            error.hidden = true;
            fetch(form.getAttribute('action'), { method: 'POST', body: data, credentials: 'same-origin', headers: { Accept: 'application/json' } })
                .then(function (response) {
                    if (response.ok && response.redirected) { location.href = response.url; return; }
                    if (response.ok) { location.href = response.url; return; }
                    return response.json().then(function (body) {
                        throw new Error(body && body.detail ? (typeof body.detail === 'string' ? body.detail : 'Check the fields above') : 'Something went wrong');
                    }, function () { throw new Error('Something went wrong'); });
                })['catch'](function (err) {
                    error.textContent = "Couldn't save: " + err.message + '. Nothing you typed is lost.';
                    error.hidden = false;
                    form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = false; });
                });
        });
    });
})();
