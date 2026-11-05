from datetime import datetime

import pytest
from flask import Flask
from zep_cloud.core.api_error import ApiError

from app.api import graph as graph_api
from app.models.project import Project, ProjectStatus
from app.models.task import TaskStatus


@pytest.mark.parametrize('status', [401, 403])
def test_graph_auth_failure_preserves_ontology_and_returns_actionable_error(monkeypatch, status):
    now = datetime.now().isoformat()
    project = Project('auth-project', 'Test', ProjectStatus.ONTOLOGY_GENERATED, now, now,
                      ontology={'entity_types': [], 'edge_types': []})
    updates = []
    created = []
    threads = []

    class Tasks:
        def create_task(self, description):
            return 'auth-task'

        def update_task(self, task_id, **kwargs):
            updates.append(kwargs)

    class Builder:
        def __init__(self, **kwargs):
            pass

        def validate_batch_chunks(self, *args, **kwargs):
            pass

        def create_graph(self, **kwargs):
            created.append('graph attempt')
            raise ApiError(status_code=status, headers={'private-header': 'private-value'}, body='PRIVATE-PROVIDER-BODY')

    class Thread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            threads.append(self.target)

    monkeypatch.setattr(graph_api.Config, 'ZEP_API_KEY', 'test-only-key')
    monkeypatch.setattr(graph_api, 'TaskManager', Tasks)
    monkeypatch.setattr(graph_api, 'GraphBuilderService', Builder)
    monkeypatch.setattr(graph_api.threading, 'Thread', Thread)
    monkeypatch.setattr(graph_api.ProjectManager, 'get_project', lambda *a: project)
    monkeypatch.setattr(graph_api.ProjectManager, 'get_extracted_text', lambda *a: 'Test source text.')
    monkeypatch.setattr(graph_api.ProjectManager, 'save_project', lambda *a: None)
    monkeypatch.setattr(graph_api, 'OntologyGenerator', lambda: pytest.fail('Retry must not regenerate ontology'))

    app = Flask(__name__)
    for attempt in range(2):
        with app.test_request_context('/api/graph/build', method='POST', json={'project_id': project.project_id}, headers={'Accept-Language': 'en'}):
            response = graph_api.build_graph()
        threads.pop(0)()
        assert response.status_code == 200
        assert project.status == ProjectStatus.FAILED
        assert project.ontology == {'entity_types': [], 'edge_types': []}
        assert project.graph_id is None
        assert 'Zep Cloud' in project.error
        assert 'ZEP_API_KEY' in project.error
        assert 'PRIVATE-PROVIDER-BODY' not in project.error
        assert 'private-header' not in project.error
        assert updates[-1]['status'] == TaskStatus.FAILED
        assert updates[-1]['error'] == project.error
        assert 'Traceback' not in updates[-1]['error']
    assert len(created) == 2
