"""Tests d'integració per als endpoints de projecte de graph.py."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_storage():
    s = MagicMock()
    s.exists.return_value = False
    s.delete_prefix.return_value = None
    return s


@pytest.fixture
def app(in_memory_db, mock_storage):
    """Flask app amb BD en memòria i storage mock.

    in_memory_db ja ha configurat db_module._engine i _SessionLocal.
    Passem un DATABASE_URL de sqlite en memòria perquè create_app() cridi
    init_db() amb el mateix engine; però com que in_memory_db ja ha establert
    els mòduls globals, parchegem init_db per evitar que sobreescrigui l'engine.
    """
    import backend.app.db as db_module

    # Guardem les referències que in_memory_db ja ha configurat
    saved_engine = db_module._engine
    saved_session = db_module._SessionLocal

    def _noop_init_db(url):
        # Restaurem per si create_app() reseteja el mòdul
        db_module._engine = saved_engine
        db_module._SessionLocal = saved_session

    with patch('backend.app.db.init_db', side_effect=_noop_init_db):
        from backend.app import create_app
        application = create_app()

    application.config['TESTING'] = True
    application.extensions['storage'] = mock_storage

    # Assegurem que el mòdul db segueix apuntant a l'engine en memòria
    db_module._engine = saved_engine
    db_module._SessionLocal = saved_session

    return application


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

def test_list_projects_empty(client):
    res = client.get('/api/graph/project/list')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data'] == []
    assert data['count'] == 0


def test_get_project_not_found(client):
    res = client.get('/api/graph/project/nonexistent-id')
    assert res.status_code == 404
    data = res.get_json()
    assert data['success'] is False


def test_create_and_get_project(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="Test Project")
    project_id = proj['project_id']

    res = client.get(f'/api/graph/project/{project_id}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['name'] == 'Test Project'
    assert data['data']['graph_id'] is None
    assert data['data']['ontology'] is None


def test_list_projects_returns_created(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    ProjectManager.create_project(name="Alpha")
    ProjectManager.create_project(name="Beta")

    res = client.get('/api/graph/project/list')
    assert res.status_code == 200
    data = res.get_json()
    assert data['count'] == 2
    names = [p['name'] for p in data['data']]
    assert 'Alpha' in names
    assert 'Beta' in names


def test_delete_project(client, in_memory_db, mock_storage):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="ToDelete")
    project_id = proj['project_id']

    res = client.delete(f'/api/graph/project/{project_id}')
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    res2 = client.get(f'/api/graph/project/{project_id}')
    assert res2.status_code == 404


def test_reset_project_to_created(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="ToReset")
    project_id = proj['project_id']
    ProjectManager.save_project({"id": project_id, "status": "graph_completed"})

    res = client.post(f'/api/graph/project/{project_id}/reset')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['status'] == 'created'  # sense ontologia → torna a 'created'


def test_reset_project_to_ontology_generated(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="ToReset2")
    project_id = proj['project_id']
    ProjectManager.save_project({"id": project_id, "status": "graph_completed"})
    ProjectManager.save_ontology(project_id, [{"name": "Person"}], [{"name": "KNOWS"}])

    res = client.post(f'/api/graph/project/{project_id}/reset')
    assert res.status_code == 200
    data = res.get_json()
    assert data['data']['status'] == 'ontology_generated'


def test_reset_nonexistent_project(client):
    res = client.post('/api/graph/project/nonexistent/reset')
    assert res.status_code == 404
