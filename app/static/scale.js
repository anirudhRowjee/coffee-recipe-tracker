// A Bookoo scale (Themis Mini / Ultra) in brew mode, over Web Bluetooth: the live
// weight against the current step's "to 200g" (with a chirp when it's reached), a Tare
// button, the brew timer starting when the scale's own does, and the weight kept when
// the brewer is lifted off before Stop. Only where navigator.bluetooth
// exists (Chrome, Edge, Android Chrome, Bluefy); everywhere else nothing shows.
//
// Protocol: Bookoo's published notes (github.com/BooKooCode/OpenSource, mini and
// ultra scale). Service 0x0FFE; 0xFF11 notifies 20-byte weight packets, 0xFF12 takes
// 6-byte commands; automatic-mode events are 03 0D <state>. Every packet ends in the
// XOR of the bytes before it. ES5 so an old browser can't trip over the syntax.
//
// The Ultra ignores timer commands outside timing and ratio mode, and tare while an
// automatic brew runs or is done, or while charging; an ignored command gets no reply.
(function () {
    var timer = document.getElementById('brew-timer');
    if (!timer || !navigator.bluetooth || !window.isSecureContext) return;

    // 0x0FFE, 0xFF11, 0xFF12 written out in full: Chrome takes the short numbers, but
    // iOS Bluetooth browsers such as Bluefy may only take the full form
    var SERVICE = '00000ffe-0000-1000-8000-00805f9b34fb',
        WEIGHT = '0000ff11-0000-1000-8000-00805f9b34fb',
        COMMAND = '0000ff12-0000-1000-8000-00805f9b34fb';
    // 03 0A <command> 00 00, then the checksum (send adds it)
    var COMMANDS = { tare: 0x01, start: 0x04, stop: 0x05, reset: 0x06, tareAndStart: 0x07 };
    var EVENT_STOPPED = 0x00, EVENT_STARTED = 0x01;
    var CLOSE_G = 2;  // within this of the target counts as there
    // Lifting the brewer off before Stop drops the reading by its whole weight (often
    // below zero). Nothing else in a brew makes the weight fall: water stays on the
    // scale. So a reading held this far below the brew's highest for a second means the
    // brewer is off: keep the last real weight, and stop recording until it's back.
    var LIFT_G = 50, LIFT_MS = 1000;

    var panel = document.getElementById('brew-scale');
    var weightBox = document.getElementById('brew-scale-weight');
    var targetBox = document.getElementById('brew-scale-target');
    var fill = document.getElementById('brew-scale-fill');
    var connectBtn = document.getElementById('brew-scale-connect');
    var tareBtn = document.getElementById('brew-scale-tare');
    var startBtn = document.getElementById('brew-start');
    var resetBtn = document.getElementById('brew-reset');
    var note = document.getElementById('brew-scale-note');
    var fromScale = false;  // the scale started or stopped the brew, so don't echo it back
    var device = null, command = null, grams = null;

    connectBtn.hidden = false;

    // 20 bytes: 03 0B, ms(3), unit, sign, grams×100 (3), sign, flow×100 (2), battery, ..., XOR checksum
    function decode(b) {
        if (b.length !== 20 || b[0] !== 0x03 || b[1] !== 0x0b) return null;
        var x = 0;
        for (var i = 0; i < 19; i++) x ^= b[i];
        if (x !== b[19]) return null;
        return {
            grams: (b[6] === 0x2d ? -1 : 1) * ((b[7] << 16) | (b[8] << 8) | b[9]) / 100,
            flow: (b[10] === 0x2d ? -1 : 1) * ((b[11] << 8) | b[12]) / 100,
            ms: (b[2] << 16) | (b[3] << 8) | b[4]  // the scale's own timer
        };
    }

    // The brew's readings, for the graphs after Stop: [seconds on the brew clock, grams, g/s].
    // Our own clock, counted only while the timer runs, so a pause doesn't leave a gap.
    var samples = [], banked = 0, runSince = null, wasRunning = false;
    // The scale's timer, read from every weight packet: when it starts counting (its
    // button, or its auto-start) the app's timer starts too, and when it stops the app
    // stops, but only if the scale's timer ran during this run of the app's: a scale
    // that ignored our Resume shouldn't stop the brew a moment later.
    var STILL_MS = 1500;  // no tick for this long: the scale's timer has stopped
    var scaleMs = null, scaleTickAt = 0, scaleTiming = false, scaleRanThisRun = false;
    var scaleSeenStill = false;  // a timer already running when we connect isn't a start
    function followScaleTimer(ms) {
        var now = Date.now(), label = startBtn.textContent;
        if (scaleMs !== null && ms > scaleMs) {
            scaleTickAt = now;
            if (!scaleTiming) {
                scaleTiming = true;
                if ((label === 'Start' || label === 'Cancel') && scaleSeenStill) startNow();
            }
            if (running()) scaleRanThisRun = true;
        } else if (scaleMs !== null && ms === scaleMs && !scaleTiming) {
            scaleSeenStill = true;
        } else if (scaleTiming && now - scaleTickAt > STILL_MS) {
            scaleTiming = false;
            if (running() && scaleRanThisRun) press();
        }
        scaleMs = ms;
    }
    function press() {  // the timer button, without telling the scale what it just did
        fromScale = true;
        startBtn.click();
        fromScale = false;
    }
    // The scale started the brew, so the app starts now: no countdown (it may already be
    // counting one down: you poured early), and nothing sent back to the scale.
    function startNow() {
        scaleRanThisRun = false;
        if (window.brewTimerStartNow) window.brewTimerStartNow();
    }
    // The countdown reached "go": Bookoo's recommended start, tare and start together
    // (it also starts a ready automatic-mode brew).
    window.brewScaleGo = function () { send('tareAndStart'); };

    var recent = [], top = null, dropAt = null, lifted = null;  // lifted: the weight kept
    function median(list) {
        var v = list.map(function (r) { return r[1]; }).sort(function (a, b) { return a - b; });
        return v[Math.floor((v.length - 1) / 2)];  // the lower middle: a short spike never wins
    }
    function clearLift() { recent = []; top = null; dropAt = null; lifted = null; say(''); }
    // true while the brewer is off the scale (see LIFT_G)
    function liftedNow(g) {
        if (!running()) return lifted !== null;
        var now = Date.now();
        recent.push([now, g]);
        while (recent.length && now - recent[0][0] > 1000) recent.shift();
        var level = median(recent);  // a spoon pressing on the bed for under half a second doesn't count
        if (lifted !== null) {
            if (level < lifted - LIFT_G) return true;
            lifted = null; top = level; say('');  // it's back
        }
        if (top === null || level > top) top = level;
        if (level >= top - LIFT_G) { dropAt = null; return false; }
        if (dropAt === null) dropAt = now;
        if (now - dropAt < LIFT_MS) return false;
        // off: forget the readings from the fall itself, and keep the last real weight
        while (samples.length && samples[samples.length - 1][1] < top - LIFT_G) samples.pop();
        lifted = samples.length ? samples[samples.length - 1][1] : top;
        say('Brewer off the scale: keeping ' + lifted.toFixed(1) + ' g');
        return true;
    }
    function weight() { return lifted !== null ? lifted : grams; }

    function brewSeconds() { return banked + (runSince === null ? 0 : (Date.now() - runSince) / 1000); }

    function track() {
        var now = running();
        if (now && runSince === null) runSince = Date.now();
        if (!now && runSince !== null) { banked = brewSeconds(); runSince = null; }
        if (wasRunning && !now && samples.length > 1) {
            if (window.BrewGraphs) window.BrewGraphs.show(samples, stepTargets());
            keepForLog();
        }
        wasRunning = now;
    }

    // Two readings a second go into the log form, so the graphs are saved with the brew
    // (crud.parse_curve checks them). Resuming and stopping again replaces them.
    function keepForLog() {
        var field = document.getElementById('log-curve');
        if (!field) return;
        var t = [], g = [], f = [], last = -1;
        samples.forEach(function (s, i) {
            if (s[0] - last < 0.5 && i < samples.length - 1) return;
            last = s[0];
            t.push(s[0]); g.push(Math.round(s[1] * 10) / 10); f.push(Math.round(s[2] * 100) / 100);
        });
        field.value = JSON.stringify({ t: t, g: g, f: f });
    }

    // [seconds, grams] for every step with a target, in time order
    function stepTargets() {
        var out = [];
        Array.prototype.forEach.call(document.querySelectorAll('.brew-steps li[data-grams]'), function (li) {
            var t = parseInt(li.getAttribute('data-times'), 10);
            if (!isNaN(t)) out.push([t, parseFloat(li.getAttribute('data-grams'))]);
        });
        return out.sort(function (a, b) { return a[0] - b[0]; });
    }

    // The step whose target is in force: the current one, or the last before it with
    // a target (a swirl or drawdown still means "you should be at 500 g"); before the
    // brew starts, the first step with one.
    function targetStep() {
        for (var li = document.querySelector('.brew-steps li.brew-step-now'); li; li = li.previousElementSibling) {
            if (li.getAttribute('data-grams')) return li;
        }
        return document.querySelector('.brew-steps li[data-grams]');
    }

    function running() { return startBtn.textContent === 'Stop'; }

    function show() {
        if (grams === null) return;
        var w = weight();
        weightBox.textContent = w.toFixed(1);
        var li = targetStep(), t = li ? parseFloat(li.getAttribute('data-grams')) : null;
        // Reaching the weight ticks the step off; the clock still decides when the next
        // one starts, since the method's times are part of the recipe. Only while the
        // timer runs: before Start the scale may still be weighing beans or the brewer.
        // (An attribute, not a class: the timer script resets classes four times a second.)
        if (li && running() && w >= t - CLOSE_G && !li.hasAttribute('data-reached')) {
            li.setAttribute('data-reached', '');
            if (window.brewBeep) window.brewBeep('reached');  // not the new-step beep
        }
        var reached = li && li.hasAttribute('data-reached');
        targetBox.textContent = t ? (reached ? ' ✓ ' : ' → ') + (t % 1 ? t.toFixed(1) : t) + ' g' : '';
        fill.style.width = (t ? Math.max(0, Math.min(1, w / t)) * 100 : 0).toFixed(1) + '%';
        panel.className = 'brew-scale' + (t && w > t + CLOSE_G ? ' over-target' : reached ? ' at-target' : '');
    }

    function say(text) { note.textContent = text; note.hidden = !text; }

    function send(name) {
        if (!command) return;
        var data = new Uint8Array([0x03, 0x0a, COMMANDS[name], 0x00, 0x00, 0]);
        data[5] = data[0] ^ data[1] ^ data[2] ^ data[3] ^ data[4];
        var props = command.properties || {};
        // write with a response when the scale offers it, so a failure shows up here
        var write = props.write && command.writeValueWithResponse ? command.writeValueWithResponse(data)
                  : command.writeValueWithoutResponse ? command.writeValueWithoutResponse(data)
                  : command.writeValue(data);
        write.then(function () { say(''); }, function (err) {
            say('The scale didn’t take “' + name + '”: ' + (err && err.message || err));
        });
    }

    // 03 0D <state> …: the scale's automatic mode started or stopped a brew
    function onEvent(b) {
        if (b.length < 3 || b[0] !== 0x03 || b[1] !== 0x0d) return;
        var label = startBtn.textContent;
        if (b[2] === EVENT_STARTED && (label === 'Start' || label === 'Cancel')) startNow();
        if (b[2] === EVENT_STOPPED && label === 'Stop') press();
    }

    function connected(on) {
        panel.hidden = !on;
        connectBtn.hidden = on;
        tareBtn.hidden = !on;
        if (!on) { command = null; grams = null; }
    }

    function bytes(view) { return new Uint8Array(view.buffer, view.byteOffset, view.byteLength); }

    connectBtn.addEventListener('click', function () {
        connectBtn.disabled = true;
        connectBtn.textContent = 'Connecting…';
        var stage = 'choosing the scale';  // named in the error, since some browsers give no message
        function isCancel(err) {
            var text = err && (err.message || (typeof err === 'string' ? err : ''));
            return (err && err.name === 'NotFoundError') || /cancel/i.test(text || '');
        }
        navigator.bluetooth.requestDevice({
            filters: [{ namePrefix: 'BOOKOO' }, { namePrefix: 'Bookoo' }, { services: [SERVICE] }],
            optionalServices: [SERVICE]
        })['catch'](function (err) {
            // a browser that can't take these filters (Bluefy answered just "2"): list
            // every nearby device instead, and the scale is the one called BOOKOO…
            if (isCancel(err)) throw err;
            return navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: [SERVICE] });
        }).then(function (d) {
            device = d;
            stage = 'connecting';
            device.addEventListener('gattserverdisconnected', function () { connected(false); });
            return device.gatt.connect();
        }).then(function (server) {
            stage = 'finding the scale’s service';
            return server.getPrimaryService(SERVICE);
        }).then(function (service) {
            stage = 'finding the weight and command channels';
            return Promise.all([service.getCharacteristic(WEIGHT), service.getCharacteristic(COMMAND)]);
        }).then(function (chars) {
            stage = 'starting the weight readings';
            command = chars[1];
            // the notes don't say which characteristic carries events, so listen on both
            chars[0].addEventListener('characteristicvaluechanged', function (e) {
                var b = bytes(e.target.value), g = decode(b);
                if (g === null) { onEvent(b); return; }
                grams = g.grams;
                followScaleTimer(g.ms);
                track();
                if (running() && !liftedNow(g.grams)) samples.push([Math.round(brewSeconds() * 10) / 10, g.grams, g.flow]);
                show();
            });
            command.addEventListener('characteristicvaluechanged', function (e) { onEvent(bytes(e.target.value)); });
            // one at a time: Chrome refuses a second GATT operation while one is running
            return chars[0].startNotifications().then(function () {
                if (command.properties && !command.properties.notify) return null;
                return command.startNotifications()['catch'](function () { /* events are a bonus */ });
            });
        }).then(function () {
            say('');
            connected(true);
        })['catch'](function (err) {
            try { if (device && device.gatt.connected) device.gatt.disconnect(); } catch (e) { /* already gone */ }
            connected(false);
            // Chrome rejects with an Error; Bluefy may reject with a bare string or object
            var name = err && err.name, text = err && (err.message || (typeof err === 'string' ? err : ''));
            if (!text && err) { try { text = JSON.stringify(err); } catch (e) { text = String(err); } }
            if (!isCancel(err)) {
                window.alert('Could not connect to the scale while ' + stage + ': ' +
                    (name && name !== 'Error' ? name + ': ' : '') + (text || String(err)) +
                    '\n\nIf it isn’t listed: close the Bookoo app (on every phone or tablet nearby) and wake the scale.');
            }
        }).then(function () {
            connectBtn.disabled = false;
            connectBtn.textContent = 'Scale';
        });
    });

    tareBtn.addEventListener('click', function () { clearLift(); send('tare'); });

    // The scale's own timer follows the app's. This listener runs before the timer
    // script's (this file loads first), so the label is still the one that was pressed.
    // Start from zero only begins the countdown: the scale tares and starts at "go"
    // (brewScaleGo), and Cancel sends nothing. Resume doesn't tare.
    startBtn.addEventListener('click', function () {
        var label = startBtn.textContent;
        if (label !== 'Stop') scaleRanThisRun = false;  // a new run of the app's timer
        if (fromScale || label === 'Start' || label === 'Cancel') return;
        send(label === 'Stop' ? 'stop' : 'start');
    });
    resetBtn.addEventListener('click', function () {
        samples = []; banked = 0; runSince = null;
        clearLift();
        var field = document.getElementById('log-curve');
        if (field) field.value = '';
        if (window.BrewGraphs) window.BrewGraphs.hide();
        send('reset');
        Array.prototype.forEach.call(document.querySelectorAll('.brew-steps li[data-reached]'), function (li) {
            li.removeAttribute('data-reached');
        });
    });

    // the step changes with the clock, not with the scale, so keep the target in step
    setInterval(function () { track(); show(); }, 500);

    window.brewScaleGrams = function () { return grams === null ? '' : Math.round(weight()) + ' g'; };
})();
