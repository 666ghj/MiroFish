def test_project_serializes_active_task_id():
    """active_task_id is included in Project.to_dict()."""
    from app.models.project import Project, ProjectStatus
    p = Project(
        project_id="proj-1", name="Test",
        status=ProjectStatus.GRAPH_BUILDING,
        created_at="2026-01-01", updated_at="2026-01-01",
        active_task_id="task-abc-123",
    )
    assert p.to_dict()["active_task_id"] == "task-abc-123"


def test_project_deserializes_active_task_id():
    """Project.from_dict() restores active_task_id from JSON."""
    from app.models.project import Project
    data = {
        "project_id": "proj-1", "name": "Test", "status": "graph_building",
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
        "active_task_id": "task-abc-123",
    }
    assert Project.from_dict(data).active_task_id == "task-abc-123"


def test_project_active_task_id_defaults_none():
    """active_task_id defaults to None for projects without it (backward compat)."""
    from app.models.project import Project
    data = {
        "project_id": "proj-1", "name": "Test", "status": "created",
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
    }
    assert Project.from_dict(data).active_task_id is None
