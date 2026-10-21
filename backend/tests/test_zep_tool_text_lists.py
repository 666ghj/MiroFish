import json
from types import SimpleNamespace

import pytest

from app.services.simulation_runner import SimulationRunner
from app.services.zep_tools import ZepToolsService
from app.utils.llm_client import LLMClient


def _service_with_model_json(payload):
    llm = object.__new__(LLMClient)
    llm._create_completion = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=json.dumps(payload)),
    )])
    service = object.__new__(ZepToolsService)
    service._llm_client = llm
    return service


def test_insight_filters_unusable_queries_before_applying_the_limit():
    service = _service_with_model_json({"sub_queries": [None, {}, "", "  Useful question  "]})
    searched_queries = []

    def search(**kwargs):
        searched_queries.append(kwargs["query"])
        return SimpleNamespace(edges=[], nodes=[])

    service.client = SimpleNamespace(graph=SimpleNamespace(search=search))
    result = service.insight_forge("graph-1", "Original question", "Context", max_sub_queries=1)

    assert result.sub_queries == ["Useful question"]
    assert searched_queries == ["Useful question", "Original question"]


def test_insight_uses_existing_fallback_for_a_scalar_query_field():
    service = _service_with_model_json({"sub_queries": "Not an array"})
    searched_queries = []

    def search(**kwargs):
        searched_queries.append(kwargs["query"])
        return SimpleNamespace(edges=[], nodes=[])

    service.client = SimpleNamespace(graph=SimpleNamespace(search=search))
    result = service.insight_forge("graph-1", "Original question", "Context", max_sub_queries=1)

    assert result.sub_queries == ["Original question"]
    assert searched_queries == ["Original question", "Original question"]


@pytest.mark.parametrize("questions", [None, "A scalar question", [None, {}, "", "  What changed?  "]])
def test_interviews_receive_real_questions_instead_of_null_characters_or_objects(monkeypatch, questions):
    service = _service_with_model_json({"questions": questions})
    profiles = [{"realname": "Alice", "profession": "Student"}]
    monkeypatch.setattr(service, "_load_agent_profiles", lambda simulation_id: profiles)
    monkeypatch.setattr(service, "_select_agents_for_interview", lambda **kwargs: (
        profiles, [0], "Relevant perspective",
    ))
    monkeypatch.setattr(service, "_generate_interview_summary", lambda **kwargs: "Summary")
    prompts = []

    def interview_batch(**kwargs):
        prompts.extend(item["prompt"] for item in kwargs["interviews"])
        return {"success": True, "result": {"results": {
            "twitter_0": {"response": "A real answer"},
        }}}

    monkeypatch.setattr(SimulationRunner, "interview_agents_batch", interview_batch)
    result = service.interview_agents("simulation-1", "The discussion")

    assert result.interviewed_count == 1
    assert all(isinstance(question, str) and question.strip() for question in result.interview_questions)
    if isinstance(questions, list):
        assert result.interview_questions == ["What changed?"]
        assert "1. What changed?" in prompts[0]
    else:
        assert len(result.interview_questions) == 3
        assert all(len(question) > 1 for question in result.interview_questions)


def test_valid_generated_lists_preserve_model_order():
    service = _service_with_model_json({"sub_queries": ["Second perspective", "First perspective"]})
    assert service._generate_sub_queries("Question", "Context", max_queries=2) == [
        "Second perspective", "First perspective",
    ]
    service = _service_with_model_json({"questions": ["Second question?", "First question?"]})
    assert service._generate_interview_questions("Topic", "Context", []) == [
        "Second question?", "First question?",
    ]
