import pytest

from app.services.outcome_questions import (
    MAX_QUESTIONS,
    default_outcome_questions,
    derive_outcome_questions,
    validate_outcome_questions,
)


def ok(questions):
    normalized, errors = validate_outcome_questions(questions)
    assert errors == [], errors
    return normalized


def bad(questions):
    normalized, errors = validate_outcome_questions(questions)
    assert normalized == [] or errors, "expected an error"
    assert errors, "expected an error"
    return errors


# --- valid questions ----------------------------------------------------------------------

def test_each_question_type_is_accepted_and_normalised():
    out = ok([
        {"text": " Will it rise? ", "type": "probability"},
        {"text": "Stance?", "type": "choice", "options": [" up ", "down"],
         "stance_map": {"UP": "supportive", "down": "opposing"}},
        {"text": "How far?", "type": "number", "unit": " % "},
    ])
    assert out[0] == {"id": "q1", "text": "Will it rise?", "type": "probability"}
    assert out[1] == {"id": "q2", "text": "Stance?", "type": "choice", "options": ["up", "down"],
                      "stance_map": {"up": "supportive", "down": "opposing"}}
    assert out[2] == {"id": "q3", "text": "How far?", "type": "number", "unit": "%"}


def test_generated_ids_skip_ids_already_in_use():
    out = ok([{"id": "q1", "text": "a", "type": "probability"}, {"text": "b", "type": "probability"},
              {"id": "mine", "text": "c", "type": "probability"}])
    assert [q["id"] for q in out] == ["q1", "q2", "mine"]
    out = ok([{"text": "a", "type": "probability"}, {"id": "q1", "text": "b", "type": "probability"}])
    assert [q["id"] for q in out] == ["q2", "q1"]


def test_an_empty_list_is_valid_and_means_no_poll():
    assert validate_outcome_questions([]) == ([], [])


def test_up_to_three_questions_are_allowed():
    assert len(ok([{"text": str(i), "type": "probability"} for i in range(MAX_QUESTIONS)])) == 3


# --- invalid questions ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "q", {"id": "q1"}, 5])
def test_a_non_list_is_rejected(value):
    assert bad(value) == ["outcome_questions must be a list"]


def test_more_than_three_questions_are_rejected():
    assert "at most 3" in bad([{"text": "x", "type": "probability"}] * 4)[0]


@pytest.mark.parametrize(
    "question,fragment",
    [
        ("text", "must be an object"),
        ({"text": "", "type": "probability"}, "text must be a non-empty string"),
        ({"text": "  ", "type": "probability"}, "text must be a non-empty string"),
        ({"type": "probability"}, "text must be a non-empty string"),
        ({"text": "x" * 501, "type": "probability"}, "longer than"),
        ({"text": "x", "type": "essay"}, "type must be one of"),
        ({"text": "x"}, "type must be one of"),
        ({"id": "1abc", "text": "x", "type": "probability"}, "must start with a letter"),
        ({"id": "has space", "text": "x", "type": "probability"}, "must start with a letter"),
        ({"id": "reason", "text": "x", "type": "probability"}, "reserved"),
        ({"id": "a" * 40, "text": "x", "type": "probability"}, "must start with a letter"),
        ({"text": "x", "type": "choice"}, "options must be a list"),
        ({"text": "x", "type": "choice", "options": "up,down"}, "options must be a list"),
        ({"text": "x", "type": "choice", "options": ["up", ""]}, "options must be a list"),
        ({"text": "x", "type": "choice", "options": [1, 2]}, "options must be a list"),
        ({"text": "x", "type": "choice", "options": ["only"]}, "provide 2-8 options"),
        ({"text": "x", "type": "choice", "options": [str(i) for i in range(9)]}, "provide 2-8 options"),
        ({"text": "x", "type": "choice", "options": ["Up", "up"]}, "unique"),
        ({"text": "x", "type": "choice", "options": ["up", "y" * 61]}, "longer than 60"),
        ({"text": "x", "type": "choice", "options": ["up", "down"], "stance_map": "up"}, "stance_map must be an object"),
        ({"text": "x", "type": "choice", "options": ["up", "down"], "stance_map": {"sideways": "neutral"}}, "stance_map entry"),
        ({"text": "x", "type": "choice", "options": ["up", "down"], "stance_map": {"up": "ecstatic"}}, "stance_map entry"),
        ({"text": "x", "type": "number"}, "needs a unit"),
        ({"text": "x", "type": "number", "unit": "  "}, "needs a unit"),
        ({"text": "x", "type": "number", "unit": "u" * 21}, "unit is longer"),
    ],
)
def test_invalid_questions_are_reported(question, fragment):
    errors = bad([question])
    assert len(errors) == 1 and fragment in errors[0] and errors[0].startswith("question 1")


