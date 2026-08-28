from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_history_api_exposes_project_and_task_mutations():
    source = (ROOT / "frontend/src/api/history.js").read_text(encoding="utf-8")

    assert "export function updateHistoryProject" in source
    assert "export function deleteHistoryProject" in source
    assert "export function updateHistoryTask" in source
    assert "export function deleteHistoryTask" in source


def test_history_lists_emit_edit_and_delete_actions():
    projects = (ROOT / "frontend/src/components/HistoryProjectList.vue").read_text(encoding="utf-8")
    tasks = (ROOT / "frontend/src/components/HistoryTaskList.vue").read_text(encoding="utf-8")

    assert "@click=\"$emit('edit', project)\"" in projects
    assert "@click=\"$emit('delete', project)\"" in projects
    assert "@click=\"$emit('edit', task)\"" in tasks
    assert "@click=\"$emit('delete', task)\"" in tasks


def test_history_view_has_confirmation_dialog_and_mutation_handlers():
    source = (ROOT / "frontend/src/views/HistoryView.vue").read_text(encoding="utf-8")

    assert "function requestProjectDelete" in source
    assert "function requestTaskDelete" in source
    assert "function saveEdit" in source
    assert "function confirmDelete" in source
    assert "输入项目名称以确认彻底删除" in source


def test_history_tasks_show_related_project_name_and_id():
    view = (ROOT / "frontend/src/views/HistoryView.vue").read_text(encoding="utf-8")
    tasks = (ROOT / "frontend/src/components/HistoryTaskList.vue").read_text(encoding="utf-8")

    assert "displayTasks" in view
    assert "project_name" in view
    assert "关联项目已删除" in tasks
    assert "task.metadata.project_id" in tasks


def test_project_history_action_does_not_claim_to_resume_work():
    source = (ROOT / "frontend/src/components/HistoryProjectList.vue").read_text(encoding="utf-8")

    assert "打开项目" in source
    assert "继续项目" not in source


def test_project_history_shows_collapsible_file_list():
    source = (ROOT / "frontend/src/components/HistoryProjectList.vue").read_text(encoding="utf-8")

    assert "visibleFiles(project)" in source
    assert "还有 {{ project.files.length - 3 }} 个文件" in source
    assert "展开全部" in source
    assert "收起文件" in source
    assert "暂无关联文件" in source
