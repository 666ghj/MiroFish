from pathlib import Path


def test_task_list_supports_status_and_bounded_limit():
    root = Path(__file__).resolve().parents[2]
    graph_api = (root / "backend" / "app" / "api" / "graph.py").read_text()

    assert "request.args.get('status')" in graph_api
    assert "request.args.get('limit', 100, type=int)" in graph_api
    assert "TaskStatus(status)" in graph_api
    assert "max(1, min(limit, 500))" in graph_api
    assert "list_tasks(status=status, limit=limit)" in graph_api
    assert '"data": tasks' in graph_api
    assert '[t.to_dict() for t in tasks]' not in graph_api


def test_graph_and_report_tasks_include_project_metadata():
    root = Path(__file__).resolve().parents[2]
    graph_api = (root / "backend" / "app" / "api" / "graph.py").read_text()
    report_api = (root / "backend" / "app" / "api" / "report.py").read_text()

    assert "metadata={'project_id': project_id}" in graph_api
    assert '"project_id": state.project_id' in report_api
