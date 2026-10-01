"""Focused subprocess coverage for environment-first secret handling."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
ENV_FILE = ROOT / ".env"


class EnvironmentFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env_file = ENV_FILE.read_bytes() if ENV_FILE.exists() else None

    def tearDown(self) -> None:
        if self.original_env_file is None:
            ENV_FILE.unlink(missing_ok=True)
        else:
            ENV_FILE.write_bytes(self.original_env_file)

    def run_config(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        process_env.update(env)
        process_env["PYTHONPATH"] = str(BACKEND)
        return subprocess.run(
            [sys.executable, "-c", "import importlib.util; from pathlib import Path; spec = importlib.util.spec_from_file_location('config_under_test', Path('app/config.py')); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); Config = module.Config; print(Config.LLM_API_KEY); print(Config.ZEP_API_KEY); print('|'.join(Config.validate()))"],
            cwd=BACKEND,
            env=process_env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_injected_values_win_over_local_env(self) -> None:
        ENV_FILE.write_text("LLM_API_KEY=file-llm\nZEP_API_KEY=file-zep\n")
        completed = self.run_config({"LLM_API_KEY": "injected-llm", "ZEP_API_KEY": "injected-zep"})
        self.assertEqual(completed.stdout.splitlines(), ["injected-llm", "injected-zep", ""])

    def test_required_literal_op_reference_is_rejected(self) -> None:
        ENV_FILE.write_text("LLM_API_KEY=op://Thrivbe-Core/Example/credential\nZEP_API_KEY=valid-zep\n")
        completed = self.run_config({"ZEP_API_KEY": "injected-zep"})
        self.assertIn("LLM_API_KEY contains an unresolved 1Password reference", completed.stdout)

    def test_upstream_zep_url_rejection_and_debug_warning_are_preserved(self) -> None:
        completed = self.run_config({
            "LLM_API_KEY": "injected-llm",
            "ZEP_API_KEY": "injected-zep",
            "ZEP_API_URL": "https://unsupported.example",
            "FLASK_DEBUG": "true",
        })
        self.assertIn("ZEP_API_URL 不受支持", completed.stdout)
        self.assertIn("Flask DEBUG mode is enabled", completed.stderr)

    def test_direct_scripts_share_the_unresolved_reference_guard(self) -> None:
        ENV_FILE.write_text("LLM_API_KEY=op://Thrivbe-Core/Example/credential\n")
        for name in ("run_twitter_simulation.py", "run_reddit_simulation.py", "run_parallel_simulation.py"):
            completed = subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / name), "--help"],
                cwd=BACKEND,
                env={**os.environ, "PYTHONPATH": str(BACKEND)},
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0, name)
            self.assertIn("unresolved 1Password reference", completed.stderr, name)


if __name__ == "__main__":
    unittest.main()
