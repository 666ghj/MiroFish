"""Keep the copied example usable with only the required API settings filled in."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]


def select_reddit_model(boost_settings=None):
    environment = dict(dotenv_values(ROOT / ".env.example"))
    environment.update(
        LLM_API_KEY="configured-general-key",
        LLM_BASE_URL="https://general.example/v1",
        LLM_MODEL_NAME="configured-general-model",
    )
    environment.update(boost_settings or {})

    # Load the real selector without importing the optional OASIS/CAMEL runtime.
    script = ROOT / "backend/scripts/run_parallel_simulation.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    selector = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_model"
    )

    def record_model(**kwargs):
        return {
            "api_key": environment["OPENAI_API_KEY"],
            "base_url": environment["OPENAI_API_BASE_URL"],
            "model": kwargs["model_type"],
        }

    namespace = {
        "os": SimpleNamespace(environ=environment),
        "Dict": Dict,
        "Any": Any,
        "ModelFactory": SimpleNamespace(create=record_model),
        "ModelPlatformType": SimpleNamespace(OPENAI="openai"),
    }
    exec(compile(ast.Module(body=[selector], type_ignores=[]), str(script), "exec"), namespace)
    return namespace["create_model"]({}, use_boost=True)


def test_required_settings_are_enough_for_the_default_reddit_model():
    assert select_reddit_model() == {
        "api_key": "configured-general-key",
        "base_url": "https://general.example/v1",
        "model": "configured-general-model",
    }


def test_explicit_boost_configuration_still_selects_the_separate_model():
    assert select_reddit_model({
        "LLM_BOOST_API_KEY": "configured-boost-key",
        "LLM_BOOST_BASE_URL": "https://boost.example/v1",
        "LLM_BOOST_MODEL_NAME": "configured-boost-model",
    }) == {
        "api_key": "configured-boost-key",
        "base_url": "https://boost.example/v1",
        "model": "configured-boost-model",
    }
