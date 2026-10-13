from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.api import graph as api
from app.models.project import ProjectStatus
from app.services.graph_builder import GraphBuilderService
from test_zep_graph_lifecycle import _project, _json_result


@pytest.mark.parametrize('batch_status', ['failed', 'draft', 'processing', 'succeeded'])
def test_failed_local_graph_build_reuses_saved_graph_and_batch(monkeypatch, batch_status):
    project = _project(ProjectStatus.FAILED)
    builder = Mock()
    builder.get_batch_summary.return_value = SimpleNamespace(status=batch_status)
    builder.build_operation_id = GraphBuilderService.build_operation_id
    project.zep_batch_operation_id = builder.build_operation_id('graph-1', ['source text'])
    monkeypatch.setattr(api.Config, 'GRAPH_PROVIDER', 'graphiti')
    factory = Mock(return_value=builder)
    factory.validate_batch_chunks = GraphBuilderService.validate_batch_chunks
    factory.build_operation_id = GraphBuilderService.build_operation_id
    monkeypatch.setattr(api, 'GraphBuilderService', factory)
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.ProjectManager, 'get_extracted_text', lambda _: 'source text')
    monkeypatch.setattr(api.ProjectManager, 'save_project', lambda _: None)
    monkeypatch.setattr(api, 'TaskManager', lambda: SimpleNamespace(create_task=lambda _: 'retry-task'))
    monkeypatch.setattr(api.threading, 'Thread', Mock())
    with Flask(__name__).test_request_context('/api/graph/build', method='POST', json={'project_id': 'proj-1'}):
        body, status = _json_result(api.build_graph())
    assert status == 200, body
    assert body['data']['resumed'] is True
    assert project.graph_id == 'graph-1'
    assert project.zep_batch_id == 'batch-1'
    builder.delete_graph.assert_not_called()


def test_service_resumes_only_local_failed_batch(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(provider='graphiti', batch=Mock())
    chunks = ['one', 'two']
    operation = builder.build_operation_id('g1', chunks)
    builder.client.batch.get.return_value = SimpleNamespace(status='failed', metadata={
        'graph_id': 'g1', 'mirofish_operation_id': operation, 'chunk_count': 2})
    submission = builder.resume_text_batch('g1', 'batch-1', operation, chunks)
    builder.client.batch.resume.assert_called_once_with(batch_id='batch-1', operation_id=operation, chunks=chunks)
    assert submission.item_count == 2
    assert submission.batch_id == 'batch-1'


def test_service_rejects_changed_input_before_retry():
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(provider='graphiti', batch=Mock())
    with pytest.raises(ValueError, match='input'):
        builder.resume_text_batch('g1', 'batch-1', 'old-operation', ['changed'])
    builder.client.batch.resume.assert_not_called()


def test_cloud_terminal_failure_is_preserved_without_replay():
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(provider='zep', batch=Mock())
    operation = builder.build_operation_id('g1', ['one'])
    builder.client.batch.get.return_value = SimpleNamespace(status='failed')
    with pytest.raises(RuntimeError, match='does not support'):
        builder.resume_text_batch('g1', 'batch-1', operation, ['one'])
    builder.client.batch.process.assert_not_called()
    builder.client.batch.add.assert_not_called()


@pytest.mark.parametrize('has_batch', [True, False])
def test_recovery_worker_completes_without_recreating_saved_work(monkeypatch, has_batch):
    from app.services.graph_builder import BatchSubmission
    from app.models.task import TaskStatus
    project = _project(ProjectStatus.FAILED)
    project.zep_batch_operation_id = GraphBuilderService.build_operation_id('graph-1', ['source text']) if has_batch else None
    project.zep_batch_id = 'batch-1' if has_batch else None
    builder = Mock()
    builder.build_operation_id = GraphBuilderService.build_operation_id
    builder.get_batch_summary.return_value = SimpleNamespace(status='failed')
    builder.create_graph.return_value = 'graph-1'
    submission = BatchSubmission('batch-1', 'operation', [], 1)
    builder.resume_text_batch.return_value = submission
    builder.add_text_batches.return_value = submission
    builder.get_graph_data.return_value = {'node_count': 4, 'edge_count': 2}
    factory = Mock(return_value=builder)
    factory.validate_batch_chunks = GraphBuilderService.validate_batch_chunks
    factory.build_operation_id = GraphBuilderService.build_operation_id
    tasks = Mock()
    tasks.create_task.return_value = 'retry-task'
    threads = []
    class Thread:
        def __init__(self, target, daemon):
            threads.append(target)
        def start(self):
            pass
    monkeypatch.setattr(api.Config, 'GRAPH_PROVIDER', 'graphiti')
    monkeypatch.setattr(api, 'GraphBuilderService', factory)
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.ProjectManager, 'get_extracted_text', lambda _: 'source text')
    monkeypatch.setattr(api.ProjectManager, 'save_project', lambda _: None)
    monkeypatch.setattr(api, 'TaskManager', lambda: tasks)
    monkeypatch.setattr(api.threading, 'Thread', Thread)
    with Flask(__name__).test_request_context('/api/graph/build', method='POST', json={'project_id': 'proj-1'}):
        body, status = _json_result(api.build_graph())
    assert status == 200, body
    threads[0]()
    assert project.status == ProjectStatus.GRAPH_COMPLETED
    assert project.error is None
    builder.delete_graph.assert_not_called()
    if has_batch:
        builder.create_graph.assert_not_called()
        builder.set_ontology.assert_not_called()
        builder.add_text_batches.assert_not_called()
        builder.resume_text_batch.assert_called_once()
    else:
        assert builder.create_graph.call_args.kwargs['graph_id'] == 'graph-1'
        builder.set_ontology.assert_called_once()
    assert tasks.update_task.call_args.kwargs['status'] == TaskStatus.COMPLETED


def test_cloud_failed_batch_returns_recovery_limit_without_deletion(monkeypatch):
    project = _project(ProjectStatus.FAILED)
    builder = Mock()
    builder.get_batch_summary.return_value = SimpleNamespace(status='partial')
    monkeypatch.setattr(api.Config, 'GRAPH_PROVIDER', 'zep')
    monkeypatch.setattr(api.Config, 'ZEP_API_KEY', 'test-key')
    monkeypatch.setattr(api, 'GraphBuilderService', lambda **kw: builder)
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.ProjectManager, 'save_project', lambda _: None)
    with Flask(__name__).test_request_context('/api/graph/build', method='POST', json={'project_id': 'proj-1'}):
        body, status = _json_result(api.build_graph())
    assert status == 409
    assert body['recoverable'] is True
    assert body['resume_supported'] is False
    assert project.graph_id == 'graph-1'
    assert project.zep_batch_id == 'batch-1'
    builder.delete_graph.assert_not_called()
