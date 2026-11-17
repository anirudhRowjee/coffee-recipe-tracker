// Freeze in portions (the bag's sheet on a coffee's page): portion size as chips (the last
// one used is remembered on this device), how many with − / +, and a bar showing what's
// frozen and what stays out. The server checks it all again (crud.freeze_portions).
(function () {
    var KEY = 'portion-g';
    function setup(form) {
        var left = parseFloat(form.getAttribute('data-left')) || 0;
        var dose = parseFloat(form.getAttribute('data-dose')) || 0;
        var grams = form.querySelector('[name="grams"]');
        var count = form.querySelector('[name="count"]');
        var other = form.querySelector('.freeze-other');
        var bar = form.querySelector('.freeze-bar');
        var sum = form.querySelector('.freeze-sum');
        var go = form.querySelector('.freeze-go');
        var chips = form.querySelectorAll('.freeze-sizes .chip');

        function pick(value) {
            var preset = ['30', '60', '90'].indexOf(String(value)) !== -1;
            for (var i = 0; i < chips.length; i++) {
                var c = chips[i].getAttribute('data-grams');
                chips[i].setAttribute('aria-pressed', String(preset ? c === String(value) : c === 'other'));
                chips[i].classList.toggle('on', preset ? c === String(value) : c === 'other');
            }
            other.hidden = preset;
            if (value !== 'other') grams.value = value;
            update();
        }
        function cups(g) { return dose ? Math.round(g / dose) : 0; }
        function update() {
            var g = parseFloat(grams.value) || 0, n = parseInt(count.value, 10) || 0;
            var frozen = g * n, rest = Math.round((left - frozen) * 10) / 10;
            if (g > 0 && n > 1 && frozen > left) { n = Math.max(1, Math.floor(left / g)); count.value = n; frozen = g * n; rest = Math.round((left - frozen) * 10) / 10; }
            var html = '';
            if (rest > 0) html += '<i class="keep" style="flex:' + rest + '">' + Math.round(rest) + ' g out</i>';
            for (var i = 0; i < Math.min(n, 20); i++) html += '<i style="flex:' + g + '">' + g + ' g</i>';
            bar.innerHTML = html;
            var ok = g >= 5 && n >= 1 && frozen <= left + 1e-6;
            go.disabled = !ok;
            go.textContent = 'Freeze ' + n + ' portion' + (n === 1 ? '' : 's');
            if (!ok) { sum.textContent = g * n > left ? 'That’s more than the ' + Math.round(left) + ' g left.' : ''; return; }
            sum.textContent = n + ' × ' + g + ' g frozen today' + (cups(g) ? ' (about ' + cups(g) + ' cups each)' : '') +
                (rest > 0 ? ' · ' + Math.round(rest) + ' g stays out' + (cups(rest) ? ' (about ' + cups(rest) + ' cups)' : '') : ' · nothing stays out');
        }
        form.addEventListener('click', function (e) {
            var chip = e.target.closest('.freeze-sizes .chip');
            if (!chip) return;
            var v = chip.getAttribute('data-grams');
            pick(v);
            if (v === 'other') grams.focus();
        });
        form.addEventListener('input', update);
        form.addEventListener('submit', function () { try { localStorage.setItem(KEY, grams.value); } catch (err) { /* private mode */ } });

        var saved = null;
        try { saved = localStorage.getItem(KEY); } catch (err) { /* private mode */ }
        var start = parseFloat(saved) || 60;
        if (start > left) start = ['90', '60', '30'].filter(function (v) { return +v <= left; })[0] || Math.floor(left);
        grams.value = start;
        count.value = Math.max(1, Math.min(50, Math.floor(left / start) - (left - Math.floor(left / start) * start < start / 2 && Math.floor(left / start) > 1 ? 1 : 0)));
        pick(['30', '60', '90'].indexOf(String(start)) !== -1 ? String(start) : 'other');
    }
    document.addEventListener('DOMContentLoaded', function () {
        var forms = document.querySelectorAll('.freeze-form');
        for (var i = 0; i < forms.length; i++) setup(forms[i]);
    });
})();
