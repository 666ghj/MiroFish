from unittest.mock import Mock

import pytest

from app.config import Config
from app.services.report_agent import (
    ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    agent = object.__new__(ReportAgent)
    agent.simulation_id = 'sim_resume'
    agent.graph_id = 'graph_resume'
    agent.simulation_requirement = 'Compare the choices'
    agent.report_logger = None
    agent.console_logger = None
    agent.plan_outline = Mock(return_value=ReportOutline(
        title='Decision', summary='Evidence',
        sections=[ReportSection('Demand'), ReportSection('Risks')],
    ))
    return agent


def test_resume_keeps_outline_and_completed_sections_across_instances(agent):
    agent._generate_section_react = Mock(side_effect=['Saved demand evidence', RuntimeError('provider down')])
    failed = agent.generate_report(report_id='report_resume')
    assert failed.status == ReportStatus.FAILED
    section_path = ReportManager._get_section_path('report_resume', 1)
    from pathlib import Path
    before = Path(section_path).read_bytes()

    agent.plan_outline = Mock(side_effect=AssertionError('must reuse outline'))
    agent._generate_section_react = Mock(return_value='Recovered risk evidence')
    result = agent.generate_report(report_id='report_resume', resume=True)

    assert result.status == ReportStatus.COMPLETED
    assert result.error is None
    assert result.report_id == failed.report_id
    assert result.created_at == failed.created_at
    agent._generate_section_react.assert_called_once()
    kwargs = agent._generate_section_react.call_args.kwargs
    assert kwargs['section'].title == 'Risks'
    assert 'Saved demand evidence' in kwargs['previous_sections'][0]
    assert Path(section_path).read_bytes() == before
    assert 'Saved demand evidence' in result.markdown_content
    assert 'Recovered risk evidence' in result.markdown_content


def test_resume_rejects_incompatible_report(agent):
    agent._generate_section_react = Mock(side_effect=RuntimeError('provider down'))
    agent.generate_report(report_id='report_resume')
    agent.graph_id = 'different_graph'
    with pytest.raises(ValueError, match='does not match'):
        agent.generate_report(report_id='report_resume', resume=True)


def test_resume_recovers_section_written_before_meta_update(agent):
    agent._generate_section_react = Mock(side_effect=RuntimeError('provider down'))
    agent.generate_report(report_id='report_resume')
    ReportManager.save_section('report_resume', 1, ReportSection('Demand', 'Durably saved'))
    agent.plan_outline = Mock(side_effect=AssertionError('must reuse outline'))
    agent._generate_section_react = Mock(return_value='Risks recovered')
    result = agent.generate_report(report_id='report_resume', resume=True)
    assert result.status == ReportStatus.COMPLETED
    agent._generate_section_react.assert_called_once()
    assert 'Durably saved' in result.markdown_content


def test_api_resume_reuses_report_and_deduplicates_worker(agent, monkeypatch):
    from types import SimpleNamespace
    from flask import Flask
    from app.api import report as api
    from app.models.project import ProjectStatus
    from app.services.simulation_runner import RunnerStatus
    agent._generate_section_react = Mock(side_effect=['First completed', RuntimeError('down')])
    agent.generate_report(report_id='report_resume')
    simulation = SimpleNamespace(project_id='project', graph_id=agent.graph_id)
    project = SimpleNamespace(graph_id=agent.graph_id, status=ProjectStatus.GRAPH_COMPLETED,
                              simulation_requirement=agent.simulation_requirement)
    monkeypatch.setattr(api, 'SimulationManager', lambda: SimpleNamespace(get_simulation=lambda _: simulation))
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.SimulationRunner, 'get_run_state', lambda _: SimpleNamespace(runner_status=RunnerStatus.COMPLETED))
    monkeypatch.setattr(api.ZepGraphMemoryManager, 'get_updater', lambda _: None)
    monkeypatch.setattr(api, '_active_report_tasks', {})
    workers = []
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            workers.append(self.target)
    monkeypatch.setattr(api.threading, 'Thread', Thread)
    monkeypatch.setattr(api, 'ReportAgent', lambda **kwargs: agent)
    app = Flask(__name__)
    payload = {'simulation_id': agent.simulation_id, 'report_id': 'report_resume', 'resume': True}
    try:
        with app.test_request_context(json=payload):
            first = api.generate_report().get_json()['data']
        with app.test_request_context(json=payload):
            second = api.generate_report().get_json()['data']
        assert first['report_id'] == second['report_id'] == 'report_resume'
        assert first['task_id'] == second['task_id']
        assert len(workers) == 1
        agent.plan_outline = Mock(side_effect=AssertionError('must reuse outline'))
        agent._generate_section_react = Mock(return_value='Second recovered')
        workers[0]()
        assert ReportManager.get_report('report_resume').status == ReportStatus.COMPLETED
        agent._generate_section_react.assert_called_once()
    finally:
        api.unregister_graph_reader(agent.graph_id, 'report_resume')


def test_get_interrupted_report_exposes_recoverable_error(agent, monkeypatch):
    from flask import Flask
    from app.api import report as api
    agent._generate_section_react = Mock(side_effect=RuntimeError('down'))
    report = agent.generate_report(report_id='report_resume')
    report.status = ReportStatus.GENERATING
    ReportManager.save_report(report)
    monkeypatch.setattr(api, '_active_report_tasks', {})
    app = Flask(__name__)
    with app.test_request_context():
        body = api.get_report('report_resume').get_json()['data']
    assert body['status'] == 'failed'
    assert 'interrupted' in body['error']


def test_outline_provider_failure_is_visible_and_retryable(agent):
    del agent.plan_outline
    agent.zep_tools = Mock()
    agent.zep_tools.get_simulation_context.return_value = {}
    agent.llm = Mock()
    agent.llm.chat_json.side_effect = RuntimeError('quota unavailable')
    agent._generate_section_react = Mock(return_value='Would hide failure')
    failed = agent.generate_report(report_id='report_outline')
    assert failed.status == ReportStatus.FAILED
    assert failed.outline is None
    assert 'quota unavailable' in failed.error
    agent._generate_section_react.assert_not_called()
    agent.llm.chat_json.side_effect = None
    agent.llm.chat_json.return_value = {'title': 'Recovered', 'sections': [{'title': 'Evidence'}]}
    result = agent.generate_report(report_id='report_outline', resume=True)
    assert result.status == ReportStatus.COMPLETED
    assert result.outline.title == 'Recovered'
