"""Trivia plugin for FiestaBoard.

Shows a multiple-choice question from the Open Trivia Database, then reveals
the correct answer on the next refresh.
"""

import logging
import random
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import requests

from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

API_URL = "https://opentdb.com/api.php"
USER_AGENT = "FiestaBoard (https://github.com/FiestaBoard/FiestaBoard)"
LETTERS = "ABCD"
DIFFICULTIES = ("any", "easy", "medium", "hard")

# The plugin's original design baseline (a Flagship). Boards no taller than
# this keep the plugin's original compact layout (paired choices); a board
# taller than this has rows to spare, which are spent on one choice per line
# instead of blank padding -- see _choice_lines().
FLAGSHIP_ROWS = 6

# Note width (15 cols) -- the narrowest board any FiestaBoard supports.
# Template variables are placed by the user into their own page layout, so a
# value must fit the narrowest board regardless of which board the question
# happened to be fetched for. Matches the manifest's declared max_length for
# these fields (see manifest.json).
VARIABLE_MAX_LENGTH = 15


def _wrap(text: str, width: int, max_lines: int) -> List[str]:
    """Word-wrap *text* into at most *max_lines* lines of *width* chars.

    Words longer than *width* are cut. If the text does not fit, the last
    line is truncated and ends with "...".
    """
    lines: List[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)

    lines = [line[:width] for line in lines]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width - 3].rstrip() + "..."
    return lines