def test_duplicate_ids_are_rejected_and_every_bad_question_is_reported():
    errors = bad([{"id": "a", "text": "x", "type": "probability"}, {"id": "a", "text": "y", "type": "probability"},
                  {"text": "", "type": "probability"}])
    assert len(errors) == 2
    assert "duplicate id" in errors[0] and errors[1].startswith("question 3")


def test_validation_does_not_mutate_its_input():
    raw = [{"text": " a ", "type": "choice", "options": [" x ", "y"], "stance_map": {"x": "supportive"}}]
    snapshot = repr(raw)
    validate_outcome_questions(raw)
    assert repr(raw) == snapshot


# --- the default question -----------------------------------------------------------------------

def test_the_default_question_is_a_valid_stance_question():
    config = {"event_config": {"topic": "HEGAM demerger"}, "simulation_requirement": "ignored"}
    questions = default_outcome_questions(config)
    assert len(questions) == 1
    assert ok(questions) == questions  # passes its own validation unchanged
    assert 'HEGAM demerger' in questions[0]["text"]
    assert questions[0]["stance_map"] == {"supportive": "supportive", "neutral": "neutral", "opposing": "opposing"}


def test_the_default_question_falls_back_to_the_requirement_then_a_generic_topic():
    assert "a requirement" in default_outcome_questions({"simulation_requirement": "a requirement"})[0]["text"]
    long = default_outcome_questions({"simulation_requirement": "Z" * 500})[0]["text"]
    assert long.count("Z") == 120
    assert "this topic" in default_outcome_questions({})[0]["text"]


# --- derivation ----------------------------------------------------------------------------------

CONFIG = {
    "simulation_requirement": "Will HEGAM rise after the demerger?",
    "event_config": {"topic": "HEGAM demerger"},
    "agent_configs": [{"agent_id": 0, "entity_name": "Alice", "entity_type": "Person", "stance": "supportive"}],
}


def test_questions_are_derived_with_one_llm_call():
    calls = []

    def llm(messages):
        calls.append(messages)
        return {"questions": [
            {"text": "Will HEGAM rise?", "type": "probability"},
            {"text": "Your stance?", "type": "choice", "options": ["bullish", "bearish"],
             "stance_map": {"bullish": "supportive", "bearish": "opposing"}},
        ]}

    questions, source = derive_outcome_questions(CONFIG, llm)
    assert source == "llm" and len(calls) == 1
    assert [q["id"] for q in questions] == ["q1", "q2"]
    prompt = "\n".join(m["content"] for m in calls[0])
    assert "Will HEGAM rise after the demerger?" in prompt and "Alice" in prompt and "stance_map" in prompt
    assert "Do not leak any expected outcome" in prompt


@pytest.mark.parametrize(
    "reply",
    [
        {"questions": []},
        {"questions": "not a list"},
        {},
        {"questions": [{"text": "x", "type": "bogus"}]},
        {"questions": [{"text": "x", "type": "choice", "options": ["only-one"]}]},
    ],
)
def test_an_unusable_llm_reply_falls_back_to_the_default(reply):
    questions, source = derive_outcome_questions(CONFIG, lambda _m: reply)
    assert source == "fallback" and questions == default_outcome_questions(CONFIG)


def test_an_llm_exception_falls_back_to_the_default():
    def boom(_messages):
        raise ConnectionError("down")

    questions, source = derive_outcome_questions(CONFIG, boom)
    assert source == "fallback" and questions[0]["id"] == "q1"


