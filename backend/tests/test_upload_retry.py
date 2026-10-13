from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from unittest.mock import Mock

import pytest
from flask import Flask

from app.api import graph as api
from app.models.project import ProjectManager


@pytest.fixture
def upload(monkeypatch, tmp_path):
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    parser = Mock(return_value='Saved document text')
    generator = Mock(return_value={'entity_types': [{'name': 'Person'}], 'edge_types': []})
    monkeypatch.setattr(api.FileParser, 'extract_text', parser)
    monkeypatch.setattr(api.OntologyGenerator, 'generate', generator)
    app = Flask(__name__)

    def post(upload_id='upload-1'):
        data = {'files': (BytesIO(b'document'), 'document.txt'),
                'simulation_requirement': 'Predict the discussion'}
        if upload_id is not None:
            data['upload_id'] = upload_id
        with app.test_request_context('/ontology/generate', method='POST', data=data):
            result = api.generate_ontology()
            response, status = result if isinstance(result, tuple) else (result, 200)
            return response.get_json(), status

    return post, parser, generator


def test_retry_after_lost_success_returns_same_project_without_parsing_or_llm(upload):
    post, parser, generator = upload
    first, status = post()
    assert status == 200
    second, status = post()
    assert status == 200
    assert second['data']['project_id'] == first['data']['project_id']
    assert second['data']['reused'] is True
    assert len(ProjectManager.list_projects()) == 1
    assert ProjectManager.list_projects()[0].upload_id == 'upload-1'
    assert parser.call_count == generator.call_count == 1


def test_retry_after_lost_failure_resumes_saved_text_on_same_project(upload):
    post, parser, generator = upload
    generator.side_effect = [RuntimeError('Provider temporarily unavailable'),
                             {'entity_types': [], 'edge_types': []}]
    first, status = post()
    assert status == 500
    second, status = post()
    assert status == 200
    assert second['data']['project_id'] == first['data']['project_id']
    assert parser.call_count == 1
    assert generator.call_count == 2
    assert 'Saved document text' in generator.call_args.kwargs['document_texts'][0]
    assert len(ProjectManager.list_projects()) == 1
    assert ProjectManager.list_projects()[0].error is None


def test_different_upload_ids_create_distinct_projects(upload):
    post, parser, generator = upload
    first, _ = post('upload-1')
    second, _ = post('upload-2')
    assert first['data']['project_id'] != second['data']['project_id']
    assert parser.call_count == generator.call_count == 2


def test_parallel_retry_waits_for_existing_upload_claim(upload, monkeypatch):
    post, parser, generator = upload
    generating = Event()
    release = Event()
    second_claim = Event()
    lock_factory = api._project_build_lock
    claims = []

    def lock(project_id):
        if project_id == 'upload:upload-1':
            claims.append(project_id)
            if len(claims) == 2:
                second_claim.set()
        return lock_factory(project_id)

    def generate(**kwargs):
        # The upload identity is on disk before any long provider operation.
        assert ProjectManager.find_project_by_upload_id('upload-1') is not None
        generating.set()
        assert release.wait(5)
        return {'entity_types': [], 'edge_types': []}

    monkeypatch.setattr(api, '_project_build_lock', lock)
    generator.side_effect = generate
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post)
        assert generating.wait(5)
        second = pool.submit(post)
        try:
            assert second_claim.wait(5)
            assert not second.done()
        finally:
            release.set()
        first_body, first_status = first.result(timeout=5)
        second_body, second_status = second.result(timeout=5)
    assert first_status == second_status == 200
    assert first_body['data']['project_id'] == second_body['data']['project_id']
    assert parser.call_count == generator.call_count == 1


@pytest.mark.parametrize('upload_id', ['', '../unsafe', 'x' * 129, 'with spaces'])
def test_invalid_upload_id_is_rejected_before_persistence(upload, upload_id):
    post, parser, generator = upload
    _, status = post(upload_id)
    assert status == 400
    assert ProjectManager.list_projects() == []
    parser.assert_not_called()
    generator.assert_not_called()


def test_legacy_upload_without_key_still_works(upload):
    post, parser, generator = upload
    body, status = post(None)
    assert status == 200
    assert body['data']['project_id']
    assert ProjectManager.list_projects()[0].upload_id is None
