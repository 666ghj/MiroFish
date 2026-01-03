import json
import os

import pytest

from app.config import Config
from app.services.report_agent import (
    Report,
    ReportAgent,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)
from app.utils.llm_client import LLMChatCompletion, LLMToolCall


class _FakeResult:
    def __init__(self, text: str):
        self._text = text

    def to_text(self) -> str:
        return self._text


class _FakeZepTools:
    def __init__(self):
        self.calls = []

    def insight_forge(self, *, graph_id: str, query: str, simulation_requirement: str, report_context: str):
        self.calls.append(("insight_forge", query))
        return _FakeResult(f"[insight_forge] {query}")

    def panorama_search(self, *, graph_id: str, query: str, include_expired: bool = True):
        self.calls.append(("panorama_search", query, include_expired))
        return _FakeResult(f"[panorama_search] {query} include_expired={include_expired}")

    def quick_search(self, *, graph_id: str, query: str, limit: int = 10):
        self.calls.append(("quick_search", query, limit))
        return _FakeResult(f"[quick_search] {query} limit={limit}")

    def interview_agents(
        self,
        *,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int = 20,
        raise_on_failure: bool = False,
    ):
        self.calls.append(("interview_agents", interview_requirement, max_agents))
        return _FakeResult(f"[interview_agents] {interview_requirement} max_agents={max_agents}")


class _FakeLLM:
    def __init__(self):
        self.calls = []
        self._counter = 0

    def chat_completion(self, *, messages, temperature=0.7, max_tokens=4096, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        self._counter += 1

        if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            name = tool_choice.get("function", {}).get("name")
            call_id = f"call_{self._counter}"
            if name == "interview_agents":
                args = {"interview_topic": "topic", "max_agents": 3}
            elif name in {"insight_forge", "panorama_search", "quick_search"}:
                args = {} if name == "insight_forge" else {"query": "q"}
            else:
                args = {"query": "q"}

            return LLMChatCompletion(
                content=None,
                tool_calls=[LLMToolCall(id=call_id, name=name, arguments_json=json.dumps(args))],
            )

        if tool_choice == "none":
            return LLMChatCompletion(content="Final Answer: 这里是最终正文", tool_calls=[])

        return LLMChatCompletion(content="无需工具，直接回答", tool_calls=[])


class _FakeLLMUnknownTool(_FakeLLM):
    def chat_completion(self, *, messages, temperature=0.7, max_tokens=4096, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        self._counter += 1

        call_id = f"call_{self._counter}"
        return LLMChatCompletion(
            content=None,
            tool_calls=[LLMToolCall(id=call_id, name="unknown_tool", arguments_json=json.dumps({"query": "x"}))],
        )


class _FakeZepToolsInterviewFails(_FakeZepTools):
    def interview_agents(
        self,
        *,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int = 20,
        raise_on_failure: bool = False,
    ):
        raise RuntimeError("模拟环境未运行或已关闭，无法执行 Interview")


def _make_outline() -> ReportOutline:
    section = ReportSection(title="第1章", subsections=[])
    return ReportOutline(title="T", summary="S", sections=[section])


def test_generate_section_executes_min_tool_calls_and_returns_body():
    llm = _FakeLLM()
    zep = _FakeZepTools()
    agent = ReportAgent(
        graph_id="g",
        simulation_id="s",
        simulation_requirement="req",
        llm_client=llm,
        zep_tools=zep,
    )

    outline = _make_outline()
    section = outline.sections[0]

    body = agent._generate_section_react(section=section, outline=outline, previous_sections=[], section_index=1)
    assert body == "这里是最终正文"

    # Enforces 2 tool calls (insight_forge then panorama_search)
    assert [c[0] for c in zep.calls[:2]] == ["insight_forge", "panorama_search"]
    assert len(zep.calls) >= 2

    # Tool role messages are appended for subsequent LLM calls
    assert any(m.get("role") == "tool" for m in llm.calls[1]["messages"])


def test_unknown_tool_is_rejected_without_keyerror():
    llm = _FakeLLMUnknownTool()
    zep = _FakeZepTools()
    agent = ReportAgent(
        graph_id="g",
        simulation_id="s",
        simulation_requirement="req",
        llm_client=llm,
        zep_tools=zep,
    )

    outline = _make_outline()
    section = outline.sections[0]

    with pytest.raises(RuntimeError):
        agent._generate_section_react(section=section, outline=outline, previous_sections=[], section_index=1)

    # Unknown tool never executes real zep tools
    assert zep.calls == []

    # The loop still appends a tool message describing the rejection
    assert any(
        m.get("role") == "tool" and "未授权工具" in (m.get("content") or "")
        for m in llm.calls[1]["messages"]
    )


def test_interview_tool_failure_raises_and_blocks_section():
    llm = _FakeLLM()
    zep = _FakeZepToolsInterviewFails()
    agent = ReportAgent(
        graph_id="g",
        simulation_id="s",
        simulation_requirement="req",
        llm_client=llm,
        zep_tools=zep,
    )

    with pytest.raises(RuntimeError):
        agent._execute_tool("interview_agents", {"interview_topic": "t"}, report_context="")


def test_generate_report_resumes_from_existing_sections(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads_dir))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", os.path.join(str(uploads_dir), "reports"))

    report_id = "report_test_resume"
    outline = ReportOutline(
        title="T",
        summary="S",
        sections=[
            ReportSection(title="第1章"),
            ReportSection(title="第2章"),
            ReportSection(title="第3章"),
        ],
    )

    # Prepare a partial report with outline + first two section files already generated.
    ReportManager._ensure_report_folder(report_id)
    ReportManager.save_outline(report_id, outline)

    report = Report(
        report_id=report_id,
        simulation_id="sim_x",
        graph_id="graph_x",
        simulation_requirement="req",
        status=ReportStatus.FAILED,
        created_at="now",
    )
    report.outline = outline
    ReportManager.save_report(report)

    outline.sections[0].content = "已完成章节1"
    ReportManager.save_section_with_subsections(report_id, 1, outline.sections[0], [])

    outline.sections[1].content = "已完成章节2"
    ReportManager.save_section_with_subsections(report_id, 2, outline.sections[1], [])

    assert not os.path.exists(os.path.join(ReportManager.REPORTS_DIR, report_id, "section_03.md"))

    llm = _FakeLLM()
    zep = _FakeZepTools()
    agent = ReportAgent(
        graph_id="graph_x",
        simulation_id="sim_x",
        simulation_requirement="req",
        llm_client=llm,
        zep_tools=zep,
    )

    resumed = agent.generate_report(report_id=report_id)
    assert resumed.status == ReportStatus.COMPLETED
    assert os.path.exists(os.path.join(ReportManager.REPORTS_DIR, report_id, "section_03.md"))

    with open(os.path.join(ReportManager.REPORTS_DIR, report_id, "section_01.md"), "r", encoding="utf-8") as f:
        assert "已完成章节1" in f.read()
