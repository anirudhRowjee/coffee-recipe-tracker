// Change gear (partials/latest_recipe.html): pick a brewer and a grinder, then only this
// coffee's recipes for that pair show, to switch to or plan. No pair with recipes: offer to start one.
(function () {
    function update(sheet) {
        var pick = {};
        sheet.querySelectorAll('.gear-pick').forEach(function (group) {
            var on = group.querySelector('[aria-pressed="true"]');
            pick[group.getAttribute('data-kind')] = on ? on.getAttribute('data-id') : '';
        });
        var shown = 0;
        sheet.querySelectorAll('.gear-recipe').forEach(function (row) {
            var match = row.getAttribute('data-brewer') === pick.brewer && row.getAttribute('data-grinder') === pick.grinder;
            row.hidden = !match;
            if (match) shown += 1;
        });
        sheet.querySelector('.gear-recipes').hidden = !shown;
        sheet.querySelector('.gear-none').hidden = !!shown;
        sheet.querySelector('.gear-start').href = '/?bag_id=' + sheet.getAttribute('data-bag') +
            '&brewer_id=' + pick.brewer + '&grinder_id=' + pick.grinder;
    }
    document.addEventListener('click', function (e) {
        var chip = e.target.closest('.gear-pick .chip');
        if (!chip) return;
        chip.parentNode.querySelectorAll('.chip').forEach(function (c) { c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'); });
        update(chip.closest('.gear-sheet'));
    });
    document.querySelectorAll('.gear-sheet').forEach(update);
})();
