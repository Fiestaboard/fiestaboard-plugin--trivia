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
QUESTION_MAX_LINES = 3


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


class TriviaPlugin(PluginBase):
    """Trivia plugin.

    Two-phase state machine driven by the refresh interval:
    "question" shows the question and four choices; the next refresh flips
    to "answer" (same question, correct answer revealed); the refresh after
    that fetches a new question.
    """

    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self._question: Optional[Dict[str, Any]] = None
        self._revealed = False

    @property
    def plugin_id(self) -> str:
        return "trivia"

    def fetch_data(self) -> PluginResult:
        """Advance the question/answer state machine and return its data."""
        try:
            if self._question is None or self._revealed:
                self._question = self._fetch_question()
                self._revealed = False
            else:
                self._revealed = True
            return PluginResult(available=True, data=self._build_data())
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

    def _build_data(self) -> Dict[str, Any]:
        q = self._question
        choices = q["choices"]
        data: Dict[str, Any] = {"question": q["question"]}
        for i, letter in enumerate(LETTERS):
            data[f"choice_{letter.lower()}"] = choices[i] if i < len(choices) else ""
        data.update(
            {
                "answer": q["answer"] if self._revealed else "",
                "answer_letter": q["answer_letter"] if self._revealed else "",
                "phase": "answer" if self._revealed else "question",
                "category": q["category"],
                "difficulty": q["difficulty"],
                "is_revealed": self._revealed,
            }
        )
        return data

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
        data = result.data

        rows = self.board.rows if self.board else 6
        cols = self.board.cols if self.board else 22
        half = cols // 2

        choice_lines: List[str] = []
        labelled = [f"{letter} {data[f'choice_{letter.lower()}']}" for letter in LETTERS]
        for left, right in zip(labelled[0::2], labelled[1::2]):
            if len(left) < half and len(right) <= cols - half:
                choice_lines.append(left.ljust(half) + right)
            else:
                choice_lines.append(left[:cols])
                choice_lines.append(right[:cols])

        question_max = min(QUESTION_MAX_LINES, max(1, rows - len(choice_lines) - int(data["is_revealed"])))
        lines = _wrap(data["question"], cols, question_max) + choice_lines

        body_rows = rows - int(data["is_revealed"])
        lines = lines[:body_rows]
        lines += [""] * (body_rows - len(lines))
        if data["is_revealed"]:
            lines.append(f"ANSWER: {data['answer_letter']} {data['answer']}"[:cols])
        return lines

    def cleanup(self) -> None:
        self._question = None
        self._revealed = False


# Export the plugin class
Plugin = TriviaPlugin
