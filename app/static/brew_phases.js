// What was happening at each moment of a brew, from the scale's readings: pouring, a
// valve flick (the Hario Switch's lever, or any press on the brewer: a spike that comes
// straight back to the same weight), or the brewer off the scale. Used by the graphs
// (static/brew_graphs.js, in brew mode and on a logged brew's page) and the share card,
// so a flick never shows as 200 g/s of "flow". ES5, and plain enough to run under node
// for tests/test_brew_phases.py.
//
// BrewPhases.classify(samples) takes [[seconds, grams, g/s], …] and returns
//   { samples: the readings with valve spikes smoothed out (and anything after the
//               brewer came off the scale for good dropped),
//     phases:  [{kind: 'pour' | 'valve' | 'off', from: s, to: s}, …] in time order,
//     pours, valves: counts }
(function (root) {
    var SPIKE_G = 8;        // a flick moves the reading at least this far…
    var SPIKE_MAX_S = 1.6;  // …for no longer than this…
    var BACK_G = 4;         // …and comes back to within this of where it was
    var REF_S = 2;          // the "where it was" and "where it went" windows
    var POUR_GS = 1.5;      // pouring: the cleaned weight rising faster than this
    var POUR_MIN_S = 1.5, POUR_MIN_G = 4, POUR_GAP_S = 2;
    var OFF_G = 50;         // brewer off: this far below the brew's highest, to the end
    var JUMP_GS = 40;       // …or a jump faster than any kettle pours (g/s)

    function median(xs) {
        if (!xs.length) return null;
        var v = xs.slice().sort(function (a, b) { return a - b; });
        return v[Math.floor((v.length - 1) / 2)];
    }
    function within(samples, from, to) {  // weights of samples with from <= t < to
        var out = [];
        for (var i = 0; i < samples.length; i++) {
            var t = samples[i][0];
            if (t >= from && t < to) out.push(samples[i][1]);
            else if (t >= to) break;
        }
        return out;
    }
    // slope of the weight over about a second around each reading (g/s)
    function slopeAt(samples, i) {
        var a = i, b = i, t = samples[i][0];
        while (a > 0 && t - samples[a - 1][0] <= 0.6) a--;
        while (b < samples.length - 1 && samples[b + 1][0] - t <= 0.6) b++;
        var dt = samples[b][0] - samples[a][0];
        return dt > 0 ? (samples[b][1] - samples[a][1]) / dt : 0;
    }

    function classify(input) {
        var samples = input.map(function (s) { return [s[0], s[1], s[2]]; });
        var phases = [], valves = 0, n = samples.length;
        if (n < 3) return { samples: samples, phases: [], pours: 0, valves: 0 };

        // 1. valve flicks: a short run away from the level just before, coming back to it
        for (var i = 1; i < n; i++) {
            var t0 = samples[i][0];
            var before = median(within(samples, t0 - REF_S, t0));
            if (before === null || Math.abs(samples[i][1] - before) <= SPIKE_G) continue;
            if (Math.abs(samples[i - 1][1] - before) > SPIKE_G) continue;  // it must start from a steady level, not partway through a press
            var k = i;
            while (k < n && Math.abs(samples[k][1] - before) > SPIKE_G && samples[k][0] - t0 <= SPIKE_MAX_S) k++;
            if (k >= n || Math.abs(samples[k][1] - before) > SPIKE_G) continue;  // never came back: a pour, or the brewer off
            var after = median(within(samples, samples[k][0], samples[k][0] + REF_S));
            if (after === null || Math.abs(after - before) > BACK_G) continue;
            var t1 = samples[k - 1][0];
            for (var j = i; j < k; j++) samples[j][1] = before;
            // the scale's own flow swings both ways around a flick, starting a reading early:
            // flat from a second before it to a second after
            for (j = i; j > 0 && samples[j - 1][0] >= t0 - 1; j--) samples[j - 1][2] = 0;
            for (j = i; j < n && samples[j][0] <= t1 + 1; j++) samples[j][2] = 0;
            phases.push({ kind: 'valve', from: t0, to: t1 });
            valves++;
            i = k;
        }

        // 2. the brewer off the scale for good, or something set on it, at the end: a jump
        //    (faster than any kettle) or a fall far below the brew's highest that never comes
        //    back. Those readings are dropped, from where the wobble before it began.
        var top = -Infinity, offAt = -1;
        for (i = 1; i < n && offAt < 0; i++) {
            top = Math.max(top, samples[i - 1][1]);
            var dt = samples[i][0] - samples[i - 1][0] || 0.1;
            var jump = Math.abs(samples[i][1] - samples[i - 1][1]) / dt > JUMP_GS || samples[i][1] < top - OFF_G;
            if (!jump) continue;
            var back = false, level = samples[i - 1][1];
            for (j = i + 1; j < n && !back; j++) back = Math.abs(samples[j][1] - level) <= BACK_G;
            if (!back) offAt = i;
        }
        if (offAt > 0) {
            var steady = median(within(samples, samples[offAt][0] - 5, samples[offAt][0] - 2));
            while (offAt > 1 && steady !== null && Math.abs(samples[offAt - 1][1] - steady) > 3 &&
                   samples[offAt][0] - samples[offAt - 1][0] < 3) offAt--;
            phases.push({ kind: 'off', from: samples[offAt][0], to: samples[n - 1][0] });
            samples = samples.slice(0, offAt);
            // and the scale's flow as the brewer was picked up isn't a pour
            for (j = samples.length - 1; j >= 0 && samples[j][0] >= samples[samples.length - 1][0] - 1.5; j--) samples[j][2] = Math.min(samples[j][2], 0.5);
            n = samples.length;
        }

        // 3. the scale's flow where the weight doesn't bear it out (a small knock, under the
        //    spike size, still swings the scale's own flow reading): the weight's slope wins
        for (i = 0; i < n; i++) {
            if (samples[i][2] <= 15 && samples[i][2] >= -3) continue;  // nothing pours out of a scale: a negative flow is always a knock
            if (samples[i][2] < -3) { samples[i][2] = 0; continue; }  // brewer and cup both sit on the scale: weight only ever comes in
            var slope = slopeAt(samples, i);
            if (Math.abs(slope) < Math.abs(samples[i][2]) / 2) samples[i][2] = Math.round(slope * 100) / 100;
        }

        // 4. pours: the cleaned weight climbing, gaps under two seconds joined up
        var runs = [], start = -1;
        for (i = 0; i < n; i++) {
            var rising = slopeAt(samples, i) > POUR_GS;
            if (rising && start < 0) start = i;
            if ((!rising || i === n - 1) && start >= 0) { runs.push([start, rising ? i : i - 1]); start = -1; }
        }
        var pours = [];
        runs.forEach(function (r) {
            var last = pours[pours.length - 1];
            if (last && samples[r[0]][0] - samples[last[1]][0] <= POUR_GAP_S) last[1] = r[1];
            else pours.push([r[0], r[1]]);
        });
        pours = pours.filter(function (p) {
            return samples[p[1]][0] - samples[p[0]][0] >= POUR_MIN_S && samples[p[1]][1] - samples[p[0]][1] >= POUR_MIN_G;
        });
        pours.forEach(function (p) { phases.push({ kind: 'pour', from: samples[p[0]][0], to: samples[p[1]][0] }); });

        phases.sort(function (a, b) { return a.from - b.from; });
        return { samples: samples, phases: phases, pours: pours.length, valves: valves };
    }

    root.BrewPhases = { classify: classify };
    if (typeof module !== 'undefined' && module.exports) module.exports = root.BrewPhases;
})(typeof window !== 'undefined' ? window : this);
