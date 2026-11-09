"""
Brew mode helpers: turn a recipe's method text into steps with times.

A method can be in the standard step format, which the step editor writes:

    Prep: Add the grounds
    0:00 — Bloom (to 90g)
    0:40 — Pour (to 200g)
    3:30 — Done

or be free text, as all older recipes are. Free text still works: times written
in it ("Swirl at 1:00") are picked out as best we can. suggest_steps() proposes a
conversion from free text to the standard format, for a person to check.

The method is always stored as this text: there is no schema for steps, so the
one-parameter rule, version history and sharing work the same for both.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Recorded as the rationale of the recipe_text change a tidy-up creates
TIDY_RATIONALE = "Tidied into steps"

# m:ss, not part of a longer number or clock time ("12:30:00", "1:234")
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])")
# not times: a brew ratio ("ratio 1:16"), or the end of a range ("3:30–4:00"
# is one target window; only its start becomes a step time)
_NOT_A_TIME_BEFORE = re.compile(r"(ratio\W*(of\W*)?|\d:[0-5]\d\s*[–—-]\s*)$", re.IGNORECASE)

_PREP_LINE = re.compile(r"^Prep:\s*(.+)$")
_STEP_LINE = re.compile(r"^(\d{1,2}:[0-5]\d)\s+[—–-]\s+(.+)$")
_TARGET = re.compile(r"\s*\(to (\d+(?:\.\d+)?)\s*g\)\s*$")


@dataclass
class Step:
    text: str
    times: List[int] = field(default_factory=list)  # seconds from the start, in order
    grams: Optional[float] = None
    is_prep: bool = False


def _seconds(time: str) -> int:
    minutes, seconds = time.split(":")
    return int(minutes) * 60 + int(seconds)


def mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _grams_text(grams: float) -> str:
    return f"{grams:g}"


def _standard_parts(text: Optional[str]) -> Optional[Tuple[str, List[Tuple[str, str, Optional[float]]]]]:
    """(prep, [(time, action, grams)]) if the whole text is in the standard format, else None."""
    prep: List[str] = []
    rows: List[Tuple[str, str, Optional[float]]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        prep_line = _PREP_LINE.match(line)
        if prep_line and not rows:
            prep.append(prep_line.group(1).strip())
            continue
        step_line = _STEP_LINE.match(line)
        if not step_line:
            return None
        target = _TARGET.search(step_line.group(2))
        action = _TARGET.sub("", step_line.group(2)).strip()
        if not action:
            return None
        rows.append((step_line.group(1), action, float(target.group(1)) if target else None))
    return (", ".join(prep), rows) if rows else None


def is_standard(text: Optional[str]) -> bool:
    return _standard_parts(text) is not None


def needs_tidy(text: Optional[str]) -> bool:
    """There is a method, and it isn't in the step format."""
    return bool((text or "").strip()) and not is_standard(text)


def prep_text(text: Optional[str]) -> str:
    parts = _standard_parts(text)
    return parts[0] if parts else ""


def ends_timer(text: Optional[str]) -> bool:
    """A last step called "Done" stops the timer by itself. Only then: drawdowns vary."""
    parts = _standard_parts(text)
    return bool(parts and re.search(r"\bdone\b", parts[1][-1][1], re.IGNORECASE))


def _times_in(text: str) -> List[int]:
    return sorted({
        int(m.group(1)) * 60 + int(m.group(2))
        for m in _TIME.finditer(text)
        if not _NOT_A_TIME_BEFORE.search(text[:m.start()])
    })


def parse_steps(recipe_text: Optional[str]) -> List[Step]:
    """Steps for brew mode: exact for the standard format, best effort for free text."""
    parts = _standard_parts(recipe_text)
    if parts:
        prep, rows = parts
        steps = [Step(text=f"Before you start: {prep}", is_prep=True)] if prep else []
        for time, action, grams in rows:
            target = f" · to {_grams_text(grams)} g" if grams is not None else ""
            steps.append(Step(text=f"{time} — {action}{target}", times=[_seconds(time)], grams=grams))
        return steps

    # One step per non-empty line (textareas submit \r\n), with any m:ss times in it
    steps = []
    for line in (recipe_text or "").splitlines():
        text = line.strip()
        if text:
            steps.append(Step(text=text, times=_times_in(text)))
    return steps


def step_editor_data(text: Optional[str]) -> str:
    """What the step editor needs, as JSON. Free text isn't editable as rows until it's tidied."""
    parts = _standard_parts(text)
    if parts:
        prep, rows = parts
        return json.dumps({"editable": True, "prep": prep, "steps": [
            {"time": time, "action": action, "grams": _grams_text(grams) if grams is not None else ""}
            for time, action, grams in rows
        ]})
    return json.dumps({"editable": not (text or "").strip(), "prep": "", "steps": []})


# --- suggesting steps for free text -------------------------------------------------