def test_derivation_prompt_asks_for_the_configured_language(monkeypatch):
    seen = []
    from app.services import outcome_questions

    monkeypatch.setattr(outcome_questions, "get_language_instruction", lambda: "Please respond in English.")
    derive_outcome_questions(CONFIG, lambda messages: (seen.append(messages), {"questions": []})[1])
    assert "Please respond in English." in seen[0][1]["content"]


# --- a model's reply is tidied, not rejected wholesale ----------------------------------------

def derive(reply):
    return derive_outcome_questions(CONFIG, lambda _messages: reply)


def test_an_overlong_unit_is_shortened_instead_of_discarding_every_question():
    """Seen with a real model: 'unit is longer than 20 characters' threw away a good probability question too."""
    questions, source = derive({"questions": [
        {"text": "Will it close higher?", "type": "probability"},
        {"text": "By how much?", "type": "number", "unit": "percentage points of the share price"},
    ]})
    assert source == "llm" and [q["type"] for q in questions] == ["probability", "number"]
    assert len(questions[1]["unit"]) <= 20 and questions[1]["unit"] == "percentage points"


def test_a_question_that_cannot_be_saved_is_skipped_and_the_others_are_kept():
    questions, source = derive({"questions": [
        {"text": "Will it close higher?", "type": "probability"},
        {"text": "Rank these", "type": "ranking"},
        {"text": "Pick one", "type": "choice", "options": ["only"]},
        {"text": "How much?", "type": "number"},
        {"text": "   ", "type": "probability"},
        "not even an object",
    ]})
    assert source == "llm" and [q["text"] for q in questions] == ["Will it close higher?"]


def test_options_are_cleaned_and_stance_map_entries_that_match_nothing_are_dropped():
    (question,), source = derive({"questions": [{
        "text": "Your stance?", "type": "Choice",
        "options": ["Bullish", " bullish ", "", None, "Neutral", "x" * 100, "Bearish"],
        "stance_map": {"BULLISH": "Supportive", "bearish": "opposing", "renamed": "opposing", "neutral": "mixed"},
    }]})
    assert source == "llm"
    assert question["options"] == ["Bullish", "Neutral", "x" * 60, "Bearish"]
    assert question["stance_map"] == {"Bullish": "supportive", "Bearish": "opposing"}


def test_a_choice_keeps_at_most_eight_options():
    (question,), _ = derive({"questions": [{"text": "Pick", "type": "choice", "options": [f"o{i}" for i in range(12)]}]})
    assert question["options"] == [f"o{i}" for i in range(8)]


def test_repeated_and_reserved_ids_are_replaced_by_fresh_ones():
    questions, source = derive({"questions": [
        {"id": "q1", "text": "a", "type": "probability"},
        {"id": "q1", "text": "b", "type": "probability"},
        {"id": "reason", "text": "c", "type": "probability"},
    ]})
    assert source == "llm" and [q["id"] for q in questions] == ["q1", "q2", "q3"]


def test_more_than_three_questions_keep_the_first_three_usable_ones():
    questions, source = derive({"questions": [
        {"text": "skip me", "type": "bogus"},
        *({"text": f"question {i}", "type": "probability"} for i in range(5)),
    ]})
    assert source == "llm" and [q["text"] for q in questions] == ["question 0", "question 1", "question 2"]


def test_a_bare_list_is_accepted_like_the_wrapped_reply():
    questions, source = derive([{"text": "Will it close higher?", "type": "probability"}])
    assert source == "llm" and questions == [{"id": "q1", "text": "Will it close higher?", "type": "probability"}]


def test_long_text_is_cut_at_a_word_boundary():
    (question,), _ = derive({"questions": [{"text": "word " * 200, "type": "probability"}]})
    assert len(question["text"]) <= 500 and question["text"].endswith("word")


def test_the_prompt_states_the_length_limits():
    seen = []
    derive_outcome_questions(CONFIG, lambda messages: (seen.append(messages), {"questions": []})[1])
    prompt = " ".join(seen[0][1]["content"].split())
    assert "at most 500 characters" in prompt and "at most 60," in prompt and "at most 20 (" in prompt


def test_questions_typed_by_a_user_are_still_validated_strictly():
    errors = bad([{"text": "How much?", "type": "number", "unit": "u" * 21}])
    assert any("unit is longer than 20" in message for message in errors)
