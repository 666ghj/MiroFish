"""Extended character profiles, emotional state, and arc detection.

This module maintains character state beyond what OASIS tracks — backstory,
motivations, emotional state (six-dimension vector), relationships, and arc
stage. State is updated each round based on actions the character takes.
"""
from typing import Dict


EMOTIONS = ["anger", "fear", "joy", "sadness", "trust", "surprise"]

INITIAL_EMOTIONAL_STATE = {
    "anger": 0.0,
    "fear": 0.0,
    "joy": 0.0,
    "sadness": 0.0,
    "trust": 0.5,  # neutral-positive baseline; others start at 0
    "surprise": 0.0,
}


def create_initial_character(
    char_id: str,
    name: str,
    backstory: str = "",
    motivations: list | None = None,
    personality: list | None = None,
) -> dict:
    """Build a new character profile with neutral emotional state."""
    return {
        "id": char_id,
        "name": name,
        "backstory": backstory,
        "motivations": motivations or [],
        "personality_traits": personality or [],
        "status": "alive",
        "emotional_state": {
            "current": dict(INITIAL_EMOTIONAL_STATE),
            "history": [],
        },
        "relationships": {},
        "arc": {"archetype": None, "stage": "beginning", "key_moments": []},
    }


# ============================================================================
# USER CONTRIBUTION POINT — Emotional deltas per action type
# ============================================================================
#
# Each entry maps an OASIS action type to a dict of emotional changes the
# acting character experiences when they perform that action. Values are
# ADDED to current emotions (clamped to [0.0, 1.0]).
#
# Guidance:
#   - Keep individual deltas small (between -0.15 and +0.15) so they
#     accumulate gradually over many rounds.
#   - Consider BOTH positive and negative effects per action:
#       e.g. DISLIKE_POST → anger up, trust down
#   - Missing actions default to no emotional change (character still acts
#     but doesn't feel anything different about it).
#
# Actions to consider filling in (from action_mapper.py):
#   CREATE_POST, LIKE_POST, REPOST, QUOTE_POST, FOLLOW, DO_NOTHING,
#   CREATE_COMMENT, DISLIKE_POST, LIKE_COMMENT, DISLIKE_COMMENT,
#   SEARCH_POSTS, SEARCH_USER, MUTE
#
# ⬇ REPLACE THE CONTENTS BELOW WITH YOUR CHOICES ⬇
# ============================================================================
ACTION_EMOTIONAL_DELTAS: Dict[str, Dict[str, float]] = {
    # Speaking out publicly — small confidence bump
    "CREATE_POST": {"joy": 0.04},
    # Agreeing with someone — builds trust and a little joy
    "LIKE_POST": {"trust": 0.04, "joy": 0.02},
    # Spreading word of something — mild surprise/stimulation
    "REPOST": {"surprise": 0.02},
    # Responding or debating — mild engagement charge
    "QUOTE_POST": {"joy": 0.02, "surprise": 0.02},
    # Allying with someone — strong trust + joy bump
    "FOLLOW": {"trust": 0.08, "joy": 0.04},
    # Observing in silence — passive sadness/fear creep over time
    "DO_NOTHING": {"sadness": 0.02, "fear": 0.02},
    # Dialogue engagement — small positive
    "CREATE_COMMENT": {"joy": 0.03},
    # Confronting/opposing — anger up, trust down (classic conflict)
    "DISLIKE_POST": {"anger": 0.08, "trust": -0.04},
    # Validating a response — mild trust building
    "LIKE_COMMENT": {"trust": 0.03},
    # Mocking/dismissing — mild anger
    "DISLIKE_COMMENT": {"anger": 0.04},
    # Investigating — curiosity as surprise
    "SEARCH_POSTS": {"surprise": 0.03},
    # Seeking out a specific person — slight fear (implies concern)
    "SEARCH_USER": {"fear": 0.02, "surprise": 0.02},
    # Shunning/ignoring — sadness + trust loss
    "MUTE": {"sadness": 0.03, "trust": -0.03},
}
# ============================================================================


def apply_action_emotional_delta(character: dict, action_type: str) -> None:
    """Mutate character's emotional state based on an action they took.

    Emotions are clamped to [0.0, 1.0]. Unknown action types are a no-op.
    """
    deltas = ACTION_EMOTIONAL_DELTAS.get(action_type, {})
    current = character["emotional_state"]["current"]
    for emotion, delta in deltas.items():
        if emotion in current:
            current[emotion] = max(0.0, min(1.0, current[emotion] + delta))


class CharacterEngine:
    """Manages the character roster for a single simulation."""

    def __init__(self, store):
        self.store = store

    def initialize_from_profiles(self, oasis_profiles: list) -> list:
        """Bootstrap character roster from existing OASIS profile data."""
        characters = []
        for profile in oasis_profiles:
            char_id = str(profile.get("user_id", profile.get("id", "")))
            char = create_initial_character(
                char_id=char_id,
                name=profile.get("name", "Unknown"),
            )
            characters.append(char)
        self.store.save_characters(characters)
        return characters
