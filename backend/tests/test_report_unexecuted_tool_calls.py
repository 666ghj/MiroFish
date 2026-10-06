import json

import pytest

from app.services.report_agent import (
    ReportAgent,
    ReportOutline,
    ReportSection,
    UnexecutedToolCallError,
)


QUICK_SEARCH = {"name": "quick_search", "parameters": {"query": "public reaction"}}
CALL_JSON = json.dumps(QUICK_SEARCH)


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        return self.responses.pop(0)


def make_agent(responses):
    agent = ReportAgent(
        graph_id="graph",
        simulation_id="sim",
        simulation_requirement="requirement",
        llm_client=ScriptedLLM(responses),
        zep_tools=object(),
    )
    agent.executed = []

    def fake_execute(name, parameters, report_context=""):
        agent.executed.append(name)
        return f"result of {name}"

    agent._execute_tool = fake_execute
    return agent


def generate(agent):
    outline = ReportOutline(title="Report", summary="Summary", sections=[ReportSection(title="S1")])
    return agent._generate_section_react(outline.sections[0], outline, previous_sections=[])


def tool_call(tag_close="</tool_call>"):
    return f"<tool_call>\n{CALL_JSON}\n{tag_close}"


@pytest.mark.parametrize(
    "response",
    [
        tool_call(),
        tool_call("</tool_cal>"),  # the truncated closing tag reported in #599
        tool_call("</tool>"),
        tool_call(""),  # closing tag missing entirely
        "Thought: need data\n" + tool_call("</tool_cal>") + "\nmore text",
    ],
)
def test_parse_tool_calls_tolerates_malformed_closing_tag(response):
    agent = make_agent([])

    assert agent._parse_tool_calls(response) == [QUICK_SEARCH]


def test_parse_tool_calls_handles_nested_parameters():
    call = {"name": "interview_agents", "parameters": {"query": "q", "filters": {"a": {"b": 1}}}}
    agent = make_agent([])

    assert agent._parse_tool_calls(f"<tool_call>{json.dumps(call)}</tool_cal>") == [call]


def test_parse_tool_calls_ignores_broken_json():
    agent = make_agent([])

    assert agent._parse_tool_calls('<tool_call>{"name": "quick_search", </tool_call>') == []


def test_malformed_closing_tag_is_executed_not_saved_as_content():
    # Three tool calls satisfy the minimum, then the model emits a call with a
    # truncated closing tag. Before the fix this was returned as section content.
    agent = make_agent([
        tool_call(),
        tool_call(),
        tool_call(),
        tool_call("</tool_cal>"),
        "Final Answer: real analysis",
    ])

    assert generate(agent) == "real analysis"
    assert agent.executed == ["quick_search"] * 4


def test_unparseable_tool_call_is_rejected_and_model_is_asked_again():
    broken = '<tool_call>{"name": "quick_search", "parameters": </tool_cal>'
    agent = make_agent([tool_call(), tool_call(), tool_call(), broken, "Final Answer: real analysis"])

    assert generate(agent) == "real analysis"
    assert agent.executed == ["quick_search"] * 3
    last_prompt = agent.llm.calls[-1][-1]["content"]
    assert "格式错误" in last_prompt


def test_final_answer_containing_unparseable_tool_call_is_rejected():
    broken = 'Final Answer: <tool_call>{"name": "quick_search" </tool_call>'
    agent = make_agent([tool_call(), tool_call(), tool_call(), broken, "Final Answer: real analysis"])

    assert generate(agent) == "real analysis"


def test_forced_finish_with_unexecuted_tool_call_fails_the_section():
    broken = '<tool_call>{"name": "quick_search", "parameters": </tool_cal>'
    # Five loop iterations plus the forced finish all return an unusable call.
    agent = make_agent([tool_call(), tool_call(), tool_call(), broken, broken, broken])

    with pytest.raises(UnexecutedToolCallError):
        generate(agent)


def test_plain_content_without_prefix_is_still_accepted():
    agent = make_agent([tool_call(), tool_call(), tool_call(), "Plain analysis without a prefix"])

    assert generate(agent) == "Plain analysis without a prefix"
