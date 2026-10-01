"""End-to-end test: simulated actions.jsonl → translate → verify story + state."""
import os
import json
from unittest.mock import patch

from app.services.narrative.story_store import StoryStore
from app.services.narrative.narrative_translator import translate_round


def test_full_pipeline_from_fake_simulation(tmp_path):
    sim_dir = str(tmp_path / "sim_e2e")
    os.makedirs(os.path.join(sim_dir, "twitter"))

    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")
    actions = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST",
         "action_args": {"content": "The council must fall."}, "success": True, "timestamp": "t"},
        {"round": 1, "agent_id": 2, "agent_name": "Marcus", "action_type": "DISLIKE_POST",
         "action_args": {"post_id": 1}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        {"round": 2, "agent_id": 1, "agent_name": "Elena", "action_type": "REPOST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"round": 2, "agent_id": 2, "agent_name": "Marcus", "action_type": "FOLLOW",
         "action_args": {"target": 3}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in actions:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    neutral_emotions = {k: 0.0 for k in ["anger", "fear", "joy", "sadness", "surprise"]}
    store.save_characters([
        {"id": "1", "name": "Elena",
         "emotional_state": {"current": {**neutral_emotions, "trust": 0.5}, "history": []}},
        {"id": "2", "name": "Marcus",
         "emotional_state": {"current": {**neutral_emotions, "trust": 0.5}, "history": []}},
    ])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.side_effect = [
            "Elena addressed the gathering. Marcus's face darkened.",
            "Elena's message spread through the quarter like a spark.",
        ]
        beat1 = translate_round(sim_dir, "twitter", 1, "dark fantasy")
        beat2 = translate_round(sim_dir, "twitter", 2, "dark fantasy")

    # Beats are correctly attributed and sequenced
    assert beat1["round"] == 1
    assert beat2["round"] == 2
    assert "Elena" in beat1["characters"]
    assert "Marcus" in beat1["characters"]
    assert beat1["action_count"] == 2

    # Both beats persisted
    all_beats = store.get_all_beats()
    assert len(all_beats) == 2
    assert all_beats[0]["prose"] == "Elena addressed the gathering. Marcus's face darkened."

    # Characters evolved per the emotional delta rules
    chars = {c["name"]: c for c in store.load_characters()}

    # Marcus DISLIKE_POST'd in round 1 → anger should be > 0 (delta 0.08)
    assert chars["Marcus"]["emotional_state"]["current"]["anger"] > 0.0
    # Marcus FOLLOW'd in round 2 → trust should have climbed above baseline (delta 0.08)
    assert chars["Marcus"]["emotional_state"]["current"]["trust"] > 0.5
    # Elena CREATE_POST'd then REPOST'd → joy and surprise both bumped
    assert chars["Elena"]["emotional_state"]["current"]["joy"] > 0.0
    assert chars["Elena"]["emotional_state"]["current"]["surprise"] > 0.0

    # Translator state advanced — next call for round 3 would resume, not re-read
    assert store.get_file_offset("twitter") > 0


# ---------------------------------------------------------------------------
# God Mode integration tests
# ---------------------------------------------------------------------------
from app.services.narrative.god_mode import inject_event, kill_character


def test_injected_event_appears_in_next_round_prompt(tmp_path):
    sim_dir = str(tmp_path / "sim_evt")
    os.makedirs(os.path.join(sim_dir, "twitter"))
    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")

    lines = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST",
         "action_args": {"content": "x"}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        {"round": 2, "agent_id": 1, "agent_name": "Elena", "action_type": "REPOST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in lines:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger", "fear", "joy", "sadness", "surprise"]}
    store.save_characters([{
        "id": "1", "name": "Elena", "status": "alive",
        "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []},
    }])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "beat"
        translate_round(sim_dir, "twitter", 1, "noir")
        # Inject between rounds
        inject_event(sim_dir, description="A mysterious letter arrives.")
        translate_round(sim_dir, "twitter", 2, "noir")

        # Round-2 prompt should contain the injected event
        round2_prompt = mock_llm.call_args_list[1][0][0]
        assert "mysterious letter" in round2_prompt


def test_killed_character_filtered_from_next_round(tmp_path):
    sim_dir = str(tmp_path / "sim_kill")
    os.makedirs(os.path.join(sim_dir, "twitter"))
    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")

    lines = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST",
         "action_args": {"content": "x"}, "success": True, "timestamp": "t"},
        {"round": 1, "agent_id": 2, "agent_name": "Marcus", "action_type": "DISLIKE_POST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        # Round 2: Elena (alive) and Marcus (will be killed) both act — filter
        # should keep Elena and drop Marcus
        {"round": 2, "agent_id": 1, "agent_name": "Elena", "action_type": "QUOTE_POST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"round": 2, "agent_id": 2, "agent_name": "Marcus", "action_type": "REPOST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in lines:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger", "fear", "joy", "sadness", "surprise"]}
    store.save_characters([
        {"id": "1", "name": "Elena", "status": "alive",
         "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []}},
        {"id": "2", "name": "Marcus", "status": "alive",
         "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []}},
    ])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "beat"
        translate_round(sim_dir, "twitter", 1, "noir")
        # Kill Marcus between rounds
        kill_character(sim_dir, "2")
        beat2 = translate_round(sim_dir, "twitter", 2, "noir")

        # Marcus acted in round 2 but is dead — his name should not be in
        # the beat's 'characters' list (which reflects who participated)
        assert "Marcus" not in beat2["characters"]

        # Round-2 prompt's characters-in-scene section must not include Marcus.
        # Marcus may appear in the event log as a death event; we exclude him
        # from the "feeling:" lines which describe living characters.
        round2_prompt = mock_llm.call_args_list[1][0][0]
        char_lines = [l for l in round2_prompt.split("\n") if "feeling:" in l]
        assert not any("Marcus" in l for l in char_lines)
