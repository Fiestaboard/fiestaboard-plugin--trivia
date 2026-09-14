"""Tests for the trivia plugin."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from plugins.trivia import TriviaPlugin, _wrap


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
        assert data["category"] == "General Knowledge"
        assert data["difficulty"] == "easy"
        assert "Hubble Space Telescope" in {data["choice_a"], data["choice_b"], data["choice_c"], data["choice_d"]}

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
        assert sorted(choices) == sorted(["Hubble Space Telescope", "Big Eye", "Death Star", "Millenium Falcon"])
        mock_shuffle.assert_called_once()
        # correct answer starts first, reverse() puts it last -> D
        assert data["answer_letter"] == "D"
        assert data["choice_d"] == "Hubble Space Telescope"
        assert data["answer"] == "Hubble Space Telescope"

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
        assert second["answer"] == "Hubble Space Telescope"
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
        assert lines[2] == "A Hubble Space Telesco"
        assert lines[3] == "B Big Eye"
        assert lines[4] == "C Death Star"
        assert lines[5] == "D Millenium Falcon"

    @patch("plugins.trivia.requests.get")
    def test_note_board_dimensions(self, mock_get, plugin):
        mock_get.return_value = _mock_response(SECOND_RESPONSE)
        board = SimpleNamespace(device_type="note", rows=3, cols=15)

        with plugin._bound_board(board):
            lines = plugin.get_formatted_display()

        assert len(lines) == 3
        assert all(len(line) <= 15 for line in lines)

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
