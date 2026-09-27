"""Tests for the trivia plugin."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.plugins.geometry_conformance import assert_board_conformance
from plugins.trivia import TriviaPlugin, _choice_lines, _clip, _question_budget, _wrap


MANIFEST = json.loads((Path(__file__).parent.parent / "manifest.json").read_text())

# url3986-encoded, as OpenTDB returns with encode=url3986
API_RESPONSE = {
    "response_code": 0,
    "results": [
        {
            "type": "multiple",
            "difficulty": "easy",
            "category": "General%20Knowledge",
            "question": "What%20is%20the%20name%20of%20NASA%E2%80%99s%20most%20famous%20space%20telescope%3F",
            "correct_answer": "Hubble%20Space%20Telescope",
            "incorrect_answers": ["Big%20Eye", "Death%20Star", "Millenium%20Falcon"],
        }
    ],
}

SECOND_RESPONSE = {
    "response_code": 0,
    "results": [
        {
            "type": "multiple",
            "difficulty": "hard",
            "category": "Geography",
            "question": "What%20is%20the%20capital%20of%20Australia%3F",
            "correct_answer": "Canberra",
            "incorrect_answers": ["Sydney", "Perth", "Melbourne"],
        }
    ],
}


def _mock_response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def plugin():
    return TriviaPlugin(MANIFEST)


class TestFetchData:
    def test_plugin_id(self, plugin):
        assert plugin.plugin_id == "trivia"

    @patch("plugins.trivia.requests.get")
    def test_success_returns_every_declared_variable(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        result = plugin.fetch_data()

        assert result.available is True
        assert result.error is None
        for var in MANIFEST["variables"]["simple"]:
            assert var in result.data, f"'{var}' declared in manifest but missing from data"
        assert set(result.data) == set(MANIFEST["variables"]["simple"])

    @patch("plugins.trivia.requests.get")
    def test_url3986_is_decoded(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        data = plugin.fetch_data().data

        assert data["question"] == "What is the name of NASA’s most famous space telescope?"
        # category and choice text are clipped to VARIABLE_MAX_LENGTH (15, the
        # Note's width) so a template variable fits every board -- see F7.
        assert data["category"] == _clip("General Knowledge", 15)
        assert data["difficulty"] == "easy"
        assert _clip("Hubble Space Telescope", 15) in {
            data["choice_a"],
            data["choice_b"],
            data["choice_c"],
            data["choice_d"],
        }

    @patch("plugins.trivia.requests.get")
    def test_question_phase_hides_answer(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        data = plugin.fetch_data().data

        assert data["phase"] == "question"
        assert data["is_revealed"] is False
        assert data["answer"] == ""
        assert data["answer_letter"] == ""

    @patch("plugins.trivia.random.shuffle")
    @patch("plugins.trivia.requests.get")
    def test_choices_are_shuffled_and_contain_correct_answer(self, mock_get, mock_shuffle, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)
        mock_shuffle.side_effect = lambda items: items.reverse()

        plugin.fetch_data()
        data = plugin.fetch_data().data  # reveal

        choices = [data["choice_a"], data["choice_b"], data["choice_c"], data["choice_d"]]
        expected = sorted(_clip(c, 15) for c in ["Hubble Space Telescope", "Big Eye", "Death Star", "Millenium Falcon"])
        assert sorted(choices) == expected
        mock_shuffle.assert_called_once()
        # correct answer starts first, reverse() puts it last -> D
        assert data["answer_letter"] == "D"
        assert data["choice_d"] == _clip("Hubble Space Telescope", 15)
        assert data["answer"] == _clip("Hubble Space Telescope", 15)

    @patch("plugins.trivia.requests.get")
    def test_answer_letter_points_at_correct_choice(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        plugin.fetch_data()
        data = plugin.fetch_data().data

        letter = data["answer_letter"]
        assert letter in "ABCD"
        assert data[f"choice_{letter.lower()}"] == data["answer"]

    @patch("plugins.trivia.requests.get")
    def test_phase_flips_question_answer_new_question(self, mock_get, plugin):
        mock_get.side_effect = [_mock_response(API_RESPONSE), _mock_response(SECOND_RESPONSE)]

        first = plugin.fetch_data().data
        assert first["phase"] == "question"
        assert mock_get.call_count == 1

        second = plugin.fetch_data().data
        assert second["phase"] == "answer"
        assert second["is_revealed"] is True
        assert second["question"] == first["question"]
        assert [second[f"choice_{c}"] for c in "abcd"] == [first[f"choice_{c}"] for c in "abcd"]
        assert second["answer"] == _clip("Hubble Space Telescope", 15)
        assert mock_get.call_count == 1, "answer phase must not make a second HTTP call"

        third = plugin.fetch_data().data
        assert third["phase"] == "question"
        assert third["question"] == "What is the capital of Australia?"
        assert third["answer"] == ""
        assert mock_get.call_count == 2

    @patch("plugins.trivia.requests.get")
    def test_response_code_nonzero_is_unavailable(self, mock_get, plugin):
        mock_get.return_value = _mock_response({"response_code": 1, "results": []})

        result = plugin.fetch_data()

        assert result.available is False
        assert "response_code 1" in result.error

    @patch("plugins.trivia.requests.get")
    def test_empty_results_is_unavailable(self, mock_get, plugin):
        mock_get.return_value = _mock_response({"response_code": 0, "results": []})

        result = plugin.fetch_data()

        assert result.available is False
        assert "No question" in result.error

    @patch("plugins.trivia.requests.get")
    def test_malformed_result_is_unavailable(self, mock_get, plugin):
        mock_get.return_value = _mock_response({"response_code": 0, "results": [{"type": "multiple"}]})

        result = plugin.fetch_data()

        assert result.available is False
        assert result.error

    @patch("plugins.trivia.requests.get")
    def test_http_error_is_unavailable(self, mock_get, plugin):
        response = Mock()
        response.raise_for_status.side_effect = Exception("HTTP 429")
        mock_get.return_value = response

        result = plugin.fetch_data()

        assert result.available is False
        assert "HTTP 429" in result.error

    @patch("plugins.trivia.requests.get")
    def test_network_error_is_unavailable(self, mock_get, plugin):
        mock_get.side_effect = Exception("Network error")

        result = plugin.fetch_data()

        assert result.available is False
        assert "Network error" in result.error

    @patch("plugins.trivia.requests.get")
    def test_failed_fetch_keeps_previous_state(self, mock_get, plugin):
        mock_get.side_effect = [_mock_response(API_RESPONSE), Exception("boom"), _mock_response(SECOND_RESPONSE)]

        plugin.fetch_data()  # question
        plugin.fetch_data()  # answer
        assert plugin.fetch_data().available is False  # new question fails
        # next refresh retries the fetch rather than re-showing the old answer
        data = plugin.fetch_data().data
        assert data["phase"] == "question"
        assert data["question"] == "What is the capital of Australia?"

    @patch("plugins.trivia.requests.get")
    def test_phase_advances_independently_per_board(self, mock_get, plugin):
        """F6 regression.

        The platform holds ONE plugin instance per plugin id and renders it
        for every board the user owns. Before the fix, a cache miss on one
        board (calling fetch_data() again) silently advanced or skipped the
        question -> answer -> new-question cycle for every OTHER board too,
        because the phase state lived in plain instance attributes with no
        geometry key.

        Reproduces exactly that: render a flagship, then -- for the first
        time -- a note. The note's own first render must start its own
        question phase, not inherit whatever phase the flagship's render
        left behind. On the old code this failed with `note_q1["phase"] ==
        "answer"` (and a stale flagship question), because rendering the
        note advanced the one shared `_revealed` flag.
        """
        mock_get.side_effect = [_mock_response(API_RESPONSE), _mock_response(SECOND_RESPONSE)]
        flagship = SimpleNamespace(device_type="flagship", rows=6, cols=22)
        note = SimpleNamespace(device_type="note", rows=3, cols=15)

        with plugin._bound_board(flagship):
            flagship_q1 = plugin.fetch_data().data
        assert flagship_q1["phase"] == "question"

        # Note's own first-ever render must get its own fresh question phase.
        with plugin._bound_board(note):
            note_q1 = plugin.fetch_data().data
        assert note_q1["phase"] == "question"
        assert mock_get.call_count == 2, "each board fetches its own question independently"

        # Flagship's own next refresh reveals *its* question -- unaffected by
        # the note's render in between.
        with plugin._bound_board(flagship):
            flagship_q2 = plugin.fetch_data().data
        assert flagship_q2["phase"] == "answer"
        assert flagship_q2["question"] == flagship_q1["question"]

    @patch("plugins.trivia.requests.get")
    def test_request_params_and_headers_default(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        plugin.fetch_data()

        kwargs = mock_get.call_args.kwargs
        assert kwargs["params"] == {"amount": 1, "type": "multiple", "encode": "url3986"}
        assert kwargs["timeout"] == 10
        assert "FiestaBoard" in kwargs["headers"]["User-Agent"]

    @patch("plugins.trivia.requests.get")
    def test_request_params_with_difficulty_and_category(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)
        plugin.config = {"difficulty": "hard", "category": 22}

        plugin.fetch_data()

        params = mock_get.call_args.kwargs["params"]
        assert params["difficulty"] == "hard"
        assert params["category"] == 22

    @patch("plugins.trivia.requests.get")
    def test_cleanup_resets_state(self, mock_get, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)

        plugin.fetch_data()
        plugin.cleanup()
        data = plugin.fetch_data().data

        assert data["phase"] == "question"
        assert mock_get.call_count == 2


class TestValidateConfig:
    def test_valid_config(self, plugin):
        assert plugin.validate_config(
            {"difficulty": "easy", "category": 9, "refresh_seconds": 120}
        ) == []

    def test_empty_config_is_valid(self, plugin):
        assert plugin.validate_config({}) == []

    def test_bad_difficulty(self, plugin):
        errors = plugin.validate_config({"difficulty": "brutal"})
        assert len(errors) == 1
        assert "Difficulty" in errors[0]

    @pytest.mark.parametrize("category", [-1, "9", 2.5, True])
    def test_bad_category(self, plugin, category):
        errors = plugin.validate_config({"category": category})
        assert any("Category" in e for e in errors)

    def test_bad_refresh_seconds(self, plugin):
        errors = plugin.validate_config({"refresh_seconds": 5})
        assert any("at least 30" in e for e in errors)


class TestWrap:
    def test_wraps_within_width(self):
        lines = _wrap("What is the name of NASA's most famous space telescope?", 22, 3)
        assert lines == ["What is the name of", "NASA's most famous", "space telescope?"]
        assert all(len(line) <= 22 for line in lines)

    def test_truncates_with_ellipsis(self):
        text = " ".join(["word"] * 40)
        lines = _wrap(text, 22, 3)
        assert len(lines) == 3
        assert lines[-1].endswith("...")
        assert all(len(line) <= 22 for line in lines)

    def test_long_word_is_cut(self):
        lines = _wrap("Supercalifragilisticexpialidocious yes", 22, 3)
        assert lines[0] == "Supercalifragilisticex"
        assert lines[1] == "yes"

    def test_empty_text(self):
        assert _wrap("", 22, 3) == []


class TestFormattedDisplay:
    @patch("plugins.trivia.requests.get")
    def test_question_phase_shape(self, mock_get, plugin):
        mock_get.return_value = _mock_response(SECOND_RESPONSE)

        lines = plugin.get_formatted_display()

        assert lines is not None
        assert len(lines) == 6
        assert all(len(line) <= 22 for line in lines)
        assert lines[0] == "What is the capital of"
        assert lines[1] == "Australia?"
        assert lines[2].startswith("A ")
        assert not any("ANSWER:" in line for line in lines)

    @patch("plugins.trivia.random.shuffle")
    @patch("plugins.trivia.requests.get")
    def test_short_choices_two_per_line(self, mock_get, mock_shuffle, plugin):
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        mock_shuffle.side_effect = lambda items: None  # keep order: Canberra, Sydney, Perth, Melbourne

        lines = plugin.get_formatted_display()

        assert lines[2] == "A Canberra B Sydney"
        assert lines[3] == "C Perth    D Melbourne"
        assert lines[4] == ""

    @patch("plugins.trivia.requests.get")
    def test_answer_phase_last_line(self, mock_get, plugin):
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        plugin.get_data()  # question phase, cached
        plugin.clear_cache()  # simulate the refresh interval elapsing

        lines = plugin.get_formatted_display()  # next refresh -> answer phase

        assert len(lines) == 6
        assert all(len(line) <= 22 for line in lines)
        assert lines[-1].startswith("ANSWER: ")
        assert lines[-1].endswith("Canberra")

    @patch("plugins.trivia.random.shuffle")
    @patch("plugins.trivia.requests.get")
    def test_long_choices_one_per_line(self, mock_get, mock_shuffle, plugin):
        mock_get.return_value = _mock_response(API_RESPONSE)
        mock_shuffle.side_effect = lambda items: None  # Hubble Space Telescope first

        lines = plugin.get_formatted_display()

        assert len(lines) == 6
        assert all(len(line) <= 22 for line in lines)
        # question squeezed to 2 lines (with ellipsis) so all four choices fit
        assert lines[0] == "What is the name of"
        assert lines[1].endswith("...")
        # choice/answer text is clipped to 15 chars (VARIABLE_MAX_LENGTH) with
        # an ellipsis -- never silently cut mid-word with no indication.
        assert lines[2] == "A Hubble Space..."
        assert lines[3] == "B Big Eye"
        assert lines[4] == "C Death Star"
        assert lines[5] == "D Millenium Fa..."

    @patch("plugins.trivia.requests.get")
    def test_note_board_dimensions(self, mock_get, plugin):
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        board = SimpleNamespace(device_type="note", rows=3, cols=15)

        with plugin._bound_board(board):
            lines = plugin.get_formatted_display()

        assert len(lines) == 3
        assert all(len(line) <= 15 for line in lines)

    @patch("plugins.trivia.requests.get")
    def test_note_board_revealed_still_fits(self, mock_get, plugin):
        """A Note showing the revealed answer leaves only 2 body rows for
        the question + 4 choices combined -- the tightest real geometry.
        Must reflow (never overflow or silently drop content past the
        board's own bound)."""
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        board = SimpleNamespace(device_type="note", rows=3, cols=15)

        plugin.get_data()  # question phase, cached
        plugin.clear_cache()  # simulate the refresh interval elapsing

        with plugin._bound_board(board):
            lines = plugin.get_formatted_display()  # next refresh -> answer phase

        assert len(lines) == 3
        assert all(len(line) <= 15 for line in lines)
        assert lines[-1].startswith("ANSWER: ")

    @patch("plugins.trivia.requests.get")
    def test_tall_note_array_spends_rows_on_one_choice_per_line(self, mock_get, plugin):
        """F1 regression: a board taller than the Flagship baseline must
        spend its extra rows on content (one choice per line) rather than
        leaving them blank, and must never exceed its own row/col bound."""
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        board = SimpleNamespace(device_type="note_array", rows=24, cols=120)

        with plugin._bound_board(board):
            lines = plugin.get_formatted_display()

        assert len(lines) <= 24
        assert all(len(line) <= 120 for line in lines)
        # each choice gets its own line instead of being paired
        assert sum(1 for line in lines if line.strip().startswith(("A ", "B ", "C ", "D "))) == 4

    @patch("plugins.trivia.requests.get")
    def test_returns_none_on_error(self, mock_get, plugin):
        mock_get.side_effect = Exception("Network error")

        assert plugin.get_formatted_display() is None


class TestManifestMetadata:
    def test_manifest_uses_dict_simple_format(self):
        assert isinstance(MANIFEST["variables"]["simple"], dict)

    def test_all_variables_have_descriptions_and_groups(self):
        groups = set(MANIFEST["variables"]["groups"])
        for name, meta in MANIFEST["variables"]["simple"].items():
            assert meta.get("description"), f"'{name}' missing description"
            assert meta.get("group") in groups, f"'{name}' has undefined group"

    @patch("plugins.trivia.requests.get")
    def test_choice_answer_category_never_exceed_declared_max_length(self, mock_get, plugin):
        """F7: max_lengths must be honest -- the manifest declares 15 for
        choice_a-d/answer/category (down from 20/22), and the code must
        actually enforce that bound, not just declare it."""
        mock_get.return_value = _mock_response(API_RESPONSE)  # contains
        # answers longer than 15 chars ("Hubble Space Telescope", 22 chars;
        # "General Knowledge", 18 chars) so the clip is actually exercised.

        plugin.fetch_data()
        data = plugin.fetch_data().data  # reveal, so "answer" is populated

        for var in ("choice_a", "choice_b", "choice_c", "choice_d", "answer", "category"):
            max_length = MANIFEST["variables"]["simple"][var]["max_length"]
            assert max_length <= 15, f"'{var}' declares {max_length}, which cannot fit a Note (15 cols)"
            assert len(data[var]) <= max_length, f"'{var}' rendered {data[var]!r}, longer than declared {max_length}"


class TestClip:
    def test_short_text_is_unchanged(self):
        assert _clip("Sydney", 15) == "Sydney"

    def test_long_text_gets_ellipsis(self):
        result = _clip("Millenium Falcon", 15)
        assert len(result) == 15
        assert result.endswith("...")

    def test_zero_or_negative_width_is_empty(self):
        assert _clip("Sydney", 0) == ""
        assert _clip("Sydney", -1) == ""

    def test_very_narrow_width_has_no_room_for_ellipsis(self):
        assert _clip("Sydney", 2) == "Sy"


class TestBoardGeometryScaling:
    """Direct tests pinning F1's fix: the question's line budget and the
    choice layout mode are derived from the board's own rows, not a fixed
    cap -- asserted against the internal functions themselves (not a
    rendered row count), since the shared growth check cannot distinguish a
    fixed cap from content that is simply short (documented blind spot,
    FiestaBoard PR #2078)."""

    def test_question_budget_scales_with_board_rows_not_fixed_at_three(self):
        # Same number of choice rows either way; only the board's row count
        # differs. The old code capped this at a fixed QUESTION_MAX_LINES=3
        # regardless of board.rows.
        assert _question_budget(body_rows=6, choice_rows=2) == 4
        assert _question_budget(body_rows=23, choice_rows=2) == 21
        assert _question_budget(body_rows=23, choice_rows=2) > 3

    def test_question_budget_never_less_than_one(self):
        assert _question_budget(body_rows=2, choice_rows=4) == 1

    def test_choice_layout_switches_to_one_per_line_on_tall_boards(self):
        data = {
            "choice_a": "Sydney",
            "choice_b": "Canberra",
            "choice_c": "Perth",
            "choice_d": "Melbourne",
        }
        # Flagship-height board keeps the plugin's original paired layout...
        flagship = _choice_lines(data, cols=22, rows=6, choice_row_budget=5)
        assert len(flagship) == 2

        # ...but a board taller than the Flagship baseline spends the extra
        # rows on one choice per line instead of leaving them blank.
        tall = _choice_lines(data, cols=22, rows=12, choice_row_budget=11)
        assert len(tall) == 4

    def test_choice_layout_never_exceeds_its_row_budget(self):
        """However tight the budget, the layout must fit within it -- this
        is what stops a small board (e.g. a Note) from silently truncating
        choices, rather than reflowing them."""
        data = {
            "choice_a": "A Very Long Choice One",
            "choice_b": "Another Long Choice Two",
            "choice_c": "Yet Another Choice Three",
            "choice_d": "The Fourth Long Choice",
        }
        for budget in (1, 2, 3, 4, 5):
            lines = _choice_lines(data, cols=15, rows=3, choice_row_budget=budget)
            assert len(lines) <= budget
            assert all(len(line) <= 15 for line in lines)


class TestGeometryConformance:
    @patch("plugins.trivia.requests.get")
    def test_renders_on_every_board_shape(self, mock_get):
        mock_get.return_value = _mock_response(API_RESPONSE)

        def make_plugin():
            fresh = TriviaPlugin(MANIFEST)
            fresh.config = {}
            return fresh

        # strict_growth=False, deliberately: a trivia question is one item
        # (one question, four choices, one optional answer), not a list or
        # feed. Fixing F1 means a taller board spends its extra rows on
        # content (one choice per line, a longer question budget) instead of
        # blank padding -- it does not mean a taller board has *more*
        # content to show. Turning this on would make the assertion depend
        # on how long this test's fixture question happens to be (whether a
        # given rung's render is "full"), which is exactly the shared
        # suite's documented blind spot (FiestaBoard PR #2078): it cannot
        # tell a fixed cap from genuinely short/fixed content. The actual
        # cap fix (F1) is pinned directly in TestBoardGeometryScaling above,
        # against board geometry rather than a rendered row count.
        assert_board_conformance(
            make_plugin,
            manifest=MANIFEST,
            strict_growth=False,
            require_note_array_preview=True,
        )
