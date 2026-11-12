"""The words behind every "?" button, in one place so they're easy to read and change.

Two sentences at most each. `tip('grind')` in a template (partials/tip.html)
draws the button and its popover.
"""

TIPS = {
    "up_next": "The coffee you'll brew next. Change the coffee or gear from the picker; your choice is remembered for this coffee.",
    "start": "Opens a timer that walks you through each pour and beeps at every step. Rate the cup when you press Stop.",
    "next_time": "A note you left after your last cup. Try a change starts from it, with only that one thing changed.",
    "one_change": "If you change two things and the cup gets better, you can't tell which one helped. One change per version keeps every lesson clear.",
    "log_next_time": "A note to future you. It shows above Start until you brew this recipe again. Leave it as \"same again\" if you'd brew it the same way.",
    "grind": "The number on your grinder's dial. It only means something on that grinder, so recipes are kept per grinder.",
    "ratio": "Grams of water for every gram of coffee. A bigger number makes a lighter cup.",
    "version": "Each change you save makes a new version. Older versions and their cups stay in the history.",
    "recipes": "Keep separate recipes for the same coffee and gear, say one cup and two. Each has its own versions and history.",
    "plan": "Puts this coffee and recipe at the top of Brew next time you open the app, on any device.",
    "rating": "Only you see it. It's never on a shared recipe unless you choose to show it.",
    "log": "Logging takes the coffee's dose out of the bag, so the grams left stay right.",
    "scale": "Connect a Bookoo scale to see the weight against each step's target. Works in Bluefy and Chrome.",
    "pour_to": "What the scale should read at the end of this step, counting everything poured so far.",
    "tidy": "Turns a written method into timed steps, so brew mode can time and beep each one. Your old text stays as the previous version.",
    "share": "Makes a picture or text of this recipe for friends. Your tasting notes, ratings and bags stay private.",
    "frozen": "Frozen bags stay out of the picker until you thaw them.",
    "low_stock": "The bag shows as low when fewer grams than this are left.",
    "graph": "Weight and flow from the scale, over your previous cup of this recipe, so you can see what changed.",
    "savings": "Each cup you log counts as one café cup (₹300) you didn't buy.",
    "streak": "Days in a row with at least one cup logged, in India time.",
    "flavour": "What the roaster says it tastes like. It shows on the coffee's card and helps you name what you taste.",
    "roast_date": "Coffee is usually best one to four weeks after roasting. With the date, you can see each bag's age.",
    "brewer_type": "Picking a type tells brew mode which brewer to draw. You can still name it anything.",
    "cooled": "Coffee tastes different as it cools. Add how it tastes now; your first impression stays.",
}
