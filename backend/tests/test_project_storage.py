"""Project saves must preserve the last readable snapshot on write failure."""
import json

import pytest

from app.models import project as storage


def test_failed_save_preserves_previous_project(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.ProjectManager, 'PROJECTS_DIR', str(tmp_path))
    project = storage.ProjectManager.create_project('original')
    meta = tmp_path / project.project_id / 'project.json'
    previous = meta.read_bytes()
    project.name = 'updated'

    def interrupted_dump(value, stream, **kwargs):
        stream.write('{"name":')
        raise OSError('simulated interrupted write')

    monkeypatch.setattr(storage.json, 'dump', interrupted_dump)
    with pytest.raises(OSError, match='interrupted write'):
        storage.ProjectManager.save_project(project)

    assert meta.read_bytes() == previous
    assert storage.ProjectManager.get_project(project.project_id).name == 'original'
    assert sorted(p.name for p in meta.parent.iterdir()) == ['files', 'project.json']


def test_successful_save_replaces_complete_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.ProjectManager, 'PROJECTS_DIR', str(tmp_path))
    project = storage.ProjectManager.create_project('original')
    project.name = 'updated 日本語'
    storage.ProjectManager.save_project(project)
    meta = tmp_path / project.project_id / 'project.json'
    assert json.loads(meta.read_text(encoding='utf-8'))['name'] == project.name
    assert storage.ProjectManager.get_project(project.project_id).name == project.name
    assert sorted(p.name for p in meta.parent.iterdir()) == ['files', 'project.json']
