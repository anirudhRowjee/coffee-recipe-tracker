// Step editor: rows of time / action / target weight over a recipe's plain text
// box. The textarea stays the real form field, so without JavaScript (or for a
// free-text recipe) the form is exactly what it always was. It is only rewritten
// when someone actually edits a step, so an untouched recipe can't change.
// Written in ES5 like the other scripts.
(function () {
    function secondsOf(value) {
        var m = /^(\d{1,2}):([0-5]\d)$/.exec(value);
        return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : null;
    }

    function asTime(seconds) {
        return Math.floor(seconds / 60) + ':' + ('0' + (seconds % 60)).slice(-2);
    }

    // Phones get a number pad with no colon, so "140" means 1:40 and "45" means 0:45
    function tidyTime(value) {
        var v = value.replace(/\s/g, '');
        if (!/^\d{1,4}$/.test(v)) return v;
        if (v.length <= 2) return asTime(parseInt(v, 10));
        return v.slice(0, -2) + ':' + v.slice(-2);
    }

    function field(className, label, value, inputMode) {
        var input = document.createElement('input');
        input.type = 'text';
        input.className = className;
        input.value = value || '';
        input.setAttribute('aria-label', label);
        if (inputMode) input.setAttribute('inputmode', inputMode);
        return input;
    }

    function build(editor) {
        if (editor.getAttribute('data-ready')) return;
        editor.setAttribute('data-ready', '1');
        var textarea = editor.nextElementSibling;
        var data;
        try { data = JSON.parse(editor.getAttribute('data-step-editor')); } catch (e) { return; }
        if (!data.editable) return;

        var form = textarea.form;
        var checks = (editor.getAttribute('data-checks') || '').split(',');
        var freeText = false;
        var touched = false;

        var prepLabel = document.createElement('label');
        prepLabel.className = 'step-prep';
        prepLabel.appendChild(document.createTextNode('Before you start (not timed)'));
        var prep = field('step-prep-input', 'Before you start', data.prep);
        prepLabel.appendChild(prep);

        var rows = document.createElement('div');
        rows.className = 'step-rows';

        var error = document.createElement('p');
        error.className = 'form-error';
        error.hidden = true;

        var add = document.createElement('button');
        add.type = 'button';
        add.className = 'btn-secondary';
        add.textContent = '+ Add step';

        var hint = document.createElement('p');
        hint.className = 'muted step-hint';
        hint.textContent = 'Time as 1:40, or just 140. Add a step called Done to stop the timer automatically.';

        var plain = document.createElement('button');
        plain.type = 'button';
        plain.className = 'step-plain';
        plain.textContent = 'Write as plain text instead';

        function rowData() {
            var out = [];
            var list = rows.children;
            for (var i = 0; i < list.length; i++) {
                var time = list[i].querySelector('.step-time');
                var action = list[i].querySelector('.step-action');
                var grams = list[i].querySelector('.step-grams');
                if (time.value.trim() || action.value.trim()) {
                    out.push({ time: time, action: action, grams: grams });
                }
            }
            return out;
        }

        function serialise() {
            var lines = [];
            if (prep.value.trim()) lines.push('Prep: ' + prep.value.trim());
            rowData().forEach(function (r) {
                var grams = r.grams.value.trim();
                lines.push(tidyTime(r.time.value.trim()) + ' — ' + r.action.value.trim() + (grams ? ' (to ' + grams + 'g)' : ''));
            });
            textarea.value = lines.join('\n');
        }

        function edited() {
            touched = true;
            error.hidden = true;
            serialise();
            // In the variation form, changing the steps is the one change being made
            var changed = form.querySelector('[name="changed_param"]');
            if (changed) {
                changed.value = 'recipe_text';
                if (window.toggleDeltaAmount) window.toggleDeltaAmount(changed);
            }
        }

        function addRow(step, needsCheck) {
            var row = document.createElement('div');
            row.className = 'step-row';
            var time = field('step-time', 'Time', step.time, 'numeric');
            var action = field('step-action', 'What to do', step.action);
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'step-remove';
            remove.setAttribute('aria-label', 'Remove this step');
            remove.textContent = '✕';
            var pour = document.createElement('label');
            pour.className = 'step-pour';
            pour.appendChild(document.createTextNode('Pour to '));
            var grams = field('step-grams', 'Pour to grams', step.grams, 'decimal');
            pour.appendChild(grams);
            pour.appendChild(document.createTextNode(' g'));
            if (needsCheck) {
                var tag = document.createElement('span');
                tag.className = 'step-check';
                tag.textContent = 'check this';
                pour.appendChild(tag);
            }
            // tapping a time selects it, so typing replaces rather than appends
            time.addEventListener('focus', function () { time.select(); });
            time.addEventListener('input', edited);
            action.addEventListener('input', edited);
            grams.addEventListener('input', edited);
            time.addEventListener('blur', function () {
                var tidied = tidyTime(time.value);
                if (tidied !== time.value) { time.value = tidied; edited(); }
            });
            remove.addEventListener('click', function () { rows.removeChild(row); edited(); });
            row.appendChild(time);
            row.appendChild(action);
            row.appendChild(remove);
            row.appendChild(pour);
            rows.appendChild(row);
            return time;
        }

        data.steps.forEach(function (step, i) { addRow(step, checks.indexOf(String(i)) !== -1); });
        if (!data.steps.length) addRow({ time: '0:00' }, false);

        prep.addEventListener('input', edited);
        add.addEventListener('click', function () {
            var existing = rowData();
            var last = existing.length ? secondsOf(tidyTime(existing[existing.length - 1].time.value.trim())) : null;
            addRow({ time: last === null ? '' : asTime(last + 30) }, false).focus();
            edited();
        });
        plain.addEventListener('click', function () {
            freeText = true;
            editor.hidden = true;
            textarea.hidden = false;
        });

        form.addEventListener('submit', function (event) {
            if (freeText || !touched) return;
            serialise();
            var last = -1, problem = '';
            rowData().forEach(function (r, i) {
                var s = secondsOf(tidyTime(r.time.value.trim()));
                r.time.classList.remove('step-bad');
                if (problem) return;
                if (s === null) problem = 'Step ' + (i + 1) + ': write the time like 1:40.';
                else if (s < last) problem = 'Step ' + (i + 1) + ' is earlier than the step above it.';
                else if (!r.action.value.trim()) problem = 'Step ' + (i + 1) + ' needs something to do.';
                if (problem) r.time.classList.add('step-bad');
                if (s !== null) last = s;
            });
            if (problem) {
                error.textContent = problem;
                error.hidden = false;
                event.preventDefault();
            }
        });

        editor.appendChild(prepLabel);
        editor.appendChild(rows);
        editor.appendChild(error);
        editor.appendChild(add);
        editor.appendChild(hint);
        if (editor.getAttribute('data-free-text') === '1') editor.appendChild(plain);
        editor.hidden = false;
        textarea.hidden = true;
    }

    function init(root) {
        var editors = root.querySelectorAll('[data-step-editor]');
        for (var i = 0; i < editors.length; i++) build(editors[i]);
    }

    document.addEventListener('DOMContentLoaded', function () {
        init(document);
        document.body.addEventListener('htmx:afterSwap', function (event) { init(event.target); });
    });
})();
