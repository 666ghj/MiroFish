import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace


def test_validation_script_preserves_the_process_key_across_app_config_import():
    backend_root = Path(__file__).resolve().parents[1]
    script_path = backend_root / "scripts" / "validate_zep_cloud_integration.py"
    probe = textwrap.dedent(
        f"""
        import os
        import runpy
        import dotenv

        def overwrite_with_dotenv_value(*_args, **_kwargs):
            os.environ["ZEP_API_KEY"] = "dotenv-test-key"
            return True

        dotenv.load_dotenv = overwrite_with_dotenv_value
        namespace = runpy.run_path({str(script_path)!r}, run_name="zep_validation_probe")
        assert namespace["_PROCESS_ZEP_API_KEY"] == "process-test-key"
        assert namespace["_require_process_api_key"]() == "process-test-key"
        assert os.environ["ZEP_API_KEY"] == "process-test-key"
        """
    )
    environment = os.environ.copy()
    environment["ZEP_API_KEY"] = "process-test-key"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(backend_root), environment.get("PYTHONPATH", "")])
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_validation_cleanup_retains_graph_when_updater_cannot_drain(monkeypatch):
    monkeypatch.setenv("ZEP_API_KEY", "validation-test-key")
    from scripts import validate_zep_cloud_integration as validation

    class FailingUpdater:
        def stop(self):
            raise TimeoutError("worker still running")

    updater_drained, error = validation._drain_updater_after_failure(
        FailingUpdater(),
        started=True,
        stop_attempted=False,
    )
    deleted_graphs = []
    client = SimpleNamespace(
        graph=SimpleNamespace(delete=lambda graph_id: deleted_graphs.append(graph_id))
    )
    cleanup = validation._cleanup_graph(
        client,
        "graph-id",
        created=True,
        keep_graph=False,
        updater_started=True,
        updater_drained=updater_drained,
    )

    assert isinstance(error, TimeoutError)
    assert cleanup == {
        "graph_deleted": False,
        "graph_retained": True,
        "reason": "updater_not_confirmed_drained",
    }
    assert deleted_graphs == []


def test_validation_cleanup_deletes_graph_after_confirmed_drain(monkeypatch):
    monkeypatch.setenv("ZEP_API_KEY", "validation-test-key")
    from scripts import validate_zep_cloud_integration as validation

    deleted_graphs = []
    client = SimpleNamespace(
        graph=SimpleNamespace(delete=lambda graph_id: deleted_graphs.append(graph_id))
    )
    cleanup = validation._cleanup_graph(
        client,
        "graph-id",
        created=True,
        keep_graph=False,
        updater_started=True,
        updater_drained=True,
    )

    assert cleanup == {
        "graph_deleted": True,
        "graph_retained": False,
        "reason": "validation_cleanup",
    }
    assert deleted_graphs == ["graph-id"]