_BULLET = re.compile(r"^(?:[•*\-–—]\s*|\d+[.)]\s*)+")
_LEADING_TIME = re.compile(r"^~?(\d{1,2}:[0-5]\d)(?![\da-zA-Z])\s*:?\s*(?:[—–-]\s*)?(.*)$")
_AT_TIMES = re.compile(r"\s*\b(?:at|by)\s+\d{1,2}:[0-5]\d(?:\s*(?:,|and|&)\s*\d{1,2}:[0-5]\d)*", re.IGNORECASE)
_GRAMS_IN_TEXT = re.compile(r"(?:^|\s+)to\s+(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams?)\b", re.IGNORECASE)
_DURATION_HINT = re.compile(r"\bfor\b|\d+\s*s\b|–|—", re.IGNORECASE)
# a pour schedule line: "45g 45s bloom", "Second Pour: 70gms in 45s", "4x 60gm in 30s"
_POUR_GRAMS = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams?)\b", re.IGNORECASE)
_POUR_SECONDS = re.compile(r"(?<![\d.:])(\d+)\s*(?:s|secs?|seconds?)\b", re.IGNORECASE)
_POUR_REPEAT = re.compile(r"^(\d+)\s*x\s*", re.IGNORECASE)
_FOR_TIME = re.compile(r"\s*\bfor\s+(\d{1,2}:[0-5]\d)\b", re.IGNORECASE)


@dataclass
class SuggestedRow:
    time: int
    action: str
    grams: Optional[float] = None
    check: bool = False  # a guess the person should look at


@dataclass
class Suggestion:
    prep: str
    rows: List[SuggestedRow]

    @property
    def text(self) -> str:
        lines = [f"Prep: {self.prep}"] if self.prep else []
        for row in self.rows:
            target = f" (to {_grams_text(row.grams)}g)" if row.grams is not None else ""
            lines.append(f"{mmss(row.time)} — {row.action}{target}")
        return "\n".join(lines)

    @property
    def checks(self) -> List[int]:
        return [i for i, row in enumerate(self.rows) if row.check]


def _clean_action(text: str) -> str:
    action = text.strip(" \t.,;:—–-")
    return action[:1].upper() + action[1:]


def _with_grams(time: int, text: str, check: bool) -> SuggestedRow:
    match = _GRAMS_IN_TEXT.search(text)
    grams = float(match.group(1)) if match else None
    action = _clean_action(_GRAMS_IN_TEXT.sub("", text, count=1) if match else text)
    return SuggestedRow(time=time, action=action or ("Pour" if grams else "Step"), grams=grams, check=check)


def suggest_steps(text: Optional[str]) -> Suggestion:
    """A best-guess conversion to the standard format. Rows marked `check` are guesses."""
    prep: List[str] = []
    rows: List[SuggestedRow] = []
    title_row: Optional[SuggestedRow] = None
    clock: Optional[int] = None  # how far a pour schedule has got, in seconds
    poured = 0.0
    lines = [_BULLET.sub("", raw.strip()).strip() for raw in (text or "").splitlines()]
    lines = [line for line in lines if line and not (line.endswith(":") and not _times_in(line))]  # no headings
    for index, line in enumerate(lines):
        leading = _LEADING_TIME.match(line)
        times = _times_in(line)
        pour_grams, pour_seconds = _POUR_GRAMS.search(line), _POUR_SECONDS.search(line)
        for_time = _FOR_TIME.search(line)

        if pour_grams and pour_seconds and not times and len(line) <= 40:
            # Amounts in these schedules are per pour, so the targets add up
            repeat = _POUR_REPEAT.match(line)
            name = _POUR_SECONDS.sub("", _POUR_GRAMS.sub("", _POUR_REPEAT.sub("", line)))
            name = re.sub(r"\b(?:in|within)\b|[()]", "", name, flags=re.IGNORECASE)
            action = _clean_action(" ".join(name.split())) or "Pour"
            for _ in range(int(repeat.group(1)) if repeat else 1):
                clock = clock or 0
                poured += float(pour_grams.group(1))
                rows.append(SuggestedRow(time=clock, action=action, grams=poured, check=True))
                clock += int(pour_seconds.group(1))
        elif leading and clock is not None:
            # below a pour schedule, "1:00 drawdown" means for that long
            rows.append(SuggestedRow(time=clock, action=_clean_action(leading.group(2)) or "Wait", check=True))
            clock += _seconds(leading.group(1))
        elif for_time and clock is not None:
            action = _FOR_TIME.sub("", line)
            action = re.sub(r"^and\s+", "", action, flags=re.IGNORECASE)
            rows.append(SuggestedRow(time=clock, action=_clean_action(action) or "Wait", check=True))
            clock += _seconds(for_time.group(1))
        elif leading and index == 0 and len(lines) > 1 and _seconds(leading.group(1)) > 0 and leading.group(0)[len(leading.group(1)):].lstrip()[:1] not in "—–-:":
            # "2:30 Immersion, 30s slow plunge" above a list: a title, so it mustn't absorb the list
            title_row = _with_grams(_seconds(leading.group(1)), leading.group(2), check=True)
        elif leading:
            rest = leading.group(2)
            rows.append(_with_grams(_seconds(leading.group(1)), rest, check=bool(_DURATION_HINT.search(rest)) or not rest))
        elif times:
            at_only = _AT_TIMES.search(line) is not None and not _TIME.search(_AT_TIMES.sub("", line))
            action = _AT_TIMES.sub("", line) if at_only else line
            for time in times:
                rows.append(_with_grams(time, action, check=not at_only))
        elif clock is not None:
            rows.append(SuggestedRow(time=clock, action=_clean_action(line), check=True))
        elif rows:
            rows[-1].action = f"{rows[-1].action}, {_clean_action(line)}"
            rows[-1].check = True
        else:
            prep.append(_clean_action(line))

    if title_row:
        rows.append(title_row)
    if not rows and prep:
        # nothing was timed: the last instruction is what starts the brew
        rows.append(SuggestedRow(time=0, action=prep.pop(), check=True))
    rows.sort(key=lambda row: row.time)
    return Suggestion(prep=", ".join(prep), rows=rows)
