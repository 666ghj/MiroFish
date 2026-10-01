import os
import tempfile
import pytest
from app.services.narrative.world_state import WorldStateStore


@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test")
        os.makedirs(sim_dir)
        yield sim_dir


def test_load_returns_empty_world_when_missing(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    world = store.load()
    assert world == {"rules": [], "locations": {}, "event_log": []}


def test_set_rules_replaces_previous(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    store.set_rules(["rule 1", "rule 2"])
    assert store.load()["rules"] == ["rule 1", "rule 2"]
    store.set_rules(["only rule"])
    assert store.load()["rules"] == ["only rule"]


def test_upsert_location_adds_and_updates(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    store.upsert_location({"id": "tower", "name": "The Tower", "description": "tall"})
    assert store.load()["locations"]["tower"]["name"] == "The Tower"

    store.upsert_location({"id": "tower", "name": "The Iron Tower", "description": "dark"})
    assert store.load()["locations"]["tower"]["name"] == "The Iron Tower"


def test_append_event_auto_ids_sequentially(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    e1 = store.append_event({"type": "custom", "description": "one", "round": 1})
    e2 = store.append_event({"type": "custom", "description": "two", "round": 2})

    assert e1["id"] == "evt_1"
    assert e2["id"] == "evt_2"
    assert store.load()["event_log"][-1]["description"] == "two"
