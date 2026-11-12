// Try a change (change_recipe.html): one tile at a time.
(function () {
    var form = document.getElementById('variation-form');
    if (!form) return;
    var LABEL = { dose_g: 'Coffee', grind_size: 'Grind', water_ml: 'Water', temp_c: 'Temp', recipe_text: 'Method' };
    var UNIT = { dose_g: ' g', grind_size: '', water_ml: ' ml', temp_c: ' °C', recipe_text: '' };
    var save = document.getElementById('change-save');
    var saveLabel = save.textContent;
    var summary = document.getElementById('change-summary');
    var why = document.getElementById('change-why');
    var methodBox = document.getElementById('method-editor');
    var methodOriginal = document.getElementById('method-original');
    var methodTouched = false;

    function fmt(n) { return String(Math.round(n * 1000) / 1000); }
    function input(param) { return form.querySelector('.change-editor [name="' + param + '"]'); }
    function selected() {
        var r = form.querySelector('[name="changed_param"]:checked');
        return r ? r.value : '';
    }

    function resetMethod() {
        if (!methodTouched) return;
        methodBox.innerHTML = methodOriginal.innerHTML;
        if (window.initStepEditors) window.initStepEditors(methodBox);
        annotate();
        methodTouched = false;
    }

    function refresh() {
        var param = selected();
        form.querySelectorAll('.change-tile').forEach(function (tile) {
            var p = tile.getAttribute('data-param');
            tile.classList.toggle('active', p === param);
            tile.classList.toggle('locked', !!param && p !== param);
        });
        form.querySelectorAll('.change-editor').forEach(function (ed) {
            ed.hidden = ed.getAttribute('data-for') !== param;
        });
        var changed = false;
        ['dose_g', 'grind_size', 'water_ml', 'temp_c'].forEach(function (p) {
            var el = input(p);
            var was = el.getAttribute('data-original');
            if (p !== param && el.value !== was) el.value = was;  // only the picked one may differ
            var show = form.querySelector('[data-show="' + p + '"]');
            if (show) show.textContent = el.value;
            var wasTag = form.querySelector('[data-was="' + p + '"]');
            var diff = form.querySelector('[data-diff="' + p + '"]');
            var differs = el.value.trim() !== was;
            if (wasTag) wasTag.hidden = !differs;
            if (diff) {
                var a = parseFloat(el.value), b = parseFloat(was);
                diff.textContent = !differs ? 'Same as now: ' + was + UNIT[p]
                    : isNaN(a) || isNaN(b) ? 'was ' + was + UNIT[p]
                    : 'was ' + was + UNIT[p] + ' · ' + (a > b ? '+' : '−') + fmt(Math.abs(a - b)) + UNIT[p];
            }
            if (p === param && differs) {
                changed = true;
                summary.innerHTML = '';
                var strong = document.createElement('strong');
                strong.textContent = LABEL[p] + ' ' + was + ' → ' + el.value + UNIT[p];
                summary.appendChild(strong);
                summary.appendChild(document.createTextNode('. Everything else stays the same.'));
            }
        });
        if (param !== 'recipe_text') resetMethod();
        if (param === 'recipe_text' && methodTouched) {
            changed = true;
            summary.innerHTML = '<strong>Method</strong>. Everything else stays the same.';
        }
        if (!changed) summary.textContent = param ? 'Set the new ' + LABEL[param].toLowerCase() + '.' : 'Nothing yet. Tap a setting.';
        save.disabled = !changed;
        save.textContent = changed ? saveLabel : (param ? 'Change the ' + LABEL[param].toLowerCase() + ' to save' : 'Pick one thing to change');
    }

    form.addEventListener('change', function (e) {
        if (e.target.name === 'changed_param') {
            var ed = form.querySelector('.change-editor[data-for="' + e.target.value + '"]');
            refresh();
            if (ed) ed.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    });
    form.addEventListener('input', function (e) {
        if (e.target.closest('#method-editor')) methodTouched = true;
        refresh();
    });
    // the step editor's own buttons (+ Add a step, ✕, − / +) change it without an input event
    methodBox.addEventListener('click', function (e) {
        if (e.target.closest('button')) setTimeout(function () { methodTouched = true; refresh(); }, 0);
    });

    form.addEventListener('click', function (e) {
        var btn = e.target.closest('.stepper-btn');
        if (btn) {
            var el = btn.parentNode.querySelector('input');
            var step = parseFloat(btn.getAttribute('data-step'));
            var v = parseFloat(el.value);
            if (isNaN(v)) return;
            var next = Math.round((v + step) * 1000) / 1000;
            if (el.min !== '' && next < parseFloat(el.min)) next = parseFloat(el.min);
            if (el.max !== '' && next > parseFloat(el.max)) next = parseFloat(el.max);
            el.value = fmt(next);
            refresh();
        }
        var chip = e.target.closest('[data-why]');
        if (chip) { why.value = chip.getAttribute('data-why'); chip.classList.add('on'); }
    });

    form.addEventListener('submit', function (e) {
        if (save.disabled) e.preventDefault();
    });

    // After "Save and edit the steps now": each row shows what the scale saw, and
    // "Use what I did" copies the real start times into the rows
    var actuals = [];
    try { actuals = JSON.parse(form.getAttribute('data-actuals') || '[]'); } catch (err) { actuals = []; }
    function mmss(s) { return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
    function annotate() {
        if (!actuals.length) return;
        var rows = methodBox.querySelectorAll('.step-row');
        var any = false;
        rows.forEach(function (row, i) {
            var a = actuals[i];
            var old = row.querySelector('.step-actual');
            if (old) old.remove();
            if (!a || (a.start === null && a.reached === null)) return;
            any = true;
            var tag = document.createElement('span');
            tag.className = 'step-actual';
            var bits = [];
            if (a.start !== null && i) bits.push('started ' + mmss(a.start));
            if (a.reached !== null) bits.push(a.grams + ' g at ' + mmss(a.reached));
            tag.textContent = '● ' + bits.join(' · ');
            row.appendChild(tag);
        });
        form.querySelector('.actuals-bar').hidden = !any;
    }
    document.addEventListener('DOMContentLoaded', annotate);
    var useActuals = document.getElementById('use-actuals');
    if (useActuals) useActuals.addEventListener('click', function () {
        methodBox.querySelectorAll('.step-row').forEach(function (row, i) {
            var a = actuals[i];
            var time = row.querySelector('.step-time');
            if (a && a.start !== null && time) time.value = mmss(Math.round(a.start / 5) * 5);
        });
        var t = methodBox.querySelector('.step-time');
        if (t) t.dispatchEvent(new Event('input', { bubbles: true }));
        useActuals.classList.add('on');
    });

    // Start from the Next time note, if there is one (or from the method, after Stop)
    var recParam = form.getAttribute('data-start-method') ? 'recipe_text' : form.getAttribute('data-rec-param');
    if (recParam) {
        var radio = form.querySelector('[name="changed_param"][value="' + recParam + '"]');
        if (radio) {
            radio.checked = true;
            var recDelta = parseFloat(form.getAttribute('data-rec-delta'));
            var el = input(recParam);
            if (el && !isNaN(recDelta) && !isNaN(parseFloat(el.value))) el.value = fmt(parseFloat(el.value) + recDelta);
            if (form.getAttribute('data-rec-why')) why.value = form.getAttribute('data-rec-why');
        }
    }
    refresh();
})();
