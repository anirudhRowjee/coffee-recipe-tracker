// Brew mode's animation: a small drawing of the brewer doing the current step.
// app/brew.py decides everything about a recipe (brewer shape, what each step is,
// water level, valve, cup) and tests it; this only draws one step at a time as
// SVG, and CSS keyframes in styles.css do the moving. Lengths are the step's real
// seconds, so the drawing keeps time with the clock.
window.BrewAnimation = (function () {
    var CONE_OUTLINE = '<path class="o" d="M38 32 L122 32"/><path class="o" d="M43 33 L72 103 L88 103 L117 33"/>';
    var CONE_HANDLE = '<path class="o thin" d="M109 46 C136 44 134 82 98 80"/>';
    var CONE_INSIDE = 'M44 34 L116 34 L87 100 L73 100 Z';

    var SHAPES = {
        cone: { inside: CONE_INSIDE, top: 34, bottom: 100, bed: 26, curve: 0.55, max: 0.92, out: 104, holes: [80], spread: 12,
            draw: CONE_OUTLINE + '<path class="o" d="M56 106 L104 106"/>' + CONE_HANDLE },
        'switch': { inside: CONE_INSIDE, top: 34, bottom: 100, bed: 26, curve: 0.55, max: 0.92, out: 116, holes: [80], spread: 12, valve: true,
            draw: CONE_OUTLINE + '<path class="o" d="M62 79 L62 115 L98 115 L98 79"/><path class="o" d="M54 116 L106 116"/>' + CONE_HANDLE },
        flat: { inside: 'M46 54 L114 54 L100 100 L60 100 Z', top: 54, bottom: 100, bed: 18, curve: 0.8, max: 0.92, out: 104, holes: [70, 80, 90], spread: 16,
            draw: '<path class="o thin" d="M42 52 L48 44 L54 52 L60 44 L66 52 L72 44 L78 52 L84 44 L90 52 L96 44 L102 52 L108 44 L114 52 L118 46"/>' +
                  '<path class="o" d="M38 52 L122 52"/><path class="o" d="M45 53 L59 103 L101 103 L115 53"/><path class="o" d="M50 106 L110 106"/>' },
        aeropress: { inside: 'M58 18 L102 18 L102 96 L58 96 Z', top: 18, bottom: 96, bed: 16, curve: 1, max: 0.8, out: 104, holes: [80], spread: 8, press: true,
            draw: '<path class="o" d="M57 16 L57 98 M103 16 L103 98"/><path class="o" d="M46 102 L114 102"/><path class="o" d="M57 98 L103 98"/><path class="o thin" d="M62 42 L68 42 M62 60 L68 60 M62 78 L68 78"/>' }
    };

    var MUG = { top: 124, bottom: 178, max: 0.8,
        inside: 'M50 122 L110 122 L106 176 Q106 178 103 178 L57 178 Q54 178 54 176 Z',
        draw: '<path class="o" d="M48 120 L112 120 L108 177 Q108 181 104 181 L56 181 Q52 181 52 177 Z"/><path class="o thin" d="M111 134 C132 132 132 162 108 162"/>' };

    var ACTIVE_SECONDS = 10;  // stirring and swirling take this long, however long the step is
    var READY = { kind: 'idle', at: 0, seconds: 1, from: 0, to: 0, cup_from: 0, cup_to: 0, valve: 'open', flip: false, flow: false };

    var ids = 0;

    function steam(x, y) {
        return '<path class="o thin steam" style="animation-delay:' + (x % 3) * 0.4 + 's" d="M' + x + ' ' + y + ' q-5 -6 0 -12 q5 -6 0 -12"/>';
    }

    function svg(style, inner) {
        return '<svg class="brew-scene" viewBox="0 0 160 190" style="' + style + '" aria-hidden="true">' + inner + '</svg>';
    }

    // Draw one step, `late` seconds after it began.
    function scene(shape, step, late) {
        var s = SHAPES[shape], id = 'brew-clip-' + (++ids), span = s.bottom - s.top;
        var a = step.kind, seconds = Math.max(step.seconds, 0.5);
        var active = Math.min(seconds, ACTIVE_SECONDS) - late;
        if ((a === 'stir' || a === 'swirl') && active <= 0) a = 'idle';

        function waterGap(share) { return (1 - Math.pow(share, s.curve) * s.max) * span; }
        function cupGap(share) { return (1 - share * MUG.max) * (MUG.bottom - MUG.top); }
        var la = waterGap(step.from), lb = waterGap(step.to), ca = cupGap(step.cup_from), cb = cupGap(step.cup_to);
        var tip = 16, reach = s.bottom - tip;
        var vars = {
            '--d': seconds + 's', '--ld': (a === 'bloom' ? seconds * 0.3 : seconds) + 's', '--late': -late + 's',
            '--la': la + 'px', '--lb': lb + 'px', '--ca': ca + 'px', '--cb': cb + 'px',
            '--sa': Math.max(0.05, (s.top + la - tip) / reach), '--sb': Math.max(0.05, (s.top + lb - tip) / reach),
            '--bottom': s.bottom + 'px', '--spread': s.spread + 'px', '--active': Math.max(active, 0) + 's',
            '--swirls': String(Math.max(1, Math.round(active / 1.1))),
            '--drop': (MUG.top + cb - s.out - 6) + 'px',
            '--pa': (s.top + la - 20) + 'px', '--pb': (s.bottom - 26) + 'px'
        };
        var style = Object.keys(vars).map(function (k) { return k + ':' + vars[k]; }).join(';');

        var mugClip = '<clipPath id="' + id + 'm"><path d="' + MUG.inside + '"/></clipPath>';
        var mug = '<g clip-path="url(#' + id + 'm)"><rect class="coffee cup" x="40" y="' + MUG.top + '" width="80" height="' + (MUG.bottom - MUG.top + 10) + '"/></g>' + MUG.draw;

        if (a === 'done') {
            return svg(style, '<defs>' + mugClip + '</defs><g transform="translate(76 118) scale(1.4) translate(-80 -150)">' + mug + '</g>' +
                steam(58, 62) + steam(76, 58) + steam(94, 62));
        }

        var drips = '';
        if (a === 'plunge') {
            drips = '<rect class="coffee" x="78" y="' + s.out + '" width="4" height="' + (MUG.top + cb - s.out + 6) + '"/>';
        } else if (step.flow) {
            s.holes.forEach(function (x, i) {
                drips += '<circle class="coffee fall" cx="' + x + '" cy="' + s.out + '" r="2.4" style="animation-delay:' + i * 0.27 + 's"/>';
            });
        }

        var bubbles = '';
        if (a === 'bloom') {
            [-10, -3, 5, 11].forEach(function (x, i) {
                bubbles += '<circle class="bubble" cx="' + (80 + x) + '" cy="' + (s.bottom - s.bed - 8) + '" r="2.2" fill="#fff" style="animation-delay:' + i * 0.35 + 's"/>';
            });
        }
        var bedClass = a === 'bloom' ? 'bed swell' : (a === 'add' ? 'bed grow' : 'bed');
        var liquid = '<g clip-path="url(#' + id + ')"><g' + (a === 'swirl' ? ' class="slosh"' : '') + '>' +
            '<g class="level"><rect class="water" x="0" y="' + s.top + '" width="160" height="' + (span + 40) + '"/><rect class="surface" x="0" y="' + s.top + '" width="160" height="3"/></g>' +
            '</g><rect class="' + bedClass + '" x="30" y="' + (s.bottom - s.bed) + '" width="100" height="' + s.bed + '"/>' + bubbles + '</g>';

        var valve = '', badge = '';
        if (s.valve) {
            var isOpen = step.valve === 'open';
            var moving = (step.flip || a === 'open' || a === 'close') && late < 1;
            var lever = (moving ? 'to-' : 'is-') + (isOpen ? 'open' : 'closed');
            var state = isOpen ? 'valve-open' : 'valve-closed';
            valve = '<g class="lever ' + lever + ' ' + state + '"><path class="o" d="M98 110 L116 110"/><circle cx="118" cy="110" r="5"/></g>';
            if (!isOpen) valve += '<rect class="plug" x="68" y="99" width="24" height="7" rx="2"/>';
            badge = '<g class="badge ' + state + '"><rect x="2" y="2" width="66" height="23" rx="11.5"/><text x="35" y="19">' + (isOpen ? 'OPEN' : 'CLOSED') + '</text></g>';
        }
        var body = '<g' + (a === 'swirl' ? ' class="swirling"' : '') + '>' + liquid + s.draw + valve + '</g>';

        var over = '';
        if (a === 'pour' || a === 'bloom') {
            over = '<g class="kettle"><g' + (a === 'bloom' ? ' class="brief"' : '') + '>' +
                '<rect class="stream pourline" x="78.5" y="' + tip + '" width="3" height="' + reach + '"/>' +
                '<path class="o" style="stroke-width:5" d="M170 -6 C140 -8 128 18 96 8 L82 14"/></g></g>';
        } else if (a === 'stir') {
            over = '<g class="spoon"><path class="o" d="M80 -8 L80 62"/><rect x="75" y="58" width="10" height="16" rx="4" class="ink"/></g>';
        } else if (a === 'plunge') {
            over = '<g class="plunger"><rect x="60" y="14" width="40" height="7" rx="2" class="ink"/><path class="o" d="M66 14 L66 -110 M94 14 L94 -110"/><path class="o" d="M52 -86 L108 -86"/></g>';
        } else if (a === 'add') {
            [68, 76, 84, 92, 72, 88].forEach(function (x, i) {
                over += '<circle class="grain bed" cx="' + x + '" cy="' + Math.max(s.top - 22, 2) + '" r="2" style="animation-delay:' + i * 0.15 + 's"/>';
            });
        } else if (a === 'wait') {
            var y = s.press ? 14 : Math.max(s.top - 2, 24);
            over = steam(74, y) + steam(85, y) + steam(96, y);
        }

        return svg(style, '<defs><clipPath id="' + id + '"><path d="' + s.inside + '"/></clipPath>' + mugClip + '</defs>' + mug + drips + body + over + badge);
    }

    function setting(value) {
        try {
            if (value) localStorage.setItem('brew-animation', value);
            return localStorage.getItem('brew-animation');
        } catch (e) { return null; }
    }

    // Returns {update(stepIndex, elapsedSeconds, running)}, or null if this recipe has no animation.
    return function (timer) {
        var raw = timer.getAttribute('data-animation');
        if (!raw) return null;
        var data = JSON.parse(raw);
        var host = document.getElementById('brew-anim');
        var toggle = document.getElementById('brew-anim-toggle');
        var checkbox = document.getElementById('brew-anim-on');
        var enabled = setting() !== 'off';
        var drawn = null, last = { index: -1, elapsed: 0, running: false };

        function draw() {
            var step = data.steps[last.index];
            host.innerHTML = scene(data.shape, step || READY, step ? Math.max(last.elapsed - step.at, 0) : 0);
            drawn = last.index;
        }

        function update(index, elapsed, running) {
            last = { index: index, elapsed: elapsed, running: running };
            if (!enabled) return;
            if (index !== drawn) draw();
            var step = data.steps[index];
            host.classList.toggle('brew-anim-paused', !running && !(step && step.kind === 'done'));
        }

        function apply() {
            host.hidden = !enabled;
            if (enabled) {
                drawn = null;
                update(last.index, last.elapsed, last.running);
            } else {
                host.innerHTML = '';
            }
        }

        toggle.hidden = false;
        checkbox.checked = enabled;
        checkbox.addEventListener('change', function () {
            enabled = checkbox.checked;
            setting(enabled ? 'on' : 'off');
            apply();
        });
        apply();
        return { update: update };
    };
})();
