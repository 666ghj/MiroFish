"""Tests d'aïllament de projectes per user_id."""
import pytest


@pytest.fixture(autouse=True)
def _db(in_memory_db):
    pass


def _make_user(email, role='user'):
    from backend.app.models.db_models import UserModel
    from backend.app.db import get_session
    with get_session() as db:
        user = UserModel(email=email, name=email, role=role, status='active')
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def test_list_projects_filtered_by_user():
    from backend.app.models.project import ProjectManager
    uid1 = _make_user('u1@test.com')
    uid2 = _make_user('u2@test.com')

    ProjectManager.create_project(name="U1-A", user_id=uid1)
    ProjectManager.create_project(name="U1-B", user_id=uid1)
    ProjectManager.create_project(name="U2-A", user_id=uid2)

    u1_projects = ProjectManager.list_projects(user_id=uid1)
    assert len(u1_projects) == 2
    assert all(p['user_id'] == uid1 for p in u1_projects)

    u2_projects = ProjectManager.list_projects(user_id=uid2)
    assert len(u2_projects) == 1
    assert u2_projects[0]['name'] == 'U2-A'


def test_list_projects_no_filter_returns_all():
    from backend.app.models.project import ProjectManager
    uid1 = _make_user('all1@test.com')
    uid2 = _make_user('all2@test.com')
    ProjectManager.create_project(name="P1", user_id=uid1)
    ProjectManager.create_project(name="P2", user_id=uid2)
    all_projects = ProjectManager.list_projects(user_id=None)
    assert len(all_projects) >= 2


def test_create_project_assigns_user_id():
    from backend.app.models.project import ProjectManager
    uid = _make_user('owner@test.com')
    proj = ProjectManager.create_project(name="Owned", user_id=uid)
    assert proj['user_id'] == uid


def test_to_dict_includes_user_id():
    from backend.app.models.project import ProjectManager
    uid = _make_user('dict@test.com')
    proj = ProjectManager.create_project(name="DictTest", user_id=uid)
    assert 'user_id' in proj
    assert proj['user_id'] == uid
