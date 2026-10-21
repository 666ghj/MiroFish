"""Syntactically valid model JSON must still produce runnable timing."""
import pytest

from app.services.simulation_config_generator import SimulationConfigGenerator


@pytest.mark.parametrize("field", ["minutes_per_round", "total_simulation_hours"])
@pytest.mark.parametrize("value", [0, -1, None, "60", True, 0.5])
def test_invalid_generated_duration_uses_executable_defaults(field, value):
    generator = object.__new__(SimulationConfigGenerator)
    config = generator._parse_time_config({field: value}, num_entities=3)
    assert type(config.total_simulation_hours) is int
    assert type(config.minutes_per_round) is int
    assert config.total_simulation_hours > 0
    assert config.minutes_per_round > 0
    assert config.total_simulation_hours * 60 // config.minutes_per_round > 0


@pytest.mark.parametrize("entity_count", [1, 2, 3])
def test_generated_activity_counts_never_exceed_actual_cohort(entity_count):
    generator = object.__new__(SimulationConfigGenerator)
    config = generator._parse_time_config({
        "agents_per_hour_min": 50, "agents_per_hour_max": 60,
    }, num_entities=entity_count)
    assert 1 <= config.agents_per_hour_min <= config.agents_per_hour_max <= entity_count


def test_valid_generated_timing_is_preserved():
    generator = object.__new__(SimulationConfigGenerator)
    config = generator._parse_time_config({
        "total_simulation_hours": 48, "minutes_per_round": 30,
        "agents_per_hour_min": 2, "agents_per_hour_max": 4,
    }, num_entities=8)
    assert (config.total_simulation_hours, config.minutes_per_round) == (48, 30)
    assert (config.agents_per_hour_min, config.agents_per_hour_max) == (2, 4)


def test_round_length_cannot_silently_eliminate_entire_simulation():
    generator = object.__new__(SimulationConfigGenerator)
    config = generator._parse_time_config({
        "total_simulation_hours": 1, "minutes_per_round": 120,
    }, num_entities=3)
    assert config.total_simulation_hours * 60 // config.minutes_per_round >= 1
