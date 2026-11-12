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
})();
