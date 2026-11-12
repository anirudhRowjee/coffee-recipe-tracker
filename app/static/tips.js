// "?" tips (partials/tip.html) and the one-time tour on Brew.
(function () {
    var supportsPopover = typeof HTMLElement !== 'undefined' && HTMLElement.prototype.hasOwnProperty('popover');
    var lastButton = null;

    // Place an open tip under (or above) the button that opened it, inside the screen
    function place(pop, btn) {
        if (!btn) return;
        var r = btn.getBoundingClientRect();
        var w = Math.min(280, window.innerWidth - 24);
        pop.style.width = w + 'px';
        var left = Math.max(12, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 12));
        pop.style.left = left + 'px';
        pop.style.right = 'auto';
        pop.style.margin = '0';
        var below = r.bottom + 8;
        pop.style.top = below + 'px';
        var h = pop.offsetHeight;
        if (below + h > window.innerHeight - 12 && r.top - h - 8 > 12) pop.style.top = (r.top - h - 8) + 'px';
        pop.style.setProperty('--arrow-x', (r.left + r.width / 2 - left) + 'px');
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.tip-btn');
        if (!btn) {
            if (!supportsPopover) {
                document.querySelectorAll('.tip-pop.is-open').forEach(function (p) {
                    if (!p.contains(e.target)) p.classList.remove('is-open');
                });
            }
            return;
        }
        e.stopPropagation();  // a "?" inside a <summary> mustn't open or close the section
        e.preventDefault();
        lastButton = btn;
        var pop = document.getElementById(btn.getAttribute('popovertarget'));
        if (!pop) return;
        if (supportsPopover) {
            pop.togglePopover();
        } else {
            var open = !pop.classList.contains('is-open');
            document.querySelectorAll('.tip-pop.is-open').forEach(function (p) { p.classList.remove('is-open'); });
            pop.classList.toggle('is-open', open);
            if (open) place(pop, btn);
        }
    }, true);

    document.addEventListener('toggle', function (e) {
        if (e.target.classList && e.target.classList.contains('tip-pop') && e.newState === 'open') place(e.target, lastButton);
    }, true);

    // ---- The tour: a few cards pointing at things, the first time someone sees Brew ----
    // Targets carry data-tour="<order>" and data-tour-text; remembered per person on this device.
    var running = false;
    function startTour(force) {
        if (running) return;
        var key = 'coffee-tour-' + (document.body.getAttribute('data-user') || '');
        try { if (!force && localStorage.getItem(key)) return; } catch (err) { return; }
        var targets = Array.prototype.slice.call(document.querySelectorAll('[data-tour]'))
            .filter(function (el) { return el.offsetParent !== null; })
            .sort(function (a, b) { return a.getAttribute('data-tour') - b.getAttribute('data-tour'); });
        if (!targets.length) return;
        running = true;
        var i = 0;
        var spot = document.createElement('div');
        spot.className = 'tour-spot';
        var card = document.createElement('div');
        card.className = 'tour-card';
        card.setAttribute('role', 'dialog');
        document.body.appendChild(spot);
        document.body.appendChild(card);
        function done() {
            try { localStorage.setItem(key, '1'); } catch (err) { /* private mode */ }
            spot.remove(); card.remove();
            running = false;
        }
        function show() {
            var el = targets[i];
            el.scrollIntoView({ block: 'center' });
            var r = el.getBoundingClientRect();
            spot.style.top = (r.top - 6) + 'px'; spot.style.left = (r.left - 6) + 'px';
            spot.style.width = (r.width + 12) + 'px'; spot.style.height = (r.height + 12) + 'px';
            card.innerHTML = '<p></p><div class="tour-actions"><span>' + (i + 1) + ' of ' + targets.length +
                '</span><button type="button" class="tour-skip">Skip</button><button type="button" class="tour-next">' +
                (i === targets.length - 1 ? 'Got it' : 'Next') + '</button></div>';
            card.querySelector('p').textContent = el.getAttribute('data-tour-text');
            var below = r.bottom + 14;
            card.style.top = (below + 150 < window.innerHeight ? below : Math.max(12, r.top - 160)) + 'px';
        }
        card.addEventListener('click', function (e) {
            if (e.target.classList.contains('tour-skip')) done();
            if (e.target.classList.contains('tour-next')) { i += 1; if (i >= targets.length) done(); else show(); }
        });
        show();
    }
    window.coffeeTour = startTour;
    window.addEventListener('load', function () {
        setTimeout(function () { startTour(/[?&]tour=1/.test(location.search)); }, 400);
    });
    document.addEventListener('htmx:afterSwap', function () { setTimeout(function () { startTour(false); }, 300); });
})();
