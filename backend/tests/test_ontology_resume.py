from unittest.mock import Mock
from flask import Flask

from app.api import graph as api
from app.models.project import ProjectStatus, Project
from test_zep_graph_lifecycle import _project, _json_result


def test_ontology_resume_reuses_source_and_does_not_upload_or_clear_graph(monkeypatch):
    project = _project(ProjectStatus.FAILED, graph_id=None)
    project.ontology = None
    project.additional_context = 'Use the banking context'
    project.simulation_requirement = 'Model adoption'
    generator = Mock()
    generator.generate.return_value = {'entity_types': [], 'edge_types': [], 'analysis_summary': 'Recovered'}
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.ProjectManager, 'get_extracted_text', lambda _: 'Saved source')
    monkeypatch.setattr(api.ProjectManager, 'save_project', lambda _: None)
    monkeypatch.setattr(api, 'OntologyGenerator', lambda: generator)
    with Flask(__name__).test_request_context('/api/graph/ontology/resume', method='POST', json={'project_id': 'proj-1'}):
        body, status = _json_result(api.resume_ontology())
    assert status == 200
    assert body['data']['project_id'] == 'proj-1'
    assert project.status == ProjectStatus.ONTOLOGY_GENERATED
    assert project.error is None
    generator.generate.assert_called_once_with(document_texts=['Saved source'], simulation_requirement='Model adoption', additional_context='Use the banking context')


def test_ontology_resume_reuses_completed_ontology_without_changing_graph(monkeypatch):
    project = _project(ProjectStatus.GRAPH_COMPLETED)
    generator = Mock()
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api, 'OntologyGenerator', generator)
    with Flask(__name__).test_request_context('/api/graph/ontology/resume', method='POST', json={'project_id': 'proj-1'}):
        body, status = _json_result(api.resume_ontology())
    assert status == 200
    assert body['data']['reused'] is True
    assert project.status == ProjectStatus.GRAPH_COMPLETED
    assert project.graph_id == 'graph-1'
    generator.assert_not_called()


def test_ontology_context_survives_project_serialization():
    project = _project(ProjectStatus.FAILED)
    project.additional_context = 'Remember this context'
    assert Project.from_dict(project.to_dict()).additional_context == 'Remember this context'
