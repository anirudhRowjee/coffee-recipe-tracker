// The log form (partials/log_brew_form.html): taste chips and Next time chips.
// The real fields (notes, recommended_param/delta) are what's sent; the chips just fill them.
(function () {
    var form = document.getElementById('log-brew-form');
    if (!form || form.getAttribute('data-ready')) return;
    form.setAttribute('data-ready', '1');
    var notes = document.getElementById('log-notes');
    var param = document.getElementById('log-rec-param');
    var delta = document.getElementById('log-rec-delta');
    var chips = form.querySelector('.next-chips');
    var fields = form.querySelector('.next-fields');
    var amountRow = form.querySelector('.next-amount');
    var amountLabel = form.querySelector('.next-amount-label');
    var amountValue = form.querySelector('.next-amount-value');
    var stepsChoice = form.querySelector('.log-steps-choice');
    var save = form.querySelector('.log-save');
    var then = document.getElementById('log-then');
    var UNIT = { dose_g: ' g', water_ml: ' ml', temp_c: ' °C', grind_size: '' };
    var STEP = { dose_g: 0.5, water_ml: 10, temp_c: 1, grind_size: 1 };
    var current = null;  // the picked Next time chip

    // Taste words: tapping adds the word to the notes, tapping again takes it out
    form.querySelectorAll('.taste-chips .chip').forEach(function (chip) {
        chip.addEventListener('click', function () {
            var word = chip.getAttribute('data-word');
            // brew mode puts "Brewed 2:58 · 241 g" on the first line: keep it as it is
            var lines = notes.value.split('\n');
            var head = /^Brewed \d+:\d\d/.test(lines[0]) ? lines.shift() : null;
            var body = lines.join('\n');
            var parts = body.split(/,\s*/).map(function (p) { return p.trim(); }).filter(Boolean);
            var at = parts.map(function (p) { return p.toLowerCase(); }).indexOf(word);
            if (at === -1) parts.push(parts.length ? word : word.charAt(0).toUpperCase() + word.slice(1));
            else parts.splice(at, 1);
            notes.value = (head !== null ? head + '\n' : '') + parts.join(', ');
            chip.setAttribute('aria-pressed', at === -1 ? 'true' : 'false');
            notes.dispatchEvent(new Event('input', { bubbles: true }));
        });
    });

    function fmt(n) { return String(Math.round(n * 100) / 100); }
    function showAmount() {
        var p = current.getAttribute('data-param');
        var v = parseFloat(delta.value);
        amountRow.hidden = !p || p === 'recipe_text';
        if (!amountRow.hidden) {
            amountLabel.textContent = current.textContent + ' by';
            amountValue.textContent = fmt(Math.abs(v)) + UNIT[p];
        }
        var steps = p === 'recipe_text';
        stepsChoice.hidden = !steps;
        save.hidden = steps;
    }
    function pick(chip) {
        current = chip;
        chips.querySelectorAll('.chip').forEach(function (c) { c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'); });
        var p = chip.getAttribute('data-param');
        param.value = p;
        delta.value = chip.getAttribute('data-amount');
        showAmount();
    }

    // With JavaScript the chips replace the select; without it the select is still there
    chips.hidden = false;
    fields.hidden = true;
    chips.querySelectorAll('.chip').forEach(function (chip) {
        chip.addEventListener('click', function () { pick(chip); });
    });
    amountRow.addEventListener('click', function (e) {
        var b = e.target.closest('[data-nudge]');
        if (!b || !current) return;
        var p = current.getAttribute('data-param');
        var sign = parseFloat(current.getAttribute('data-amount')) < 0 ? -1 : 1;
        var size = Math.abs(parseFloat(delta.value) || 0) + parseFloat(b.getAttribute('data-nudge')) * STEP[p];
        size = Math.max(STEP[p], Math.round(size * 100) / 100);
        delta.value = fmt(sign * size);
        showAmount();
    });
    stepsChoice.addEventListener('click', function (e) {
        var b = e.target.closest('[data-then]');
        if (b) then.value = b.getAttribute('data-then');
    });
    pick(chips.querySelector('[data-param=""]'));
})();