def _clip(text: str, width: int) -> str:
    """Truncate *text* to at most *width* characters, adding an ellipsis.

    Unlike a bare slice (``text[:width]``), truncation is never silent: a
    cut string always ends with "...", the same signal ``_wrap`` gives a
    question that doesn't fit.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3].rstrip() + "..."


def _question_budget(body_rows: int, choice_rows: int) -> int:
    """How many lines the question may use.

    Whatever is left of the board after the choices (the caller separately
    reserves a row for the answer when revealed) -- not a fixed cap, so a
    taller board lets a long question spread out instead of always being cut
    to the same handful of lines regardless of how much room exists.
    """
    return max(1, body_rows - choice_rows)


def _pack_choices(labelled: List[str], cols: int) -> str:
    """All four choices squeezed onto a single row.

    Last resort for a board too tight even for a two-line pairing (e.g. a
    Note showing the revealed answer, which leaves only two body rows for
    the question and the choices combined).
    """
    per_item = max(1, (cols - (len(labelled) - 1)) // len(labelled))
    packed = " ".join(_clip(item, per_item) for item in labelled)
    return _clip(packed, cols)


def _choice_lines(data: Dict[str, Any], cols: int, rows: int, choice_row_budget: int) -> List[str]:
    """Lay out the four labelled choices within *choice_row_budget* rows.

    - A board taller than the Flagship baseline (``rows > FLAGSHIP_ROWS``)
      with room to spare spends it on one choice per line, rather than
      leaving those extra rows blank.
    - Otherwise, choices pair two-per-line where a pair's text fits the
      width; a pair that doesn't gets its own two lines when the budget can
      afford it, or is squeezed (with an ellipsis, never a silent cut) onto
      one line when it can't.
    - A budget too tight even for a two-line pairing packs everything onto
      the single row available.

    Every branch is bounded by *choice_row_budget* by construction, so the
    caller never has to truncate the result to fit.
    """
    labelled = [f"{letter} {data[f'choice_{letter.lower()}']}" for letter in LETTERS]

    if choice_row_budget >= len(labelled) and rows > FLAGSHIP_ROWS:
        return [_clip(line, cols) for line in labelled]

    if choice_row_budget >= 2:
        half = cols // 2
        pairs = list(zip(labelled[0::2], labelled[1::2]))
        lines: List[str] = []
        remaining_budget = choice_row_budget
        for index, (left, right) in enumerate(pairs):
            pairs_left_after = len(pairs) - index - 1
            if len(left) < half and len(right) <= cols - half:
                lines.append(left.ljust(half) + right)
                remaining_budget -= 1
            elif remaining_budget - 2 >= pairs_left_after:
                lines.append(_clip(left, cols))
                lines.append(_clip(right, cols))
                remaining_budget -= 2
            else:
                lines.append(_clip(left, half - 1).ljust(half) + _clip(right, cols - half))
                remaining_budget -= 1
        return lines

    return [_pack_choices(labelled, cols)]


class TriviaPlugin(PluginBase):
    """Trivia plugin.

    Two-phase state machine driven by the refresh interval:
    "question" shows the question and four choices; the next refresh flips
    to "answer" (same question, correct answer revealed); the refresh after
    that fetches a new question.

    The platform holds ONE instance of this plugin per plugin id and renders
    it for every board the user owns, so the phase state above is keyed by
    board geometry (:meth:`_state_key`) -- otherwise a cache miss triggered
    by rendering one board would silently advance or skip the
    question -> answer -> new-question cycle for every other board too.
    """

    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self._states: Dict[str, Dict[str, Any]] = {}

    @property
    def plugin_id(self) -> str:
        return "trivia"

    def _state_key(self) -> str:
        """Per-geometry key for the question/reveal state machine.

        Mirrors ``PluginBase._cache_key``. Flagship and Note have fixed sizes,
        so their device_type is a sufficient key. Every other family varies in
        size under one device_type -- note arrays, and LED/TV boards, which
        are all "panel" -- so the dimensions are folded in: otherwise a 16x10
        Pixoo and a 22x9 TV panel share one entry, and a board whose grid
        changes at runtime (a larger text size) is served output laid out for
        its old size. Two boards of one size can still draw differently
        (split-flap vs LED), so the display's key is appended when core
        provides one; ``getattr`` keeps this working on cores whose
        BoardContext has no ``display``. An unbound board (legacy callers,
        unit tests) falls back to one default key.
        """
        board = self.board
        if board is None:
            return "_default"
        if board.device_type in ("flagship", "note"):
            key = board.device_type
        else:
            key = f"{board.device_type}:{board.cols}x{board.rows}"
        display = getattr(board, "display", None)
        display_key = getattr(display, "key", None)
        return f"{key}|{display_key}" if display_key else key

    def fetch_data(self) -> PluginResult:
        """Advance this board's question/answer state machine and return its data."""
        try:
            state = self._states.setdefault(self._state_key(), {"question": None, "revealed": False})
            if state["question"] is None or state["revealed"]:
                state["question"] = self._fetch_question()
                state["revealed"] = False
            else:
                state["revealed"] = True

            data = self._build_data(state)
            rows = self.board.rows if self.board else FLAGSHIP_ROWS
            cols = self.board.cols if self.board else 22
            formatted_lines = self._format_lines(data, rows, cols)
            return PluginResult(available=True, data=data, formatted_lines=formatted_lines)
        except Exception as e:
            logger.exception("Error fetching trivia question")
            return PluginResult(available=False, error=str(e))

    def _fetch_question(self) -> Dict[str, Any]:
        """Fetch one multiple-choice question from OpenTDB (raises on failure)."""
        params: Dict[str, Any] = {"amount": 1, "type": "multiple", "encode": "url3986"}
        difficulty = self.config.get("difficulty", "any")
        if difficulty in DIFFICULTIES and difficulty != "any":
            params["difficulty"] = difficulty
        category = int(self.config.get("category", 0) or 0)
        if category > 0:
            params["category"] = category

        response = requests.get(
            API_URL,
            params=params,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()

        code = body.get("response_code")
        if code != 0:
            raise ValueError(f"OpenTDB returned response_code {code}")
        results = body.get("results") or []
        if not results:
            raise ValueError("No question returned from API")

        item = results[0]
        correct = unquote(item["correct_answer"])
        choices = [correct] + [unquote(a) for a in item.get("incorrect_answers", [])]
        random.shuffle(choices)

        return {
            "question": unquote(item["question"]),
            "choices": choices,
            "answer": correct,
            "answer_letter": LETTERS[choices.index(correct)],
            "category": unquote(item.get("category", "")),
            "difficulty": unquote(item.get("difficulty", "")),
        }

    def _build_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        q = state["question"]
        revealed = state["revealed"]
        choices = q["choices"]
        data: Dict[str, Any] = {"question": q["question"]}
        for i, letter in enumerate(LETTERS):
            raw = choices[i] if i < len(choices) else ""
            data[f"choice_{letter.lower()}"] = _clip(raw, VARIABLE_MAX_LENGTH)
        data.update(
            {
                "answer": _clip(q["answer"], VARIABLE_MAX_LENGTH) if revealed else "",
                "answer_letter": q["answer_letter"] if revealed else "",
                "phase": "answer" if revealed else "question",
                "category": _clip(q["category"], VARIABLE_MAX_LENGTH),
                "difficulty": q["difficulty"],
                "is_revealed": revealed,
            }
        )
        return data

    def _format_lines(self, data: Dict[str, Any], rows: int, cols: int) -> List[str]:
        """Render *data* into board lines that fit exactly *rows* x *cols*."""
        revealed = bool(data["is_revealed"])
        answer_rows = 1 if revealed else 0
        body_rows = max(1, rows - answer_rows)

        choice_row_budget = max(0, body_rows - 1)
        choice_lines = _choice_lines(data, cols, rows, choice_row_budget)

        question_max = _question_budget(body_rows, len(choice_lines))
        lines = _wrap(data["question"], cols, question_max) + choice_lines

        lines = lines[:body_rows]
        lines += [""] * (body_rows - len(lines))
        if revealed:
            lines.append(_clip(f"ANSWER: {data['answer_letter']} {data['answer']}", cols))
        return lines

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        errors = self._validate_refresh_seconds(config)

        difficulty = config.get("difficulty", "any")
        if difficulty not in DIFFICULTIES:
            errors.append(f"Difficulty must be one of: {', '.join(DIFFICULTIES)}")

        category = config.get("category", 0)
        if isinstance(category, bool) or not isinstance(category, int) or category < 0:
            errors.append("Category must be a whole number (0 = any category)")

        return errors

    def get_formatted_display(self) -> Optional[List[str]]:
        """Default display: wrapped question, lettered choices, answer line."""
        result = self.get_data()
        if not result.available or not result.data:
            return None

        rows = self.board.rows if self.board else FLAGSHIP_ROWS
        cols = self.board.cols if self.board else 22
        return self._format_lines(result.data, rows, cols)

    def cleanup(self) -> None:
        self._states = {}


# Export the plugin class
Plugin = TriviaPlugin
