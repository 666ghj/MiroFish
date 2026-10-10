import logging
from types import SimpleNamespace

import pytest

from app import create_app
from app.api import report as report_api
from app.services.report_agent import ReportAgent, ReportOutline, ReportSection
from app.utils.llm_client import LLMClient, LLMResponseError
from app.utils.locale import t

TRUNCATION_REASON = "LLM text output was truncated at the token limit"


class CompletionSequence:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _response(content, *, finish_reason="stop", include_choice=True):
    choices = []
    if include_choice:
        choices.append(
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        )
    return SimpleNamespace(choices=choices)


def _client_for(sequence):
    client = object.__new__(LLMClient)
    client.model = "compatible-model"
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=sequence)
    )
    return client


def _chat(client):
    return client.chat(messages=[{"role": "user", "content": "Write a section"}])


@pytest.fixture
def section_logs(caplog):
    """Capture report_agent logs: its logger deliberately does not propagate."""
    target = logging.getLogger('mirofish.report_agent')
    caplog.set_level(logging.DEBUG, logger='mirofish.report_agent')
    target.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        target.removeHandler(caplog.handler)


def test_chat_reports_truncation_when_content_is_missing():
    # Reasoning models can exhaust the budget before leaving reasoning_content,
    # which returns content=null together with finish_reason="length".
    client = _client_for(CompletionSequence(_response(None, finish_reason="length")))

    with pytest.raises(LLMResponseError) as captured:
        _chat(client)

    assert "truncated" in str(captured.value)
    assert captured.value.finish_reason == "length"


def test_chat_reports_truncation_for_partial_content():
    client = _client_for(
        CompletionSequence(
            _response("Final Answer: the first half of the sec", finish_reason="length")
        )
    )

    with pytest.raises(LLMResponseError) as captured:
        _chat(client)

    assert "truncated" in str(captured.value)
    assert captured.value.finish_reason == "length"


@pytest.mark.parametrize("content", [None, "", "   "])
def test_chat_reports_unexpected_finish_reason_when_the_body_is_empty(content):
    client = _client_for(
        CompletionSequence(_response(content, finish_reason="content_filter"))
    )

    with pytest.raises(LLMResponseError, match="stopped unexpectedly") as captured:
        _chat(client)

    assert captured.value.finish_reason == "content_filter"


@pytest.mark.parametrize("finish_reason", ["end_turn", "eos", "COMPLETE"])
def test_chat_keeps_a_complete_body_with_an_unrecognized_finish_reason(
    finish_reason,
    caplog,
):
    # LLM_BASE_URL accepts any OpenAI-compatible endpoint, and shims report
    # vendor-specific success tokens. A complete body is not the failure mode
    # this guard exists for, so it must survive, with the reason logged.
    client = _client_for(
        CompletionSequence(
            _response("Final Answer: full section body.", finish_reason=finish_reason)
        )
    )

    with caplog.at_level(logging.WARNING, logger="app.utils.llm_client"):
        assert _chat(client) == "Final Answer: full section body."

    assert any(
        f"finish_reason={finish_reason}" in message for message in caplog.messages
    )


def test_chat_json_still_refuses_any_unrecognized_finish_reason():
    # The JSON contract is unchanged: it has a retry, and half an object is
    # worthless, so an unrecognized reason stays fatal even with a body.
    client = _client_for(
        CompletionSequence(_response('{"a": 1}', finish_reason="end_turn"))
    )

    with pytest.raises(LLMResponseError, match="stopped unexpectedly") as captured:
        client.chat_json(messages=[{"role": "user", "content": "Return JSON"}])

    assert captured.value.finish_reason == "end_turn"


@pytest.mark.parametrize(
    "content",
    [None, "", "   ", "<think>still deciding how to answer</think>"],
)
def test_chat_rejects_empty_completion_even_when_finish_reason_is_stop(content):
    client = _client_for(CompletionSequence(_response(content)))

    with pytest.raises(LLMResponseError, match="empty text content") as captured:
        _chat(client)

    assert captured.value.finish_reason == "stop"


def test_chat_reports_missing_choices():
    client = _client_for(CompletionSequence(_response(None, include_choice=False)))

    with pytest.raises(LLMResponseError, match="no choices"):
        _chat(client)


