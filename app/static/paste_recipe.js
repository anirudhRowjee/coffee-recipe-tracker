// "Paste a recipe" (partials/paste_recipe.html): the server reads the pasted text
// (/recipes/paste, which saves nothing) and this fills the surrounding form's fields and
// method editor, for the person to check before saving.
(function () {
    function setField(form, name, value) {
        var input = form.querySelector('[name="' + name + '"]');
        if (!input || value === null || value === undefined) return;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function setup(box) {
        var form = box.closest('form');
        if (!form || !window.fetch) return;
        var status = box.nextElementSibling;
        if (!status || !status.classList.contains('paste-status')) return;
        box.hidden = false;
        var prompt = box.querySelector('.paste-prompt');
        var text = box.querySelector('.paste-text');
        function say(message) { status.textContent = message; status.hidden = !message; }

        box.querySelector('[data-copy-prompt]').addEventListener('click', function (e) {
            var button = e.currentTarget;
            function done() { button.textContent = 'Copied ✓'; setTimeout(function () { button.textContent = 'Copy the prompt'; }, 2000); }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(prompt.value).then(done, function () { prompt.select(); });
            } else { prompt.select(); document.execCommand('copy'); done(); }
        });

        box.querySelector('[data-paste-fill]').addEventListener('click', function () {
            if (!text.value.trim()) { say('Paste the answer first.'); text.focus(); return; }
            say('Reading it…');
            var data = new FormData();
            data.append('text', text.value);
            fetch('/recipes/paste', { method: 'POST', body: data, credentials: 'same-origin', headers: { Accept: 'application/json' } })
                .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
                .then(function (found) {
                    setField(form, 'dose_g', found.dose_g);
                    setField(form, 'water_ml', found.water_ml);
                    setField(form, 'temp_c', found.temp_c);
                    setField(form, 'grind_size', found.grind_size);
                    var slot = form.querySelector('[data-method-field]');
                    if (slot && found.method_html && found.missing.indexOf('Method') === -1) {
                        slot.innerHTML = found.method_html;
                        if (window.initStepEditors) window.initStepEditors(slot);
                    }
                    var message = found.missing.length === 5 ? "Couldn't find a recipe in that. Check it has lines like \"Coffee: 15 g\" and timed steps."
                        : 'Filled in. Check everything below before saving.';
                    if (found.missing.length && found.missing.length < 5) message += ' Not found: ' + found.missing.join(', ') + '.';
                    if (found.guesses) message += ' ' + found.guesses + (found.guesses === 1 ? ' step is a guess' : ' steps are guesses') + ', marked in the method.';
                    say(message);
                    if (found.missing.length < 5) { box.open = false; status.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
                })['catch'](function () { say("Couldn't read it just now. Nothing below has changed."); });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var boxes = document.querySelectorAll('[data-paste-recipe]');
        for (var i = 0; i < boxes.length; i++) setup(boxes[i]);
    });
})();
