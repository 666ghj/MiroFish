from app.services.simulation_runner import SimulationRunner
from app.services.zep_tools import ZepToolsService


def _interview_result(monkeypatch, platform_results):
    profiles = [{"realname": "Alice"}, {"realname": "Bob"}]
    service = object.__new__(ZepToolsService)
    monkeypatch.setattr(service, "_load_agent_profiles", lambda simulation_id: profiles)
    monkeypatch.setattr(service, "_select_agents_for_interview", lambda **kwargs: (
        profiles, [0, 1], "Two perspectives",
    ))
    summarized_names = []

    def summarize(**kwargs):
        summarized_names.extend(interview.agent_name for interview in kwargs["interviews"])
        return "Summary of actual answers"

    monkeypatch.setattr(service, "_generate_interview_summary", summarize)
    monkeypatch.setattr(SimulationRunner, "interview_agents_batch", lambda **kwargs: {
        "success": True, "result": {"results": platform_results},
    })
    result = service.interview_agents(
        "simulation-1", "Different perspectives", custom_questions=["What is your view?"],
    )
    return result, summarized_names


def test_missing_or_blank_platform_answers_do_not_become_interview_evidence(monkeypatch):
    result, summarized_names = _interview_result(monkeypatch, {
        "twitter_0": {"error": "Unavailable"},
        "reddit_0": {"response": None},
        "twitter_1": {"response": " \n\t "},
    })

    assert len(result.selected_agents) == 2
    assert result.interviewed_count == 0
    assert result.interviews == []
    assert summarized_names == []
    assert result.summary


def test_only_agents_with_answers_are_counted_and_summarized(monkeypatch):
    result, summarized_names = _interview_result(monkeypatch, {
        "twitter_0": {"response": "Alice's actual answer"},
        "reddit_0": {"error": "Unavailable"},
        "reddit_1": {"response": None},
    })

    assert result.interviewed_count == 1
    assert [interview.agent_name for interview in result.interviews] == ["Alice"]
    assert "Alice's actual answer" in result.interviews[0].response
    assert summarized_names == ["Alice"]


def test_answers_on_either_platform_remain_valid_interviews(monkeypatch):
    result, summarized_names = _interview_result(monkeypatch, {
        "twitter_0": {"response": "Alice's answer"},
        "reddit_1": {"response": "Bob's answer"},
    })

    assert result.interviewed_count == 2
    assert summarized_names == ["Alice", "Bob"]
    assert "Bob's answer" in result.interviews[1].response