def test_chat_returns_successful_completion_unchanged():
    client = _client_for(
        CompletionSequence(_response("Final Answer: full section body."))
    )

    assert _chat(client) == "Final Answer: full section body."


def test_chat_still_strips_reasoning_wrapper_from_successful_completion():
    client = _client_for(
        CompletionSequence(_response("<think>plan</think>\nFinal Answer: body."))
    )

    assert _chat(client) == "Final Answer: body."


class TruncatedChatClient:
    """Stand-in LLM client whose every completion hits the token limit."""

    def __init__(self):
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        raise LLMResponseError(
            "LLM text output was truncated at the token limit",
            finish_reason="length",
        )


def test_section_generation_degrades_to_an_explicit_failure_notice():
    agent = object.__new__(ReportAgent)
    agent.tools = {}
    agent.report_logger = None
    agent.simulation_requirement = "demo requirement"
    agent.llm = TruncatedChatClient()

    content = agent._generate_section_react(
        section=ReportSection(title="Key findings"),
        outline=ReportOutline(title="Demo report", summary="demo", sections=[]),
        previous_sections=[],
    )

    # The section must not be saved as a silently empty success.
    assert content == t('report.sectionGenFailedContent')
    # Five ReACT iterations plus the force-finish attempt.
    assert agent.llm.calls == 6


TOOL_CALL_TURN = (
    '<tool_call>{"name": "quick_search", "parameters": {"query": "reception"}}</tool_call>'
)


class StubZepTools:
    """Minimal stand-in so a tool turn succeeds without touching Zep."""

    def quick_search(self, **kwargs):
        return SimpleNamespace(to_text=lambda: "fact: the launch was widely discussed")


class SectionCompletions:
    """Replay N successful tool-call turns, then one tail response forever."""

    def __init__(self, *, tool_call_turns, tail):
        self.tool_call_turns = tool_call_turns
        self.tail = tail
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.tool_call_turns:
            return _response(TOOL_CALL_TURN)
        return self.tail

    @property
    def token_caps(self):
        return [call.get("max_tokens") for call in self.calls]


def _section_agent(completions):
    agent = object.__new__(ReportAgent)
    agent.llm = _client_for(completions)
    agent.tools = {}
    agent.report_logger = None
    agent.simulation_requirement = "demo requirement"
    agent.graph_id = "graph-1"
    agent.zep_tools = StubZepTools()
    return agent


def _generate_section(agent):
    return agent._generate_section_react(
        section=ReportSection(title="Key findings"),
        outline=ReportOutline(title="Demo report", summary="demo", sections=[]),
        previous_sections=[],
    )


def test_section_retries_a_truncation_even_after_the_tool_quota_is_met(section_logs):
    # The minimum tool-call quota is already satisfied, so a response that is
    # neither a tool call nor a Final Answer would otherwise be adopted as the
    # section body. A truncated response must take the retry path instead.
    completions = SectionCompletions(
        tool_call_turns=3,
        tail=_response(None, finish_reason="length"),
    )
    agent = _section_agent(completions)

    content = _generate_section(agent)

    assert content == t('report.sectionGenFailedContent')
    # Three tool turns, two more ReACT iterations, then the force-finish turn.
    assert len(completions.calls) == 6
    messages = section_logs.messages
    assert t(
        'report.sectionIterUnusable',
        title="Key findings",
        iteration=4,
        reason=TRUNCATION_REASON,
    ) in messages
    assert t(
        'report.sectionIterUnusable',
        title="Key findings",
        iteration=5,
        reason=TRUNCATION_REASON,
    ) in messages
    assert t(
        'report.sectionForceUnusable',
        title="Key findings",
        reason=TRUNCATION_REASON,
    ) in messages
    # The success-shaped log must not appear for a failed section.
    assert t(
        'report.sectionNoPrefix', title="Key findings", count=3
    ) not in messages
    # chat() raised rather than returning None, so the None diagnosis is wrong
    # here and must not be logged alongside the real reason.
    assert t(
        'report.sectionIterNone', title="Key findings", iteration=4
    ) not in messages


