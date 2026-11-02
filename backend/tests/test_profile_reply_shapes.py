import json
from types import SimpleNamespace

import pytest

from app.services import oasis_profile_generator as module
from app.services.oasis_profile_generator import OasisProfileGenerator

PROFILE = {"bio": "Mid-cap pharma maker", "persona": "A listed company that speaks in measured, formal terms."}


@pytest.mark.parametrize("reply", [
    PROFILE,
    [PROFILE],                                  # a list of one profile (what the model really sent)
    [{"note": "x"}, PROFILE],
    {"profile": PROFILE},                       # wrapped
])
def test_every_usual_shape_of_the_reply_yields_the_profile(reply):
    assert OasisProfileGenerator._as_profile_object(reply) == PROFILE


@pytest.mark.parametrize("reply", [[], ["text"], "text", 7, None])
def test_a_reply_without_any_object_is_an_error_so_the_caller_retries(reply):
    with pytest.raises(ValueError):
        OasisProfileGenerator._as_profile_object(reply)


@pytest.mark.parametrize("reply", [{"a": 1}, {"x": PROFILE, "y": PROFILE}])
def test_an_object_that_is_not_clearly_wrapped_is_left_for_the_caller_to_fill_in(reply):
    # the caller fills bio/persona from the entity summary when they are missing
    assert OasisProfileGenerator._as_profile_object(reply) == reply


def test_a_list_reply_gives_the_model_persona_not_the_rule_based_one(monkeypatch):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.client, generator.model_name = object(), "m"
    monkeypatch.setattr(generator, "_is_individual_entity", lambda _t: False)
    monkeypatch.setattr(generator, "_build_group_persona_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(generator, "_get_system_prompt", lambda _i: "system")
    reply = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps([PROFILE])))])
    monkeypatch.setattr(module, "create_chat_completion", lambda *a, **k: reply)
    monkeypatch.setattr(generator, "_generate_profile_rule_based", lambda *a, **k: pytest.fail("fell back to rules"))

    result = generator._generate_profile_with_llm("Granules India", "Company", "summary", {}, "context")
    assert result["persona"] == PROFILE["persona"] and result["bio"] == PROFILE["bio"]
