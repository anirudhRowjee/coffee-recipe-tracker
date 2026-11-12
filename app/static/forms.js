// Form checks that never lose your work.
// - Problems show under the field in plain words, as you leave it and when you press
//   Save; the browser's own bubbles are switched off (novalidate).
// - A name you already use (data-taken='["Default","2 cup"]') is caught before saving.
// - Unusual but possible numbers (a ratio outside 1:12 to 1:20) get an amber note and still save.
// - Textareas with data-draft="key" are saved on the device as you type and come back
//   after a reload; a successful submit clears them.
// - A form can't be sent twice by a double tap.
(function () {
    function labelOf(el) {
        if (el.getAttribute('data-label')) return el.getAttribute('data-label');
        var label = el.closest('label') || (el.id && document.querySelector('label[for="' + el.id + '"]'));
        var text = '';
        if (label) {
            label.childNodes.forEach(function (n) { if (n.nodeType === 3) text += n.textContent; });
            text = text.trim() || label.textContent.trim();
        }
        text = text || el.getAttribute('aria-label') || el.name || 'This';
        return text.replace(/\s*\(.*?\)\s*/g, ' ').replace(/[?:*]/g, '').trim();
    }

    function messageFor(el) {
        var v = el.validity;
        var name = labelOf(el);
        if (v.customError) return el.validationMessage;
        if (v.valueMissing) return name + ' is needed.';
        if (v.badInput || v.typeMismatch) return name + ' needs to be a number.';
        if (v.rangeUnderflow || v.rangeOverflow) {
            return name + ' should be between ' + el.min + ' and ' + el.max + (el.getAttribute('data-unit') || '') + '.';
        }
        if (v.stepMismatch) return name + " can't take that value.";
        return el.validationMessage;
    }

    function slotFor(el) {
        var anchor = el.closest('.signed-input, .stepper, .step-editor') || el.closest('label') || el;
        var slot = anchor.nextElementSibling;
        if (!slot || !slot.classList || !slot.classList.contains('field-error')) {
            slot = document.createElement('p');
            slot.className = 'field-error';
            slot.setAttribute('role', 'alert');
            anchor.parentNode.insertBefore(slot, anchor.nextSibling);
        }
        return slot;
    }

    function checkTaken(el) {
        var taken = el.getAttribute('data-taken');
        if (!taken) return;
        var list = [];
        try { list = JSON.parse(taken); } catch (e) { list = []; }
        var value = el.value.trim().toLowerCase();
        var hit = list.filter(function (n) { return n.toLowerCase() === value; })[0];
        el.setCustomValidity(hit && value !== (el.getAttribute('data-current') || '').toLowerCase()
            ? 'You already have "' + hit + '" for this coffee and gear. Pick another name.' : '');
    }

    function check(el) {
        if (!el.willValidate) return true;
        checkTaken(el);
        var ok = el.checkValidity();
        el.classList.toggle('field-bad', !ok);
        var slot = ok ? (el.closest('label') || el).parentNode.querySelector('.field-error') : slotFor(el);
        if (slot) { slot.textContent = ok ? '' : messageFor(el); slot.hidden = ok; }
        return ok;
    }

    function ratioNote(form) {
        var dose = form.querySelector('input[name="dose_g"]:not([type=hidden])');
        var water = form.querySelector('input[name="water_ml"]:not([type=hidden])');
        if (!dose || !water) return;
        var note = form.querySelector('.ratio-warning');
        if (!note) {
            note = document.createElement('p');
            note.className = 'form-warning ratio-warning';
            note.hidden = true;
            (water.closest('label, .change-editor') || water).insertAdjacentElement('afterend', note);
        }
        var r = parseFloat(water.value) / parseFloat(dose.value);
        var odd = isFinite(r) && r > 0 && (r < 12 || r > 20);
        note.hidden = !odd;
        if (odd) note.textContent = "That's 1:" + (Math.round(r * 10) / 10) + ', ' + (r > 20 ? 'much weaker' : 'much stronger') +
            ' than most recipes (1:15 to 1:17). Fine to save if it\'s what you meant.';
    }

    function setup(form) {
        if (form.getAttribute('data-checked') || (form.method || '').toLowerCase() !== 'post') return;
        form.setAttribute('data-checked', '1');
        form.noValidate = true;
        form.addEventListener('focusout', function (e) {
            if (e.target.matches('input, select, textarea') && e.target.value !== '') check(e.target);
        });
        form.addEventListener('input', function (e) {
            if (e.target.classList.contains('field-bad')) check(e.target);
            if (e.target.name === 'dose_g' || e.target.name === 'water_ml') ratioNote(form);
            var key = e.target.getAttribute && e.target.getAttribute('data-draft');
            if (key) { try { localStorage.setItem('draft:' + key, e.target.value); } catch (err) { /* private mode */ } }
        });
        form.addEventListener('submit', function (e) {
            if (e.defaultPrevented) return;
            var bad = Array.prototype.filter.call(form.elements, function (el) {
                return el.willValidate && !el.closest('[hidden]') && !check(el);
            });
            if (bad.length) {
                e.preventDefault();
                bad[0].focus();
                bad[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
                return;
            }
            form.querySelectorAll('[data-draft]').forEach(function (t) {
                try { localStorage.removeItem('draft:' + t.getAttribute('data-draft')); } catch (err) { /* ignore */ }
            });
            // one tap, one save: disable after the browser has read the pressed button
            setTimeout(function () {
                form.querySelectorAll('button[type=submit], button:not([type])').forEach(function (b) { b.disabled = true; });
            }, 0);
        });
        ratioNote(form);
        form.querySelectorAll('textarea[data-draft]').forEach(function (t) {
            var saved = null;
            try { saved = localStorage.getItem('draft:' + t.getAttribute('data-draft')); } catch (err) { saved = null; }
            if (saved && !t.value.trim()) {
                t.value = saved;
                var note = document.createElement('p');
                note.className = 'form-note';
                note.textContent = 'Your unsaved notes were brought back.';
                t.insertAdjacentElement('beforebegin', note);
            }
        });
    }

    function init(root) { (root || document).querySelectorAll('form').forEach(setup); }
    document.addEventListener('DOMContentLoaded', function () { init(document); });
    document.addEventListener('htmx:afterSwap', function (e) { init(e.target); });
    // coming back to a page from the history: buttons work again
    window.addEventListener('pageshow', function () {
        document.querySelectorAll('form[data-checked] button[disabled]').forEach(function (b) { b.disabled = false; });
        var change = document.getElementById('variation-form');  // Try a change decides its own Save button
        if (change) change.dispatchEvent(new Event('input', { bubbles: true }));
    });
})();
