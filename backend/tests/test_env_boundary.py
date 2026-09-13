"""Regression coverage for the local 1Password environment boundary."""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


class ConfigEnvironmentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.previous = ENV_FILE.read_bytes() if ENV_FILE.exists() else None
        ENV_FILE.write_text("LLM_API_KEY=op://Test/LLM/credential\nZEP_API_KEY=op://Test/Zep/credential\n")

    def tearDown(self):
        if self.previous is None:
            ENV_FILE.unlink(missing_ok=True)
        else:
            ENV_FILE.write_bytes(self.previous)

    def run_config(self, injected):
        env = os.environ.copy()
        env.update(injected)
        return subprocess.run(
            [sys.executable, "-c", "import importlib.util; from pathlib import Path; spec = importlib.util.spec_from_file_location('boundary_config', Path('backend/app/config.py')); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); Config = module.Config; print(Config.LLM_API_KEY or 'NONE'); print(Config.ZEP_API_KEY or 'NONE'); print('|'.join(Config.validate()))"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

    def test_injected_values_win_over_local_addresses(self):
        self.assertEqual(self.run_config({"LLM_API_KEY": "resolved-llm", "ZEP_API_KEY": "resolved-zep"}), ["resolved-llm", "resolved-zep", ""])

    def test_unresolved_addresses_fail_closed(self):
        self.assertEqual(self.run_config({"LLM_API_KEY": "op://Test/LLM/credential", "ZEP_API_KEY": "op://Test/Zep/credential"}), ["NONE", "NONE", "LLM_API_KEY 未配置|ZEP_API_KEY 未配置"])

    def test_manual_simulation_readers_reject_addresses_before_provider_use(self):
        previous = {name: os.environ.get(name) for name in ("LLM_API_KEY", "LLM_BOOST_API_KEY")}
        os.environ["LLM_API_KEY"] = "op://Test/LLM/credential"
        try:
            for filename, class_name in (
                ("run_twitter_simulation.py", "TwitterSimulationRunner"),
                ("run_reddit_simulation.py", "RedditSimulationRunner"),
                ("run_parallel_simulation.py", None),
            ):
                tree = ast.parse((ROOT / "backend/scripts" / filename).read_text())
                if class_name:
                    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
                    function = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "_create_model")
                    function.args.args = function.args.args[:1]
                    target = function.name
                    args = (SimpleNamespace(config={}),)
                else:
                    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_model")
                    target = function.name
                    args = ({},)
                module = ast.Module(body=[function], type_ignores=[])
                ast.fix_missing_locations(module)
                namespace = {"os": os, "Dict": Dict, "Any": Any}
                exec(compile(module, filename, "exec"), namespace)
                with self.assertRaisesRegex(ValueError, "unresolved 1Password address"):
                    namespace[target](*args)

            # The parallel runner selects a separate boost credential when requested;
            # it must reject that selected reference even with a resolved primary key.
            os.environ["LLM_API_KEY"] = "resolved-primary"
            os.environ["LLM_BOOST_API_KEY"] = "op://Test/Boost/credential"
            tree = ast.parse((ROOT / "backend/scripts/run_parallel_simulation.py").read_text())
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_model")
            module = ast.Module(body=[function], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {"os": os, "Dict": Dict, "Any": Any}
            exec(compile(module, "run_parallel_simulation.py", "exec"), namespace)
            with self.assertRaisesRegex(ValueError, "Selected model API key"):
                namespace["create_model"]({}, True)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
