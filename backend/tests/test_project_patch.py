import pytest
from unittest.mock import patch, MagicMock
from app import create_app


@pytest.fixture
def app():
    return create_app({'TESTING': True})


@pytest.fixture
def client(app):
    return app.test_client()


def test_patch_project_name_success(client):
    mock_project = {"id": "proj_123", "project_id": "proj_123", "name": "Old Name"}
    updated = {**mock_project, "name": "New Name"}
    with patch('app.api.graph.ProjectManager.get_project', side_effect=[mock_project, updated]), \
         patch('app.api.graph.ProjectManager.save_project'):
        resp = client.patch('/api/graph/project/proj_123', json={"name": "New Name"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_patch_project_name_not_found(client):
    with patch('app.api.graph.ProjectManager.get_project', return_value=None):
        resp = client.patch('/api/graph/project/nonexistent', json={"name": "X"})
    assert resp.status_code == 404


def test_patch_project_name_empty_rejected(client):
    mock_project = {"id": "proj_123", "project_id": "proj_123", "name": "Old"}
    with patch('app.api.graph.ProjectManager.get_project', return_value=mock_project):
        resp = client.patch('/api/graph/project/proj_123', json={"name": "   "})
    assert resp.status_code == 400
