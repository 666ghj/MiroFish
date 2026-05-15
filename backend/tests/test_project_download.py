import pytest
from unittest.mock import patch, MagicMock
from app import create_app


@pytest.fixture
def app():
    return create_app({'TESTING': True})


@pytest.fixture
def client(app):
    return app.test_client()


class TestSourceDownload:
    def test_download_source_returns_file(self, client):
        mock_storage = MagicMock()
        mock_storage.download.return_value = b"%PDF-1.4 fake content"

        with patch('app.api.graph.ProjectManager.get_project', return_value={"id": "p1"}), \
             patch('app.api.graph.ProjectManager._get_project_files',
                   return_value=[{"file_id": "file_001", "filename": "doc.pdf",
                                  "storage_path": "projects/p1/files/doc.pdf",
                                  "mime_type": "application/pdf", "size": 100}]), \
             patch('app.api.graph.get_storage', return_value=mock_storage):
            resp = client.get('/api/graph/project/p1/download/source')

        assert resp.status_code == 200
        assert 'attachment' in resp.headers.get('Content-Disposition', '')

    def test_download_source_not_found(self, client):
        with patch('app.api.graph.ProjectManager.get_project', return_value=None):
            resp = client.get('/api/graph/project/nonexistent/download/source')
        assert resp.status_code == 404

    def test_download_source_no_files(self, client):
        with patch('app.api.graph.ProjectManager.get_project', return_value={"id": "p1"}), \
             patch('app.api.graph.ProjectManager._get_project_files', return_value=[]):
            resp = client.get('/api/graph/project/p1/download/source')
        assert resp.status_code == 404


class TestSimulationDownloads:
    def test_download_log_endpoint_exists(self, client, tmp_path):
        log_file = tmp_path / "actions.jsonl"
        log_file.write_text('{"action": "test"}\n')

        with patch('app.api.simulation._get_simulation_log_path',
                   return_value=str(log_file)):
            resp = client.get('/api/simulation/sim_001/download/log')
        assert resp.status_code == 200

    def test_download_log_not_found(self, client):
        with patch('app.api.simulation._get_simulation_log_path', return_value=""):
            resp = client.get('/api/simulation/sim_001/download/log')
        assert resp.status_code == 404
