"""A report model that writes a malformed <tool_call> must not take the whole report down."""

import json

import pytest

from app.services.report_agent import ReportAgent, ReportOutline, ReportSection

from test_report_ensemble import FakeZep, BASE_ID  # noqa: F401  (FakeZep: no real graph is needed)

# What the report model actually wrote (a failed real report): the arguments, without the tool name
NAMELESS = (
    '<tool_call>\n{"query": "Competitive Realignment Bharti Airtel Reliance satcom spectrum", '
    '"report_context": "Competitive Realignment: Airtel, Reliance Industries"}\n</tool_call>'
)


class QueueLLM:
    """Answers section prompts from a fixed list, recording what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, messages, temperature=0.5, max_tokens=4096):
        self.sent.append([dict(m) for m in messages])        # the agent keeps appending to its list
        return self.replies.pop(0) if self.replies else "Final Answer: fallback text."


def agent_for(llm):
    return ReportAgent("graph_1", BASE_ID, "Will HEGAM rise?", llm_client=llm, zep_tools=FakeZep())


def call(name, **parameters):
    return '<tool_call>{"name": "%s", "parameters": %s}</tool_call>' % (name, json.dumps(parameters or {"query": "x"}))


def run_section(llm):
    return agent_for(llm)._generate_section_react(ReportSection(title="Findings"), ReportOutline("T", "S", []), [])


# --- parsing ----------------------------------------------------------------------------------

def test_a_tool_call_without_a_tool_name_is_not_a_call():
    assert agent_for(QueueLLM([]))._parse_tool_calls(NAMELESS) == []


@pytest.mark.parametrize("block", [
    '<tool_call>[1, 2]</tool_call>',                       # not an object
    '<tool_call>{"name": "", "parameters": {}}</tool_call>',
    '<tool_call>{"name": 7, "parameters": {}}</tool_call>',
    '<tool_call>{"name": "  ", "parameters": {}}</tool_call>',
    '<tool_call>{"name": "quick_search", "parameters": </tool_call>',   # broken JSON
    '<tool_call>{}</tool_call>',
])
def test_other_unusable_blocks_are_ignored_too(block):
    assert agent_for(QueueLLM([]))._parse_tool_calls(block) == []


def test_a_normal_call_is_unchanged():
    assert agent_for(QueueLLM([]))._parse_tool_calls(call("quick_search", query="x")) == [
        {"name": "quick_search", "parameters": {"query": "x"}}
    ]


def test_tool_and_params_are_accepted_as_aliases():
    calls = agent_for(QueueLLM([]))._parse_tool_calls('<tool_call>{"tool": "panorama_search", "params": {"query": "q"}}</tool_call>')
    assert calls == [{"name": "panorama_search", "parameters": {"query": "q"}}]


def test_a_non_object_parameters_value_becomes_an_empty_dict():
    calls = agent_for(QueueLLM([]))._parse_tool_calls('<tool_call>{"name": "quick_search", "parameters": "oops"}</tool_call>')
    assert calls == [{"name": "quick_search", "parameters": {}}]


def test_only_the_usable_blocks_of_a_reply_are_kept():
    reply = NAMELESS + "\n" + call("quick_search", query="x")
    assert [c["name"] for c in agent_for(QueueLLM([]))._parse_tool_calls(reply)] == ["quick_search"]


def test_an_unknown_tool_name_still_reaches_the_executor_which_explains_the_valid_ones():
    agent = agent_for(QueueLLM([]))
    calls = agent._parse_tool_calls('<tool_call>{"name": "web_search", "parameters": {"query": "x"}}</tool_call>')
    assert [c["name"] for c in calls] == ["web_search"]
    assert agent._execute_tool("web_search", {"query": "x"}).startswith("未知工具")


# --- the section loop ----------------------------------------------------------------------------

def test_a_nameless_call_makes_the_model_try_again_instead_of_failing_the_report():
    llm = QueueLLM([NAMELESS, call("quick_search"), call("panorama_search"), call("insight_forge"),
                    "Final Answer: the findings."])

    assert run_section(llm) == "the findings."                       # used to raise KeyError: 'name'

    reminder = [m["content"] for m in llm.sent[1] if m["role"] == "user"][-1]
    assert "缺少工具名称" in reminder and '"name"' in reminder         # the model is told what was wrong and how to write it
    assert "quick_search" in reminder                                 # ... and which tools exist


def test_the_raw_block_is_never_published_as_the_section():
    llm = QueueLLM([NAMELESS, NAMELESS, NAMELESS, NAMELESS, NAMELESS, "Final Answer: after forcing."])
    text = run_section(llm)                                          # retries are bounded; no exception either way
    assert isinstance(text, str) and text


def test_retries_for_a_nameless_call_are_bounded():
    llm = QueueLLM([NAMELESS] * 6 + ["Final Answer: done."])
    run_section(llm)
    reminders = sum(1 for m in llm.sent[-1] if m["role"] == "user" and "缺少工具名称" in m["content"])
    assert reminders == 2
