from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.config import Config
from app.services.report_agent import (
    ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
    build_run_summary,
)
from app.services.simulation_runner import RunnerStatus


def run_state(**overrides):
    values = dict(
        runner_status=RunnerStatus.STOPPED, current_round=3, total_rounds=12,
        planned_full_rounds=24, simulation_effort='moderate', stop_requested=True,
        twitter_current_round=3, reddit_current_round=2,
        twitter_actions_count=8, reddit_actions_count=5,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    result = ReportAgent(
        'graph_partial', 'sim_partial', 'Original scenario requirement',
        llm_client=Mock(), zep_tools=Mock(), run_summary=build_run_summary(run_state()),
    )
    result.plan_outline = Mock(return_value=ReportOutline(
        'Observed activity', 'Limited evidence', [ReportSection('Observations')],
    ))
    result._generate_section_react = Mock(return_value='Only observed agent activity.')
    return result


def test_partial_coverage_survives_storage_and_download_assembly(agent):
    report = agent.generate_report(report_id='report_partial')
    loaded = ReportManager.get_report(report.report_id)
    assert loaded.status == ReportStatus.COMPLETED
    assert loaded.simulation_requirement == 'Original scenario requirement'
    assert loaded.to_dict()['run_summary'] == build_run_summary(run_state())
    markdown = Path(ReportManager._get_report_markdown_path(report.report_id)).read_text()
    assert markdown == loaded.markdown_content
    assert markdown.count('Partial simulation: stopped before natural completion') == 2
    assert markdown.index('Partial simulation:') < markdown.index('Only observed agent activity.')
    assert 'actual round reached: 3; selected budget: 12 rounds; full planned budget: 24 rounds' in markdown
    assert 'Twitter: 3 rounds, 8 actions. Reddit: 2 rounds, 5 actions.' in markdown


def test_naturally_completed_quick_run_is_reduced_budget_not_stopped(agent):
    agent.run_summary = build_run_summary(run_state(
        runner_status=RunnerStatus.COMPLETED, simulation_effort='quick',
        current_round=4, total_rounds=4, stop_requested=False,
    ))
    report = agent.generate_report(report_id='report_quick')
    assert report.run_summary['stopped_early'] is False
    assert report.run_summary['budget_reduced'] is True
    assert 'Reduced-budget simulation: the selected run completed.' in report.markdown_content
    assert 'Partial simulation:' not in report.markdown_content


def test_partial_report_resume_preserves_coverage_and_completed_section(agent):
    agent.plan_outline.return_value.sections.append(ReportSection('Limits'))
    agent._generate_section_react.side_effect = ['Saved observed activity', RuntimeError('offline')]
    failed = agent.generate_report(report_id='report_partial_resume')
    assert failed.status == ReportStatus.FAILED
    checkpoint = Path(ReportManager._get_section_path(failed.report_id, 1)).read_bytes()
    agent.run_summary = None  # A new process can recover the saved evidence boundary.
    agent.plan_outline.side_effect = AssertionError('must reuse the saved outline')
    agent._generate_section_react.side_effect = None
    agent._generate_section_react.return_value = 'Partial-run limitations'
    agent._generate_section_react.reset_mock()
    resumed = agent.generate_report(report_id=failed.report_id, resume=True)
    assert resumed.status == ReportStatus.COMPLETED
    assert resumed.report_id == failed.report_id
    assert resumed.run_summary == failed.run_summary
    assert resumed.simulation_requirement == failed.simulation_requirement
    assert Path(ReportManager._get_section_path(failed.report_id, 1)).read_bytes() == checkpoint
    agent._generate_section_react.assert_called_once()
    assert 'Partial simulation:' in resumed.markdown_content


def test_zero_activity_report_has_no_forecast_or_llm_calls(agent):
    agent.run_summary = build_run_summary(run_state(
        current_round=0, twitter_current_round=0, reddit_current_round=0,
        twitter_actions_count=0, reddit_actions_count=0,
    ))
    report = agent.generate_report(report_id='report_empty')
    assert report.status == ReportStatus.COMPLETED
    assert report.run_summary['no_agent_activity'] is True
    assert 'No agent activity was recorded' in report.markdown_content
    assert 'source graph material is background context only' in report.markdown_content
    agent.plan_outline.assert_not_called()
    agent._generate_section_react.assert_not_called()
    assert agent.llm.mock_calls == []
    assert agent.zep_tools.mock_calls == []


def test_planning_and_section_prompts_enforce_run_evidence_boundary(agent):
    del agent.plan_outline
    del agent._generate_section_react
    agent.zep_tools.get_simulation_context.return_value = {}
    agent.llm.chat_json.return_value = {
        'title': 'Observed', 'summary': 'Partial', 'sections': [{'title': 'Evidence'}],
    }
    outline = agent.plan_outline()
    planning_prompt = agent.llm.chat_json.call_args.kwargs['messages'][0]['content']
    agent.llm.chat.side_effect = RuntimeError('Captured first section request')
    with pytest.raises(RuntimeError, match='Captured first section request'):
        agent._generate_section_react(outline.sections[0], outline, [])
    section_prompt = agent.llm.chat.call_args.kwargs['messages'][0]['content']
    for prompt in (planning_prompt, section_prompt):
        assert 'SIMULATION EVIDENCE BOUNDARY' in prompt
        assert '"current_round": 3' in prompt
        assert '"stopped_early": true' in prompt
        assert '"planned_full_rounds": 24' in prompt
        assert 'Distinguish source graph background from observed agent activity' in prompt
        assert 'Do not invent reactions, trajectories, consensus, or completion' in prompt
    assert agent.simulation_requirement == 'Original scenario requirement'


@pytest.mark.parametrize('action_count', [0, 8])
def test_stopped_run_is_reportable_after_ingestion_barrier(agent, monkeypatch, action_count):
    from app.api import report as api
    from app.models.project import ProjectStatus

    state = run_state(twitter_actions_count=action_count, reddit_actions_count=0)
    simulation = SimpleNamespace(project_id='project_partial', graph_id=agent.graph_id)
    project = SimpleNamespace(
        graph_id=agent.graph_id, status=ProjectStatus.GRAPH_COMPLETED,
        simulation_requirement=agent.simulation_requirement,
    )
    monkeypatch.setattr(api, 'SimulationManager', lambda: SimpleNamespace(get_simulation=lambda _: simulation))
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.SimulationRunner, 'get_run_state', lambda _: state)
    updater = [object()]
    monkeypatch.setattr(api.ZepGraphMemoryManager, 'get_updater', lambda _: updater[0])
    monkeypatch.setattr(api, '_active_report_tasks', {})
    # Keep the existing strict constructor contract: coverage is passed by property.
    def make_agent(graph_id, simulation_id, simulation_requirement):
        return agent
    monkeypatch.setattr(api, 'ReportAgent', make_agent)
    workers = []
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            workers.append(self.target)
    monkeypatch.setattr(api.threading, 'Thread', Thread)
    app = Flask(__name__)
    with app.test_request_context(json={'simulation_id': agent.simulation_id}):
        blocked, code = api.generate_report()
    assert code == 409
    assert blocked.get_json()['ingestion_pending'] is True
    assert not workers
    updater[0] = None
    with app.test_request_context(json={'simulation_id': agent.simulation_id}):
        response = api.generate_report()
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['run_summary']['stopped_early'] is True
    assert data['run_summary']['total_actions_count'] == action_count
    assert len(workers) == 1
    workers[0]()
    saved = ReportManager.get_report(data['report_id'])
    assert saved.status == ReportStatus.COMPLETED
    assert saved.run_summary['total_actions_count'] == action_count
    assert saved.simulation_requirement == 'Original scenario requirement'
