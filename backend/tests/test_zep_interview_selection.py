from types import SimpleNamespace

from app.services.simulation_runner import SimulationRunner
from app.services.zep_tools import ZepToolsService


def _service_with_selection(indices):
    service = object.__new__(ZepToolsService)
    service._llm_client = SimpleNamespace(chat_json=lambda **kwargs: {
        "selected_indices": indices, "reasoning": "Relevant distinct perspectives",
    })
    return service


def test_repeated_model_indices_do_not_duplicate_requests_or_interview_evidence(monkeypatch):
    profiles = [{"realname": "Alice"}, {"realname": "Bob"}]
    service = _service_with_selection([0, 0, 1])
    monkeypatch.setattr(service, "_load_agent_profiles", lambda simulation_id: profiles)
    monkeypatch.setattr(service, "_generate_interview_summary", lambda **kwargs: "summary")
    requested_ids = []

    def interview_batch(**kwargs):
        requested_ids.extend(item["agent_id"] for item in kwargs["interviews"])
        return {"success": True, "result": {"results": {
            f"twitter_{index}": {"response": f"Answer from {profile['realname']}"}
            for index, profile in enumerate(profiles)
        }}}

    monkeypatch.setattr(SimulationRunner, "interview_agents_batch", interview_batch)
    result = service.interview_agents(
        "simulation-1", "Different perspectives", max_agents=2,
        custom_questions=["What is your view?"],
    )

    assert requested_ids == [0, 1]
    assert [interview.agent_name for interview in result.interviews] == ["Alice", "Bob"]
    assert result.interviewed_count == 2


def test_model_indices_are_validated_before_limiting_without_reordering():
    profiles = [{"realname": name} for name in ["Alice", "Bob", "Carol"]]
    service = _service_with_selection([1, "0", None, True, 0, 1.0, 2])

    selected, indices, reasoning = service._select_agents_for_interview(
        profiles, "A discussion", "Background", max_agents=2,
    )

    assert indices == [1, 0]
    assert selected == [profiles[1], profiles[0]]
    assert reasoning == "Relevant distinct perspectives"


def test_valid_distinct_model_selection_keeps_its_order():
    profiles = [{"realname": name} for name in ["Alice", "Bob", "Carol"]]
    service = _service_with_selection([2, 0])

    selected, indices, _ = service._select_agents_for_interview(
        profiles, "A discussion", "Background", max_agents=2,
    )

    assert indices == [2, 0]
    assert selected == [profiles[2], profiles[0]]
