import os
import tempfile
import pytest
from app.services.narrative.story_store import StoryStore


@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test123")
        os.makedirs(sim_dir)
        yield sim_dir


def test_save_and_load_story_beats(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    beat = {"round": 1, "prose": "Elena spoke.", "characters": ["elena"]}
    store.append_beat(beat)

    beats = store.get_all_beats()
    assert len(beats) == 1
    assert beats[0]["prose"] == "Elena spoke."


def test_translator_state_tracks_offset(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    assert store.get_file_offset("twitter") == 0

    store.set_file_offset("twitter", 1024)
    assert store.get_file_offset("twitter") == 1024


def test_get_beat_by_round(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 1, "prose": "First"})
    store.append_beat({"round": 2, "prose": "Second"})

    beat = store.get_beat_by_round(2)
    assert beat["prose"] == "Second"


def test_narrative_dir_created_on_first_write(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 1, "prose": "test"})

    narrative_dir = os.path.join(temp_sim_dir, "narrative")
    assert os.path.isdir(narrative_dir)
