from types import SimpleNamespace

import pytest

from app.config import Config
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.ontology_generator import OntologyGenerator
from app.services import simulation_config_generator as simulation_config_module


def test_unset_cohort_temperature_preserves_existing_retry_schedules(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", None)

    assert Config.cohort_temperature(0.3, 0) == 0.3
    assert [Config.cohort_temperature(0.7, attempt) for attempt in range(3)] == pytest.approx([
        0.7,
        0.6,
        0.5,
    ])


def test_configured_cohort_temperature_is_flat_across_retries(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)

    assert Config.cohort_temperature(0.3, 0) == 0.0
    assert [Config.cohort_temperature(0.7, attempt) for attempt in range(3)] == [
        0.0,
        0.0,
        0.0,
    ]


def test_ontology_generator_uses_configured_cohort_temperature(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)

    class RecordingClient:
        def __init__(self):
            self.calls = []

        def chat_json(self, **kwargs):
            self.calls.append(kwargs)
            return {"entity_types": [], "edge_types": [], "analysis_summary": "ok"}

    client = RecordingClient()
    OntologyGenerator(client).generate(["source"], "requirement")

    assert client.calls[0]["temperature"] == 0.0


def test_profile_and_config_generators_use_configured_cohort_temperature(monkeypatch):
    monkeypatch.setattr(Config, "COHORT_TEMPERATURE", 0.0)
    calls = []

    def fake_completion(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"bio":"bio","persona":"persona"}'),
                )
            ]
        )

    monkeypatch.setattr(
        "app.services.oasis_profile_generator.create_chat_completion",
        fake_completion,
    )
    profile_generator = object.__new__(OasisProfileGenerator)
    profile_generator.client = object()
    profile_generator.model_name = "test-model"
    profile_generator._generate_profile_with_llm(
        "name", "Person", "summary", {}, "context"
    )

    monkeypatch.setattr(simulation_config_module, "create_chat_completion", fake_completion)
    config_generator = object.__new__(simulation_config_module.SimulationConfigGenerator)
    config_generator.client = object()
    config_generator.model_name = "test-model"
    config_generator._call_llm_with_retry("prompt", "system")

    assert [call["temperature"] for call in calls] == [0.0, 0.0]
