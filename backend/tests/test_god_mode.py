import os
import tempfile
import pytest
from app.services.narrative.god_mode import inject_event
from app.services.narrative.story_store import StoryStore
from app.services.narrative.world_state import WorldStateStore


@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test")
        os.makedirs(sim_dir)
        yield sim_dir


def test_inject_event_appends_to_log(temp_sim_dir):
    evt = inject_event(temp_sim_dir, description="A storm arrives.", round_num=5)
    assert evt["description"] == "A storm arrives."
    assert evt["round"] == 5
    assert evt["id"] == "evt_1"
    assert evt["type"] == "god_mode_injection"

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    assert len(log) == 1


def test_inject_event_defaults_round_to_beats_plus_one(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 3, "prose": "beat 3"})

    evt = inject_event(temp_sim_dir, description="auto round")
    assert evt["round"] == 4


def test_inject_event_defaults_round_to_one_when_no_beats(temp_sim_dir):
    evt = inject_event(temp_sim_dir, description="first event")
    assert evt["round"] == 1


# ---- modify_emotion ----
from app.services.narrative.god_mode import modify_emotion


def _seed_character(sim_dir, char_id="1", name="Elena"):
    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger", "fear", "joy", "sadness", "surprise"]}
    store.save_characters([{
        "id": char_id, "name": name, "status": "alive",
        "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []},
    }])
    return store


def test_modify_emotion_overwrites_specified_emotions(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = modify_emotion(temp_sim_dir, "1", {"anger": 0.8, "joy": 0.2})

    assert result["emotional_state"]["current"]["anger"] == 0.8
    assert result["emotional_state"]["current"]["joy"] == 0.2
    assert result["emotional_state"]["current"]["trust"] == 0.5


def test_modify_emotion_clamps(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = modify_emotion(temp_sim_dir, "1", {"anger": 1.5, "fear": -0.3})
    assert result["emotional_state"]["current"]["anger"] == 1.0
    assert result["emotional_state"]["current"]["fear"] == 0.0


def test_modify_emotion_character_not_found_raises(temp_sim_dir):
    _seed_character(temp_sim_dir)
    with pytest.raises(ValueError, match="not found"):
        modify_emotion(temp_sim_dir, "nonexistent", {"anger": 0.5})


def test_modify_emotion_audit_logs_to_event_log(temp_sim_dir):
    _seed_character(temp_sim_dir)
    modify_emotion(temp_sim_dir, "1", {"anger": 0.8})

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    assert len(log) == 1
    assert log[0]["type"] == "god_mode_emotion_change"
    assert "Elena" in log[0]["description"]


# ---- kill_character ----
from app.services.narrative.god_mode import kill_character


def test_kill_character_sets_status_dead(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = kill_character(temp_sim_dir, "1")
    assert result["status"] == "dead"

    chars = StoryStore(temp_sim_dir).load_characters()
    assert chars[0]["status"] == "dead"


def test_kill_character_auto_appends_death_event(temp_sim_dir):
    _seed_character(temp_sim_dir)
    kill_character(temp_sim_dir, "1")

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    death_events = [e for e in log if e["type"] == "god_mode_death"]
    assert len(death_events) == 1
    assert "Elena" in death_events[0]["description"]


def test_kill_character_not_found_raises(temp_sim_dir):
    _seed_character(temp_sim_dir)
    with pytest.raises(ValueError, match="not found"):
        kill_character(temp_sim_dir, "nonexistent")
