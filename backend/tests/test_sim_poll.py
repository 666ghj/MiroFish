import json

import pytest

import sim_poll
from sim_poll import build_poll_prompt, coerce_answer, extract_json_object, parse_poll_answer, poll_row

Q_PROB = {"id": "q1", "text": "Will it trade above its close?", "type": "probability"}
Q_CHOICE = {"id": "q2", "text": "Your stance?", "type": "choice", "options": ["bullish", "neutral", "bearish"]}
Q_NUMBER = {"id": "q3", "text": "Expected move?", "type": "number", "unit": "%"}
QUESTIONS = [Q_PROB, Q_CHOICE, Q_NUMBER]


# --- prompt --------------------------------------------------------------------

def test_prompt_lists_the_questions_and_demands_json_only():
    prompt = build_poll_prompt(QUESTIONS)
    assert prompt.startswith("The simulation has ended. Answer as yourself, based only on what you have seen.")
    assert "Reply with ONLY a JSON object" in prompt
    assert "q1 (probability, a number from 0 to 100): Will it trade above its close?" in prompt
    assert "q2 (choose exactly one of: bullish, neutral, bearish): Your stance?" in prompt
    assert "q3 (a number in %): Expected move?" in prompt


def test_prompt_template_matches_the_question_types():
    prompt = build_poll_prompt(QUESTIONS)
    template = prompt.splitlines()[-1]
    assert '"q1": <0-100>' in template
    assert '"q2": "<bullish|neutral|bearish>"' in template
    assert '"q3": <number>' in template
    assert template.endswith('"reason": "<one sentence>"}')


def test_a_number_question_without_a_unit_is_still_valid():
    prompt = build_poll_prompt([{"id": "q1", "text": "How many?", "type": "number"}])
    assert "q1 (a number): How many?" in prompt


def test_prompt_is_identical_for_every_agent():
    assert build_poll_prompt(QUESTIONS) == build_poll_prompt(list(QUESTIONS))


# --- json extraction -------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        '{"q1": 70}',
        '```json\n{"q1": 70}\n```',
        '```\n{"q1": 70}\n```',
        'Sure! Here you go: {"q1": 70} Hope that helps.',
        '<think>hmm, maybe {"q1": 1}</think>{"q1": 70}',
        '<thought>maybe {"q1": 1}</thought>```json\n{"q1": 70}\n```',
        '{"q1": 70}',
        'Text before ```json\n{"q1": 70}\n``` text after',
    ],
)
def test_json_is_extracted_from_messy_replies(raw):
    assert extract_json_object(raw) == {"q1": 70}


@pytest.mark.parametrize("raw", [None, "", "no json here", "{not json}", "[1, 2, 3]", '"just a string"', "{"])
def test_unparseable_replies_give_none(raw):
    assert extract_json_object(raw) is None


def test_the_first_decodable_object_wins():
    assert extract_json_object('{"a": 1} then {"b": 2}') == {"a": 1}
    assert extract_json_object('{bad} then {"b": 2}') == {"b": 2}


# --- coercion --------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [(70, 70.0), (70.5, 70.5), ("70", 70.0), ("70%", 70.0), ("about 65 percent", 65.0), (0, 0.0), (100, 100.0), ("1,0", 10.0)],
)
def test_probabilities_accept_numbers_and_numeric_strings(value, expected):
    assert coerce_answer(Q_PROB, value) == expected


@pytest.mark.parametrize("value", [-1, 100.5, 150, "high", None, True, [70], {"v": 70}, float("nan"), float("inf")])
def test_invalid_probabilities_are_rejected(value):
    assert coerce_answer(Q_PROB, value) is None


@pytest.mark.parametrize(
    "value,expected",
    [("bullish", "bullish"), ("BULLISH", "bullish"), (" Neutral. ", "neutral"), ('"bearish"', "bearish"),
     ("I would say bullish.", "bullish"), ("(bearish)", "bearish")],
)
def test_choices_match_options_case_insensitively(value, expected):
    assert coerce_answer(Q_CHOICE, value) == expected


@pytest.mark.parametrize("value", ["", "maybe", 5, None, "bullish or bearish", "unbullish"])
def test_invalid_choices_are_rejected(value):
    assert coerce_answer(Q_CHOICE, value) is None


def test_choices_return_the_canonical_option_spelling():
    question = {"id": "q", "text": "t", "type": "choice", "options": ["Strongly Agree", "Disagree"]}
    assert coerce_answer(question, "strongly agree") == "Strongly Agree"


@pytest.mark.parametrize("value,expected", [(-3.5, -3.5), ("12%", 12.0), ("-4.25 pts", -4.25), (1e6, 1e6), (0, 0.0)])
def test_numbers_are_any_finite_value(value, expected):
    assert coerce_answer(Q_NUMBER, value) == expected


@pytest.mark.parametrize("value", ["lots", None, True, float("inf")])
def test_invalid_numbers_are_rejected(value):
    assert coerce_answer(Q_NUMBER, value) is None


# --- parse_poll_answer -------------------------------------------------------------

def test_a_complete_answer_parses_ok():
    answers, reason, ok = parse_poll_answer(
        '{"q1": 62, "q2": "bullish", "q3": "1.5%", "reason": "  Margins look fine.  "}', QUESTIONS
    )
    assert ok is True
    assert answers == {"q1": 62.0, "q2": "bullish", "q3": 1.5}
    assert reason == "Margins look fine."


def test_a_partial_answer_is_kept_but_not_ok():
    answers, reason, ok = parse_poll_answer('{"q1": 62, "q2": "who knows"}', QUESTIONS)
    assert ok is False
    assert answers == {"q1": 62.0}
    assert reason == ""


def test_prose_is_not_ok_and_has_no_answers():
    assert parse_poll_answer("I think things are uncertain.", QUESTIONS) == ({}, "", False)
    assert parse_poll_answer(None, QUESTIONS) == ({}, "", False)


def test_extra_keys_are_ignored_and_the_reason_is_capped():
    answers, reason, ok = parse_poll_answer(
        json.dumps({"q1": 10, "q2": "neutral", "q3": 0, "extra": 1, "reason": "x" * 2000}), QUESTIONS
    )
    assert ok and set(answers) == {"q1", "q2", "q3"} and len(reason) == sim_poll.MAX_REASON_CHARS


def test_a_non_string_reason_is_ignored():
    assert parse_poll_answer('{"q1": 1, "reason": 7}', [Q_PROB])[1:] == ("", True)


def test_zero_questions_always_parse_ok_for_a_json_reply():
    assert parse_poll_answer('{"reason": "none"}', []) == ({}, "none", True)


# --- poll_row ----------------------------------------------------------------------

def test_poll_row_has_the_documented_shape():
    row = poll_row(3, "Skeptics", "opposing", '{"q1": 20}', [Q_PROB])
    assert row == {
        "agent_id": 3, "agent_name": "Skeptics", "stance_initial": "opposing",
        "answers": {"q1": 20.0}, "reason": "", "raw": '{"q1": 20}', "parse_ok": True,
    }


def test_poll_row_for_a_silent_agent_records_the_error():
    row = poll_row(1, "A", "neutral", None, [Q_PROB], error="provider exploded")
    assert row["raw"] is None and row["parse_ok"] is False and row["answers"] == {}
    assert row["error"] == "provider exploded"
    assert "error" not in poll_row(1, "A", "neutral", "{}", [Q_PROB])
