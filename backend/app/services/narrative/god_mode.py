"""God Mode intervention handlers.

All handlers mutate on-disk JSON under narrative/ and return the result.
Each intervention is logged to world_state.event_log for auditability.
"""
from typing import Optional

from app.services.narrative.story_store import StoryStore
from app.services.narrative.world_state import WorldStateStore


def _current_round(sim_dir: str) -> int:
    """Return the 'current' round: last translated beat's round + 1, or 1."""
    beats = StoryStore(sim_dir).get_all_beats()
    if not beats:
        return 1
    return beats[-1].get("round", 0) + 1


def inject_event(sim_dir: str, description: str, round_num: Optional[int] = None) -> dict:
    """Append a user-described event to the world event log."""
    world = WorldStateStore(sim_dir)
    round_val = round_num if round_num is not None else _current_round(sim_dir)
    return world.append_event({
        "type": "god_mode_injection",
        "description": description,
        "round": round_val,
    })


def modify_emotion(sim_dir: str, character_id: str, emotions: dict) -> dict:
    """Overwrite specified emotion values for a character. Clamps to [0, 1].

    Raises ValueError if character_id is not found. Unknown emotion keys are
    silently ignored (they don't corrupt state; they just don't apply).
    Logs the intervention to world_state.event_log for auditability.
    """
    store = StoryStore(sim_dir)
    characters = store.load_characters()

    target = next((c for c in characters if str(c.get("id")) == str(character_id)), None)
    if target is None:
        raise ValueError(f"character not found: {character_id}")

    current = target["emotional_state"]["current"]
    changed = {}
    for emo, val in emotions.items():
        if emo in current:
            new_val = max(0.0, min(1.0, float(val)))
            changed[emo] = {"from": current[emo], "to": new_val}
            current[emo] = new_val

    store.save_characters(characters)

    WorldStateStore(sim_dir).append_event({
        "type": "god_mode_emotion_change",
        "description": f"{target['name']} emotional state modified: {changed}",
        "round": _current_round(sim_dir),
    })

    return target


def kill_character(sim_dir: str, character_id: str) -> dict:
    """Mark a character as dead and append a death event to the world log.

    Death events are auto-appended so the LLM knows the character is gone
    rather than silently omitting them from prose.
    """
    store = StoryStore(sim_dir)
    characters = store.load_characters()

    target = next((c for c in characters if str(c.get("id")) == str(character_id)), None)
    if target is None:
        raise ValueError(f"character not found: {character_id}")

    target["status"] = "dead"
    store.save_characters(characters)

    WorldStateStore(sim_dir).append_event({
        "type": "god_mode_death",
        "description": f"{target['name']} has died.",
        "round": _current_round(sim_dir),
    })

    return target
