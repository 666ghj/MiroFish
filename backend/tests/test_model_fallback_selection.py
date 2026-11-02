"""Which model backs which platform (create_model in the parallel simulation script)."""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")


@pytest.fixture
def script(monkeypatch):
    monkeypatch.syspath_prepend(SCRIPTS)
    module = importlib.import_module("run_parallel_simulation")
    for name in ("LLM_BOOST_API_KEY", "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_MODEL_NAME", "LLM_FALLBACK"):
        monkeypatch.delenv(name, raising=False)

    def fake_make(config, use_boost=False, run_settings=None, seed=None, use_fallback=False):
        return "fallback" if use_fallback else "boost" if use_boost else "main"

    monkeypatch.setattr(module, "_make_model", fake_make)
    monkeypatch.setattr(module.sim_runtime, "install_model_fallback", lambda primary, other, note, **kwargs: (primary, other))
    monkeypatch.setattr(module.sim_runtime, "install_call_recording", lambda model, label, *a, **k: model)   # the fakes are plain strings
    return module


def test_without_any_backup_the_platform_model_is_used_alone(script):
    assert script.create_model({}, use_boost=False) == "main"


def test_with_only_a_boost_model_the_two_back_each_other_up(script, monkeypatch):
    monkeypatch.setenv("LLM_BOOST_API_KEY", "b")
    assert script.create_model({}, use_boost=False) == ("main", "boost")
    assert script.create_model({}, use_boost=True) == ("boost", "main")


def test_a_dedicated_fallback_backs_up_both_platforms(script, monkeypatch):
    monkeypatch.setenv("LLM_BOOST_API_KEY", "b")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "f")
    monkeypatch.setenv("LLM_FALLBACK_MODEL_NAME", "strong-model")
    assert script.create_model({}, use_boost=False) == ("main", "fallback")
    assert script.create_model({}, use_boost=True) == ("boost", "fallback")


def test_a_dedicated_fallback_works_without_a_boost_model(script, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "f")
    monkeypatch.setenv("LLM_FALLBACK_MODEL_NAME", "strong-model")
    assert script.create_model({}, use_boost=False) == ("main", "fallback")


def test_a_fallback_key_without_a_model_name_is_not_used(script, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "f")
    assert script.create_model({}, use_boost=False) == "main"


def test_the_fallback_can_be_turned_off(script, monkeypatch):
    monkeypatch.setenv("LLM_BOOST_API_KEY", "b")
    monkeypatch.setenv("LLM_FALLBACK", "false")
    assert script.create_model({}, use_boost=True) == "boost"


@pytest.mark.parametrize("value,paced", [(None, False), ("0", False), ("abc", False), ("1.2", True)])
def test_the_fallback_pacer_follows_the_environment(script, monkeypatch, value, paced):
    if value is None:
        monkeypatch.delenv("LLM_FALLBACK_MIN_INTERVAL", raising=False)
    else:
        monkeypatch.setenv("LLM_FALLBACK_MIN_INTERVAL", value)
    pacer = script._fallback_pacer()
    assert (pacer is not None) is paced
    if paced:
        assert pacer.interval == 1.2 and script._fallback_pacer() is pacer   # one pacer shared by both platforms
