// Bottom sheets (a phone) and centred panels (an iPad), built on <dialog>.
// <button data-sheet="id"> opens <dialog class="sheet" id="id">; anything with
// data-sheet-close, a tap on the backdrop, or Escape closes it. Delegated, so it
// also works for content htmx swaps in later.
(function () {
    document.addEventListener('click', function (e) {
        var opener = e.target.closest('[data-sheet]');
        if (opener) {
            var sheet = document.getElementById(opener.getAttribute('data-sheet'));
            if (sheet && sheet.showModal) {
                e.preventDefault();
                var parent = opener.closest('dialog[open]');  // one sheet at a time
                if (parent && parent !== sheet) parent.close();
                sheet.showModal();
                var first = sheet.querySelector('[autofocus]');
                if (first) first.focus();
            }
            return;
        }
        var closer = e.target.closest('[data-sheet-close]');
        if (closer) {
            var dlg = closer.closest('dialog');
            if (dlg) { e.preventDefault(); dlg.close(); }
            return;
        }
        // a tap on the dimmed backdrop lands on the <dialog> itself, outside its box
        if (e.target.tagName === 'DIALOG' && e.target.classList.contains('sheet')) {
            var r = e.target.getBoundingClientRect();
            if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) e.target.close();
        }
    });
    // Folded on a phone, open on an iPad or wider: <details data-open-wide>
    if (window.matchMedia && window.matchMedia('(min-width: 1024px)').matches) {
        document.addEventListener('DOMContentLoaded', function () {
            document.querySelectorAll('details[data-open-wide]').forEach(function (d) { d.open = true; });
        });
    }

    // "‹ Back" (data-back) goes to the page you came from, when that was one of ours
    document.addEventListener('click', function (e) {
        var back = e.target.closest('[data-back]');
        if (!back) return;
        var ref = document.referrer;
        if (ref && ref.indexOf(location.origin) === 0 && ref !== location.href && history.length > 1) {
            e.preventDefault();
            history.back();
        }
    });
})();
