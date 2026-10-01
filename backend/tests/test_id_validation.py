"""
安全测试：标识符与文件系统路径校验

覆盖 app.utils.id_validation 提供的中心化校验逻辑，
以及依赖该逻辑的各个模块（ProjectManager / SimulationManager /
SimulationRunner / ReportManager）在收到恶意标识符时的行为。
"""

import os

import pytest

from app.utils.id_validation import (
    InvalidIdentifierError,
    PathContainmentError,
    safe_join,
    validate_ensemble_id,
    validate_graph_id,
    validate_platform_name,
    validate_project_id,
    validate_report_id,
    validate_simulation_id,
)

VALID_IDS = [
    "proj_1234567890ab",
    "sim_test",
    "sim-1",
    "sim-start-failure",
    "report_abc123",
    "old-report",
    "graph-1",
    "a",
    "A" * 128,
]

TRAVERSAL_PAYLOADS = [
    "../secret",
    "..\\secret",
    "../../etc/passwd",
    "a/../../b",
    "/etc/passwd",
    "C:\\Windows\\System32",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "....//....//etc/passwd",
    "sim\x00_id",
    "sim_\u202eid",  # unexpected unicode (RTL override)
    "sim_ïd",  # unexpected unicode
    "",
    "A" * 129,  # oversized
    "sim/id",
    "sim.id",
    ".",
    "..",
]


@pytest.mark.parametrize("value", VALID_IDS)
@pytest.mark.parametrize(
    "validator",
    [
        validate_project_id,
        validate_simulation_id,
        validate_report_id,
        validate_graph_id,
        validate_ensemble_id,
    ],
)
def test_valid_identifiers_pass(validator, value):
    assert validator(value) == value


@pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
@pytest.mark.parametrize(
    "validator",
    [
        validate_project_id,
        validate_simulation_id,
        validate_report_id,
        validate_graph_id,
        validate_ensemble_id,
    ],
)
def test_malicious_identifiers_rejected(validator, payload):
    with pytest.raises(InvalidIdentifierError):
        validator(payload)


@pytest.mark.parametrize("value", [None, 123, ["sim_1"], {"id": "sim_1"}])
def test_non_string_identifiers_rejected(value):
    with pytest.raises(InvalidIdentifierError):
        validate_simulation_id(value)


def test_validate_platform_name_allows_known_platforms():
    assert validate_platform_name("twitter") == "twitter"
    assert validate_platform_name("reddit") == "reddit"


@pytest.mark.parametrize("payload", ["parallel", "../twitter", "twitter; DROP TABLE", "", None])
def test_validate_platform_name_rejects_unknown_platforms(payload):
    with pytest.raises(InvalidIdentifierError):
        validate_platform_name(payload)


def test_safe_join_accepts_path_within_base(tmp_path):
    result = safe_join(str(tmp_path), "sim_test")
    assert result == os.path.join(str(tmp_path), "sim_test")


def test_safe_join_rejects_escape_via_parent_segments(tmp_path):
    base = tmp_path / "simulations"
    base.mkdir()
    with pytest.raises(PathContainmentError):
        safe_join(str(base), "..", "..", "etc", "passwd")


def test_safe_join_rejects_symlink_escape(tmp_path):
    base = tmp_path / "simulations"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    escape_link = base / "escape"
    escape_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathContainmentError):
        safe_join(str(base), "escape")


class TestProjectManagerRejectsMaliciousIds:
    def _manager(self, tmp_path, monkeypatch):
        from app.models import project as project_module

        monkeypatch.setattr(project_module.ProjectManager, "PROJECTS_DIR", str(tmp_path))
        return project_module.ProjectManager

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_get_project_rejects_traversal(self, tmp_path, monkeypatch, payload):
        manager = self._manager(tmp_path, monkeypatch)
        with pytest.raises(InvalidIdentifierError):
            manager.get_project(payload)

    def test_delete_project_traversal_does_not_touch_filesystem_outside_base(
        self, tmp_path, monkeypatch
    ):
        manager = self._manager(tmp_path, monkeypatch)

        # A sibling directory that must survive the attempted attack untouched.
        victim = tmp_path.parent / "victim_dir_outside_projects"
        victim.mkdir(exist_ok=True)
        (victim / "keepme.txt").write_text("still here")

        with pytest.raises(InvalidIdentifierError):
            manager.delete_project("../victim_dir_outside_projects")

        assert (victim / "keepme.txt").exists()

    def test_list_projects_skips_unexpected_directory_names(self, tmp_path, monkeypatch):
        manager = self._manager(tmp_path, monkeypatch)
        (tmp_path / "..evil").mkdir(parents=True, exist_ok=True)

        # Should not raise even though a bogus directory name is present.
        assert manager.list_projects() == []


class TestSimulationManagerRejectsMaliciousIds:
    def _manager(self, tmp_path):
        from app.services.simulation_manager import SimulationManager

        manager = SimulationManager()
        manager.SIMULATION_DATA_DIR = str(tmp_path)
        return manager

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_get_simulation_dir_rejects_traversal(self, tmp_path, payload):
        manager = self._manager(tmp_path)
        with pytest.raises(InvalidIdentifierError):
            manager._get_simulation_dir(payload)

    def test_list_simulations_skips_unexpected_directory_names(self, tmp_path):
        manager = self._manager(tmp_path)
        (tmp_path / "..evil").mkdir(parents=True, exist_ok=True)

        assert manager.list_simulations() == []


class TestSimulationRunnerRejectsMaliciousIds:
    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_get_sim_dir_rejects_traversal(self, tmp_path, monkeypatch, payload):
        from app.services.simulation_runner import SimulationRunner

        monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
        with pytest.raises(InvalidIdentifierError):
            SimulationRunner._get_sim_dir(payload)


class TestReportManagerRejectsMaliciousIds:
    def _manager(self, tmp_path, monkeypatch):
        from app.services import report_agent as report_agent_module

        monkeypatch.setattr(report_agent_module.ReportManager, "REPORTS_DIR", str(tmp_path))
        return report_agent_module.ReportManager

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_get_report_rejects_traversal(self, tmp_path, monkeypatch, payload):
        manager = self._manager(tmp_path, monkeypatch)
        with pytest.raises(InvalidIdentifierError):
            manager.get_report(payload)

    def test_delete_report_traversal_does_not_touch_filesystem_outside_base(
        self, tmp_path, monkeypatch
    ):
        manager = self._manager(tmp_path, monkeypatch)

        victim = tmp_path.parent / "victim_reports_outside_base"
        victim.mkdir(exist_ok=True)
        (victim / "keepme.txt").write_text("still here")

        with pytest.raises(InvalidIdentifierError):
            manager.delete_report("../victim_reports_outside_base")

        assert (victim / "keepme.txt").exists()

    def test_list_reports_skips_unexpected_directory_names(self, tmp_path, monkeypatch):
        manager = self._manager(tmp_path, monkeypatch)
        (tmp_path / "..evil").mkdir(parents=True, exist_ok=True)

        assert manager.list_reports() == []
