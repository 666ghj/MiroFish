import adversarial_router as ar


def _agent(aid: str, role: str, view: str) -> dict:
    return {"agent_id": aid, "role": role, "view": view,
            "score": 5.0, "confidence": 0.7, "thesis": "t", "note": "n"}


def _balanced_agents() -> list[dict]:
    agents = [_agent(f"bull-{i}", ar.BULL_LEANING[i % 3], "bullish") for i in range(8)]
    agents += [_agent(f"bear-{i}", ar.BEAR_LEANING[i % 3], "bearish") for i in range(8)]
    return agents


def test_classify_agent():
    assert ar.classify_agent("growth") == "bull"
    assert ar.classify_agent("risk") == "bear"
    assert ar.classify_agent("macro") == "neutral"


def test_balanced_fixture_low_reinforcement():
    pool = ar.synthetic_bear_market_pool(8, 8, 0, seed=0)  # 50% bull, 50% bear notes
    agents = _balanced_agents()  # 8 bull-leaning + 8 bear-leaning
    assignments = [[a, *ar.route_notes(a, pool, k=8, seed=0)] for a in agents]
    rate = ar.reinforcement_rate(assignments)
    assert rate < 0.10, f"reinforcement too high: {rate}"


def test_routing_is_deterministic():
    pool = ar.synthetic_bear_market_pool(6, 6, 4, seed=1)
    agent = _agent("x", "growth", "bullish")
    a = ar.route_notes(agent, pool, k=8, seed=42)
    b = ar.route_notes(agent, pool, k=8, seed=42)
    assert a == b, "same seed + agent must yield identical routing"


def test_same_view_only_when_no_opposite_or_neutral():
    agent = _agent("self", "growth", "bullish")
    all_bull = [{"agent_id": f"b{i}", "view": "bullish", "score": 5,
                 "confidence": 0.5, "thesis": "t", "note": "n"} for i in range(5)]
    out = ar.route_notes(agent, all_bull, k=8, seed=0)
    assert len(out) > 0, "must fall back to same-view when nothing else exists"
    assert all(n["view"] == "bullish" for n in out)
    assert ar.reinforcement_rate([[agent, *out]]) == 1.0  # same-view counts

    # once an opposite note appears, same-view must disappear
    pool = all_bull + [{"agent_id": "bear1", "view": "bearish", "score": 5,
                        "confidence": 0.5, "thesis": "t", "note": "n"}]
    out2 = ar.route_notes(agent, pool, k=8, seed=0)
    assert len(out2) > 0
    assert all(n["view"] == "bearish" for n in out2), "opposite exists -> no same-view"


def test_self_note_never_returned():
    pool = ar.synthetic_bear_market_pool(5, 5, 2, seed=3)
    agent = _agent(pool[0]["agent_id"], "quality", "bearish")
    out = ar.route_notes(agent, pool, k=8, seed=0)
    assert out, "expected some notes"
    assert all(n.get("agent_id") != agent["agent_id"] for n in out)


def test_dedup_holds():
    base = {"view": "bearish", "score": 5, "confidence": 0.5, "thesis": "t", "note": "n"}
    pool = [{**base, "agent_id": "dup"}, {**base, "agent_id": "dup"},
            {**base, "agent_id": "dup"}, {**base, "agent_id": "other"}]
    agent = _agent("self", "growth", "bullish")
    out = ar.route_notes(agent, pool, k=8, seed=0)
    ids = [n.get("agent_id") for n in out]
    assert len(ids) == len(set(ids)), "duplicate agent_ids returned"
