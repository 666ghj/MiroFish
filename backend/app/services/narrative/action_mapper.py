"""Maps OASIS action types to narrative verbs and interpretations.

Used by the Narrative Translator to convert raw simulation actions
(`CREATE_POST`, `LIKE_POST`, etc.) into human-readable story language.
"""

ACTION_TO_VERB = {
    "CREATE_POST": "speaks",
    "LIKE_POST": "agrees with",
    "REPOST": "spreads word of",
    "QUOTE_POST": "responds to",
    "FOLLOW": "shows loyalty to",
    "DO_NOTHING": "observes in silence",
    "CREATE_COMMENT": "engages with",
    "DISLIKE_POST": "disapproves of",
    "LIKE_COMMENT": "validates",
    "DISLIKE_COMMENT": "dismisses",
    "SEARCH_POSTS": "investigates",
    "SEARCH_USER": "seeks out",
    "MUTE": "ignores",
}

ACTION_TO_NARRATIVE = {
    "CREATE_POST": "Character speaks, declares, or announces",
    "LIKE_POST": "Character agrees, supports, or nods",
    "REPOST": "Character spreads rumor, amplifies, or gossips",
    "QUOTE_POST": "Character responds, debates, or challenges",
    "FOLLOW": "Character allies with or shows loyalty to",
    "DO_NOTHING": "Character reflects, observes, or waits",
    "CREATE_COMMENT": "Character engages in dialogue",
    "DISLIKE_POST": "Character opposes, confronts, or disapproves",
    "LIKE_COMMENT": "Character validates a response",
    "DISLIKE_COMMENT": "Character dismisses or mocks",
    "SEARCH_POSTS": "Character investigates or seeks information",
    "SEARCH_USER": "Character seeks out a specific person",
    "MUTE": "Character avoids, ignores, or shuns",
}


def map_action_to_verb(action_type: str) -> str:
    """Return a narrative verb phrase for an OASIS action type."""
    return ACTION_TO_VERB.get(action_type, "does something")


def get_narrative_context(action_type: str) -> str:
    """Return a longer narrative interpretation for an OASIS action type."""
    return ACTION_TO_NARRATIVE.get(action_type, "Character takes an unknown action")
