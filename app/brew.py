"""
Brew mode helpers: turn a recipe's free-text method into steps, and pick out
the times written in them ("Swirl at 1:00 and 2:00", "Release at 3:00") so the
brew-mode timer can say what's next. No schema: the method stays free text
and the one-parameter rule is untouched.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

# m:ss, not part of a longer number or clock time ("12:30:00", "1:234")
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])")
# not times: a brew ratio ("ratio 1:16"), or the end of a range ("3:30–4:00"
# is one target window; only its start becomes a step time)
_NOT_A_TIME_BEFORE = re.compile(r"(ratio\W*(of\W*)?|\d:[0-5]\d\s*[–—-]\s*)$", re.IGNORECASE)


@dataclass
class Step:
    text: str
    times: List[int] = field(default_factory=list)  # seconds from the start, in order


def parse_steps(recipe_text: Optional[str]) -> List[Step]:
    """One step per non-empty line (textareas submit \\r\\n), with any m:ss times in it."""
    steps = []
    for line in (recipe_text or "").splitlines():
        text = line.strip()
        if text:
            times = sorted({
                int(m.group(1)) * 60 + int(m.group(2))
                for m in _TIME.finditer(text)
                if not _NOT_A_TIME_BEFORE.search(text[:m.start()])
            })
            steps.append(Step(text=text, times=times))
    return steps


def mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"
