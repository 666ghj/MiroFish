from datetime import datetime

from flask import Flask

from app.api import graph as graph_api
from app.models.project import Project, ProjectStatus
from app.models.task import TaskStatus


def _json_result(result):
    if isinstance(result, tuple):
        response, status = result
    else:
        response, status = result, result.status_code
    return response.get_json(), status


def test_update_project_name_endpoint_only_accepts_name(monkeypatch):
    project = Project(
        project_id="proj-1",
        name="新名称",
        status=ProjectStatus.CREATED,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        simulation_requirement="原始需求",
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "update_project_name",
        classmethod(lambda _cls, project_id, name: project),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/project/proj-1",
        method="PATCH",
        json={"name": "新名称", "simulation_requirement": "恶意修改"},
    ):
        body, status = _json_result(graph_api.update_project("proj-1"))

    assert status == 200
    assert body["data"]["name"] == "新名称"
    assert body["data"]["simulation_requirement"] == "原始需求"


def test_task_display_update_and_terminal_delete_endpoints(monkeypatch):
    calls = []

    class Tasks:
        def get_task(self, task_id):
            return type(
                "Task",
                (),
                {
                    "status": TaskStatus.COMPLETED,
                    "to_dict": lambda self: {"task_id": task_id},
                },
            )()

        def update_display(self, task_id, task_type, note):
            calls.append(("update", task_id, task_type, note))
            return True

        def delete_task(self, task_id):
            calls.append(("delete", task_id))
            return True

    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    app = Flask(__name__)

    with app.test_request_context(
        "/api/graph/task/task-1",
        method="PATCH",
        json={"task_type": "新任务名", "note": "备注"},
    ):
        body, status = _json_result(graph_api.update_task_display("task-1"))
    assert status == 200
    assert body["success"] is True

    with app.test_request_context("/api/graph/task/task-1", method="DELETE"):
        body, status = _json_result(graph_api.delete_task("task-1"))
    assert status == 200
    assert calls == [
        ("update", "task-1", "新任务名", "备注"),
        ("delete", "task-1"),
    ]


def test_running_task_delete_endpoint_is_rejected(monkeypatch):
    class Tasks:
        def get_task(self, task_id):
            return type("Task", (), {"status": TaskStatus.PROCESSING})()

    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    app = Flask(__name__)
    with app.test_request_context("/api/graph/task/task-1", method="DELETE"):
        body, status = _json_result(graph_api.delete_task("task-1"))

    assert status == 409
    assert "运行中" in body["error"]


def test_project_delete_is_rejected_when_any_related_task_is_running(monkeypatch):
    project = Project(
        project_id="proj-1",
        name="项目",
        status=ProjectStatus.GRAPH_COMPLETED,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )

    class Tasks:
        def list_tasks(self, **_kwargs):
            return [{
                "status": "processing",
                "metadata": {"project_id": "proj-1"},
            }]

    monkeypatch.setattr(graph_api, "TaskManager", Tasks)
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(graph_api, "_project_has_active_build", lambda _project: False)
    app = Flask(__name__)
    with app.test_request_context("/api/graph/project/proj-1", method="DELETE"):
        body, status = _json_result(graph_api.delete_project("proj-1"))

    assert status == 409
    assert "运行中" in body["error"]
