from app.services.narrative.character_engine import (
    CharacterEngine,
    create_initial_character,
    apply_action_emotional_delta,
)


def test_create_initial_character_has_neutral_emotions():
    char = create_initial_character(char_id="elena", name="Elena Voss")
    assert char["emotional_state"]["current"]["anger"] == 0.0
    assert char["emotional_state"]["current"]["joy"] == 0.0
    # Trust starts at a neutral-positive baseline, not zero
    assert char["emotional_state"]["current"]["trust"] == 0.5


def test_create_initial_character_stores_name_and_id():
    char = create_initial_character(char_id="elena", name="Elena Voss")
    assert char["id"] == "elena"
    assert char["name"] == "Elena Voss"


def test_apply_delta_clamps_to_zero_one_range():
    char = create_initial_character(char_id="x", name="X")
    # Hammer a single action many times to exceed the clamp
    for _ in range(20):
        apply_action_emotional_delta(char, "DISLIKE_POST")
    for emo, val in char["emotional_state"]["current"].items():
        assert 0.0 <= val <= 1.0, f"{emo}={val} outside [0,1]"


def test_create_post_increases_confidence_proxy():
    # Speaking out should bump joy slightly (a proxy for confidence)
    char = create_initial_character(char_id="x", name="X")
    baseline_joy = char["emotional_state"]["current"]["joy"]
    apply_action_emotional_delta(char, "CREATE_POST")
    assert char["emotional_state"]["current"]["joy"] >= baseline_joy


def test_dislike_post_increases_anger():
    char = create_initial_character(char_id="x", name="X")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    assert char["emotional_state"]["current"]["anger"] > 0.0


def test_create_initial_character_sets_status_alive():
    char = create_initial_character(char_id="x", name="X")
    assert char["status"] == "alive"
