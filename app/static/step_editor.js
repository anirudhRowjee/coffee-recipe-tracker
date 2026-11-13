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

        // "Before you start" (untimed prep) folds into a link until there's something in it
        var prepLabel = document.createElement('label');
        prepLabel.className = 'step-prep';
        prepLabel.appendChild(document.createTextNode('Before you start (not timed)'));
        var prep = field('step-prep-input', 'Before you start', data.prep);
        prepLabel.appendChild(prep);
        var prepOpen = document.createElement('button');
        prepOpen.type = 'button';
        prepOpen.className = 'step-plain step-prep-open';
        prepOpen.textContent = '+ Something to do before you start';
        prepLabel.hidden = !data.prep;
        prepOpen.hidden = !!data.prep;
        prepOpen.addEventListener('click', function () { prepOpen.hidden = true; prepLabel.hidden = false; prep.focus(); });

        // A first-time user read the times as how long each step lasts ("so Done is 0:00?"):
        // one line says they're clock times from Start, and the columns are labelled to match
        var intro = document.createElement('p');
        intro.className = 'step-intro';
        intro.textContent = 'Each time is when that step begins, counted from Start, not how long it lasts.';
        var head = document.createElement('div');
        head.className = 'step-head';
        head.setAttribute('aria-hidden', 'true');
        head.innerHTML = '<span>Starts at</span><span>What to do</span>';

        var rows = document.createElement('div');
        rows.className = 'step-rows';

        // Edit steps: off, the steps are a list to read (fields read-only, so a stray tap neither
        // opens the keyboard nor nudges a number; no − / +, ✕, ⠿ or Add step); on, every control.
        // Remembered on this device; always on while there are no steps to read.
        var editing = false, pourSyncs = [];
        try { editing = window.localStorage.getItem('step-editing') === '1'; } catch (e) {}
        if (!data.steps.length) editing = true;
        var editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'chip step-edit-toggle';
        function setEditing(on, remember) {
            editing = on;
            editor.classList.toggle('step-editing', on);
            editBtn.textContent = on ? 'Done editing' : '✎ Edit steps';
            editBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            Array.prototype.forEach.call(editor.querySelectorAll('input'), function (i) { i.readOnly = !on; });
            pourSyncs.forEach(function (sync) { sync(); });
            if (remember) { try { window.localStorage.setItem('step-editing', on ? '1' : '0'); } catch (e) {} }
        }
        editBtn.addEventListener('click', function () { setEditing(!editing, true); });

        var error = document.createElement('p');
        error.className = 'form-error';
        error.hidden = true;

        var add = document.createElement('button');
        add.type = 'button';
        add.className = 'btn-secondary';
        add.textContent = '+ Add step';

        var hint = document.createElement('p');
        hint.className = 'muted step-hint';
        hint.textContent = 'Drag ⠿ to move a step: it takes the time of where you drop it. Type times as 1:40 or 140.';

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
            // say so on the real field too, so a page watching for edits (Try a change) sees
            // every kind: typing, − / +, ✕, Add step, and a drag
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            // In the variation form, changing the steps is the one change being made
            var changed = form.querySelector('[name="changed_param"]');
            if (changed && changed.tagName === 'SELECT') {
                changed.value = 'recipe_text';
                if (window.toggleDeltaAmount) window.toggleDeltaAmount(changed);
            } else if (changed) {  // Try a change: the Method tile
                var method = form.querySelector('[name="changed_param"][value="recipe_text"]');
                if (method && !method.checked) { method.checked = true; method.dispatchEvent(new Event('change', { bubbles: true })); }
            }
        }

        // − and + beside a time (1 s) or grams (1 g), so a step can be nudged without the keyboard
        function nudger(input, kind, label) {
            var wrap = document.createElement('span');
            wrap.className = 'step-nudge';
            [-1, 1].forEach(function (sign) {
                var b = document.createElement('button');
                b.type = 'button';
                b.textContent = sign < 0 ? '−' : '+';
                b.setAttribute('aria-label', (sign < 0 ? 'Less ' : 'More ') + label);
                b.addEventListener('click', function () {
                    if (kind === 'time') {
                        var now = secondsOf(tidyTime(input.value.trim()));
                        input.value = asTime(Math.max(0, (now === null ? 0 : now) + sign));
                    } else {
                        var g = parseFloat(input.value) || 0;
                        input.value = String(Math.max(0, Math.round((g + sign) * 10) / 10));
                    }
                    edited();
                });
                if (sign < 0) wrap.appendChild(b); else { wrap.appendChild(input); wrap.appendChild(b); }
            });
            return wrap;
        }

        // the words brew mode recognises (and animates), offered as you type an action
        if (!document.getElementById('step-action-list')) {
            var list = document.createElement('datalist');
            list.id = 'step-action-list';
            ['Bloom', 'Pour', 'Swirl', 'Stir', 'Wait', 'Close valve', 'Open valve', 'Press', 'Flip', 'Drawdown', 'Done'].forEach(function (w) {
                var o = document.createElement('option');
                o.value = w;
                list.appendChild(o);
            });
            document.body.appendChild(list);
        }

        // Drag ⠿ to reorder (pointer events, so a finger works as well as a mouse). The row
        // follows the finger and swaps with a neighbour once it passes that one's middle. Times
        // must stay in order, so they belong to the places: on drop each row takes the time of
        // the place it ended up in, and the step (action and grams) is what moved.
        function dragHandle(row) {
            var handle = document.createElement('button');
            handle.type = 'button';
            handle.className = 'step-drag';
            handle.setAttribute('aria-label', 'Drag to move this step');
            handle.textContent = '⠿';
            handle.addEventListener('pointerdown', function (e) {
                if (e.button !== undefined && e.button !== 0) return;
                e.preventDefault();
                try { handle.setPointerCapture(e.pointerId); } catch (err) {}
                var times = Array.prototype.map.call(rows.children, function (r) { return r.querySelector('.step-time').value; });
                var before = Array.prototype.slice.call(rows.children);
                var startY = e.clientY, lastY = e.clientY, baseTop = row.offsetTop;
                row.classList.add('step-dragging');
                function mid(el) { var b = el.getBoundingClientRect(); return b.top + b.height / 2; }
                function place() {
                    // as many places as the finger has passed (a quick flick can cross several)
                    for (var moved = true; moved;) {
                        var prev = row.previousElementSibling, next = row.nextElementSibling;
                        moved = false;
                        if (prev && lastY < mid(prev)) { rows.insertBefore(row, prev); moved = true; }
                        else if (next && lastY > mid(next)) { rows.insertBefore(next, row); moved = true; }
                    }
                    row.style.transform = 'translateY(' + ((lastY - startY) - (row.offsetTop - baseTop)) + 'px)';
                }
                // near the top or bottom of the screen, scroll so a long method can be crossed
                var scroller = setInterval(function () {
                    var edge = 70, h = window.innerHeight;
                    var by = lastY < edge ? -10 : lastY > h - edge ? 10 : 0;
                    if (!by) return;
                    window.scrollBy(0, by);
                    startY -= by;
                    place();
                }, 16);
                function move(ev) { if (ev.pointerId === e.pointerId) { lastY = ev.clientY; place(); } }
                function end(ev) {
                    if (ev.pointerId !== e.pointerId) return;
                    clearInterval(scroller);
                    document.removeEventListener('pointermove', move);
                    document.removeEventListener('pointerup', end);
                    document.removeEventListener('pointercancel', end);
                    row.classList.remove('step-dragging');
                    row.style.transform = '';
                    var after = Array.prototype.slice.call(rows.children);
                    if (after.some(function (r, i) { return r !== before[i]; })) {
                        after.forEach(function (r, i) { r.querySelector('.step-time').value = times[i]; });
                        edited();
                    }
                }
                // on the page, not the handle: the finger soon leaves the handle, and not every
                // browser keeps the pointer captured
                document.addEventListener('pointermove', move);
                document.addEventListener('pointerup', end);
                document.addEventListener('pointercancel', end);
            });
            return handle;
        }

        var NO_WEIGHT = /^(swirl|stir|wait|rest|drawdown|done|press|flip|remove|serve|drain|release|(open|close)( the)? valve|valve (open|close)d?)\b/i;

        function addRow(step, needsCheck) {
            var row = document.createElement('div');
            row.className = 'step-row';
            var time = field('step-time', 'Starts at (minutes:seconds from Start)', step.time, 'numeric');
            var action = field('step-action', 'What to do', step.action);
            action.setAttribute('list', 'step-action-list');
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'step-remove';
            remove.setAttribute('aria-label', 'Remove this step');
            remove.textContent = '✕';
            var pour = document.createElement('label');
            pour.className = 'step-pour';
            var verb = document.createElement('span');
            verb.className = 'step-pour-verb';
            verb.textContent = 'Pour';
            pour.appendChild(verb);
            pour.appendChild(document.createTextNode(' to '));
            var grams = field('step-grams', 'Pour to grams', step.grams, 'decimal');
            pour.appendChild(nudger(grams, 'grams', 'water'));
            pour.appendChild(document.createTextNode(' g'));
            if (needsCheck) {
                var tag = document.createElement('span');
                tag.className = 'step-check';
                tag.textContent = 'check this';
                pour.appendChild(tag);
            }
            // "Pour to" only on steps that might pour: while editing, hidden for the words that
            // never do (and never while it has grams); while reading, only where there are grams
            function syncPour() {
                var none = !grams.value.trim() && (!editing || NO_WEIGHT.test(action.value.trim()));
                pour.hidden = none;
                row.classList.toggle('no-weight', none);
            }
            action.addEventListener('input', syncPour);
            pourSyncs.push(syncPour);
            syncPour();
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
            row.appendChild(dragHandle(row));
            row.appendChild(nudger(time, 'time', 'time'));
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
            if (freeText || !touched || !editor.isConnected) return;  // a replaced editor no longer counts
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

        editor.appendChild(prepOpen);
        editor.appendChild(prepLabel);
        editor.appendChild(intro);
        editor.appendChild(editBtn);
        editor.appendChild(head);
        editor.appendChild(rows);
        editor.appendChild(error);
        editor.appendChild(add);
        editor.appendChild(hint);
        setEditing(editing, false);
        if (editor.getAttribute('data-free-text') === '1') editor.appendChild(plain);
        editor.hidden = false;
        textarea.hidden = true;
    }

    window.initStepEditors = function (root) { init(root); };

    function init(root) {
        var editors = root.querySelectorAll('[data-step-editor]');
        for (var i = 0; i < editors.length; i++) build(editors[i]);
    }

    document.addEventListener('DOMContentLoaded', function () {
        init(document);
        document.body.addEventListener('htmx:afterSwap', function (event) { init(event.target); });
    });
})();
