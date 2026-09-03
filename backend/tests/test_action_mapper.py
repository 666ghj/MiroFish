from app.services.narrative.action_mapper import map_action_to_verb, get_narrative_context


def test_create_post_maps_to_speech():
    result = map_action_to_verb("CREATE_POST")
    assert result == "speaks"


def test_like_post_maps_to_agreement():
    result = map_action_to_verb("LIKE_POST")
    assert result == "agrees with"


def test_unknown_action_returns_fallback():
    result = map_action_to_verb("UNKNOWN_ACTION")
    assert result == "does something"


def test_get_narrative_context_returns_interpretation():
    ctx = get_narrative_context("REPOST")
    assert "rumor" in ctx.lower() or "amplifies" in ctx.lower()