def test_section_drops_the_token_cap_after_a_truncation(section_logs):
    completions = SectionCompletions(
        tool_call_turns=0,
        tail=_response(None, finish_reason="length"),
    )
    agent = _section_agent(completions)

    _generate_section(agent)

    # The first attempt uses the caller's budget; every attempt after the
    # truncation omits it so the provider can use its own output limit.
    assert completions.token_caps[0] == 4096
    assert completions.token_caps[1:] == [None] * (len(completions.calls) - 1)
    assert "max_tokens" not in completions.calls[-1]
    # Announced once, not once per iteration.
    assert section_logs.messages.count(
        t('report.sectionRetryNoTokenCap', title="Key findings")
    ) == 1


def test_section_keeps_the_token_cap_when_truncation_was_not_the_cause(section_logs):
    # An empty body with finish_reason="stop" is unusable, but the output
    # budget is not the reason, so the cap must stay in place.
    completions = SectionCompletions(tool_call_turns=0, tail=_response(None))
    agent = _section_agent(completions)

    content = _generate_section(agent)

    assert content == t('report.sectionGenFailedContent')
    assert completions.token_caps == [4096] * len(completions.calls)
    assert t(
        'report.sectionRetryNoTokenCap', title="Key findings"
    ) not in section_logs.messages


@pytest.mark.parametrize(
    "tail_content",
    [
        "Final Answer:",
        "Final Answer:   \n\n  ",
        '<tool_result>{"fabricated": true}</tool_result>',
    ],
)
def test_section_never_returns_an_empty_body(tail_content, section_logs):
    # These completions are non-empty, so the client accepts them, but the
    # section body they leave behind is empty. They must not be saved as a
    # completed section.
    completions = SectionCompletions(
        tool_call_turns=3,
        tail=_response(tail_content),
    )
    agent = _section_agent(completions)

    content = _generate_section(agent)

    assert content == t('report.sectionGenFailedContent')
    assert t('report.sectionEmptyBody', title="Key findings") in section_logs.messages
    assert t(
        'report.sectionNoPrefix', title="Key findings", count=3
    ) not in section_logs.messages
    assert t(
        'report.sectionGenDone', title="Key findings", count=3
    ) not in section_logs.messages


def test_force_finish_never_returns_an_empty_body(section_logs):
    # No tool turns, so every "Final Answer:" is rejected for an unmet quota
    # and the loop runs out, leaving the force-finish turn to produce the body.
    completions = SectionCompletions(
        tool_call_turns=0,
        tail=_response("Final Answer:"),
    )
    agent = _section_agent(completions)

    content = _generate_section(agent)

    assert content == t('report.sectionGenFailedContent')
    assert len(completions.calls) == 6
    assert t('report.sectionEmptyBody', title="Key findings") in section_logs.messages


def _post_chat(client):
    return client.post(
        "/api/report/chat",
        json={"simulation_id": "sim_1", "message": "what happened?"},
    )


def test_report_chat_api_maps_an_unusable_response_to_502_without_a_traceback(
    monkeypatch,
):
    class StubSimulationManager:
        def get_simulation(self, simulation_id):
            return SimpleNamespace(project_id="proj_1", graph_id="graph-1")

    class StubProjectManager:
        @staticmethod
        def get_project(project_id):
            return SimpleNamespace(
                graph_id="graph-1",
                simulation_requirement="demo requirement",
            )

    class TruncatingAgent:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            raise LLMResponseError(TRUNCATION_REASON, finish_reason="length")

    monkeypatch.setattr(report_api, "SimulationManager", StubSimulationManager)
    monkeypatch.setattr(report_api, "ProjectManager", StubProjectManager)
    monkeypatch.setattr(report_api, "ReportAgent", TruncatingAgent)

    app = create_app()
    app.config.update(TESTING=True)
    response = _post_chat(app.test_client())

    assert response.status_code == 502
    assert response.json["success"] is False
    assert response.json["error"] == TRUNCATION_REASON
    assert "traceback" not in response.json
    assert "Traceback" not in response.get_data(as_text=True)


def test_chat_truncation_error_does_not_echo_partial_model_output():
    partial = "The informant named SENTINEL-SHOULD-NOT-LEAK said that"
    client = _client_for(CompletionSequence(_response(partial, finish_reason="length")))

    with pytest.raises(LLMResponseError) as captured:
        _chat(client)

    assert "SENTINEL-SHOULD-NOT-LEAK" not in str(captured.value)
    assert "SENTINEL-SHOULD-NOT-LEAK" not in repr(captured.value)
