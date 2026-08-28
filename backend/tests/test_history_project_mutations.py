from pathlib import Path

from app.models.project import ProjectManager


def test_project_name_can_be_updated_without_changing_requirement(monkeypatch, tmp_path):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    project = ProjectManager.create_project("旧名称")
    project.simulation_requirement = "保持不变的模拟需求"
    ProjectManager.save_project(project)

    updated = ProjectManager.update_project_name(project.project_id, "新名称")

    assert updated.name == "新名称"
    assert updated.simulation_requirement == "保持不变的模拟需求"


def test_project_name_rejects_blank_value(monkeypatch, tmp_path):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    project = ProjectManager.create_project("原名称")

    try:
        ProjectManager.update_project_name(project.project_id, "   ")
    except ValueError as error:
        assert str(error) == "项目名称不能为空"
    else:
        raise AssertionError("空项目名称应被拒绝")

    assert Path(ProjectManager._get_project_meta_path(project.project_id)).exists()
