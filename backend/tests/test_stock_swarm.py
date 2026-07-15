import asyncio
import json

import pytest

import run_stock_swarm as sw


def test_topology_deterministic_and_no_self():
    a = sw.build_topology(8, 2, seed=42)
    b = sw.build_topology(8, 2, seed=42)
    assert a == b, "topology must be deterministic for a given seed"


def test_topology_peer_count_and_no_self():
    n, peers = 6, 3
    topo = sw.build_topology(n, peers, seed=1)
    assert len(topo) == n
    for i, ps in topo.items():
        assert i not in ps, "an agent must never be its own peer"
        assert len(ps) == min(peers, n - 1)
        assert len(set(ps)) == len(ps), "peers must be distinct"


def test_topology_caps_when_peers_ge_agents():
    topo = sw.build_topology(3, 10, seed=7)
    for i, ps in topo.items():
        assert len(ps) == 2, "peers capped at n-1 when fewer agents than peers"


def test_topology_single_agent():
    assert sw.build_topology(1, 3, seed=5) == {0: []}


def test_topology_seed_changes_assignment():
    a = sw.build_topology(8, 2, seed=1)
    b = sw.build_topology(8, 2, seed=999)
    assert a != b, "different seeds should yield different peer sets"


@pytest.mark.parametrize(
    ("field", "value"),
    [("agents", 0), ("rounds", 0), ("peers", -1), ("concurrency", 0),
     ("max_tokens", 0), ("opinion_words", 0), ("max_retries", -1)],
)
def test_invalid_config_rejected(field, value):
    cfg = sw.SwarmConfig(dry_run=True)
    setattr(cfg, field, value)
    with pytest.raises(ValueError):
        sw.validate_config(cfg)


def test_dry_run_end_to_end():
    cfg = sw.SwarmConfig(agents=4, rounds=2, peers=2, concurrency=4,
                        seed=1337, dry_run=True, base_delay=0.0,
                        output=":memory:")
    out = asyncio.run(sw.run_swarm(cfg))

    assert out["config"]["mode"] == "dry-run"
    assert len(out["rounds"]) == 2
    for rnd in out["rounds"]:
        assert len(rnd["agents"]) == 4
        for a in rnd["agents"]:
            assert a["ok"] is True
            assert a["opinion"] is not None
            assert "view" in a["opinion"]

    total = out["metrics"]["total"]
    assert total["requests"] == 8
    assert total["successes"] == 8
    assert total["failures"] == 0
    assert total["prompt_tokens"] > 0
    assert total["completion_tokens"] > 0
    assert total["total_tokens"] == total["prompt_tokens"] + total["completion_tokens"]
    assert len(out["metrics"]["rounds"]) == 2


def test_dry_run_no_secrets_leaked():
    cfg = sw.SwarmConfig(agents=2, rounds=1, dry_run=True, base_delay=0.0)
    cfg.llm_api_key = "sk-super-secret"
    cfg.clickhouse_password = "hunter2"
    out = asyncio.run(sw.run_swarm(cfg))
    blob = json.dumps(out)
    assert "sk-super-secret" not in blob
    assert "hunter2" not in blob
    assert out["config"]["llm_base_url"] is None
    assert out["config"]["clickhouse_url"] is None


def test_dry_run_round2_has_peer_revisions():
    cfg = sw.SwarmConfig(agents=4, rounds=2, peers=2, concurrency=4,
                        seed=21, dry_run=True, base_delay=0.0)
    out = asyncio.run(sw.run_swarm(cfg))
    r2 = out["rounds"][1]["agents"]
    changed = [a["opinion"].get("changed") for a in r2 if a["opinion"]]
    assert all(changed), "round 2 opinions should be marked as revised"
    assert all(a["peer_opinions_received"] == 2 for a in r2)


def test_round2_prompt_contains_own_and_peer_opinions():
    own = {"ticker": "AAA", "view": "bullish"}
    peers = [{"peer_ticker": "BBB", "opinion": {"view": "bearish"}}]
    prompt = sw.roundN_prompt("AAA", "{}", own, peers, 80)
    assert '"ticker":"AAA","view":"bullish"' in prompt
    assert '"peer_ticker":"BBB"' in prompt
    assert '"view":"bearish"' in prompt


def test_tokens_come_from_complete_fn_not_content():
    async def fake_complete(prompt):
        return {"content": "x", "prompt_tokens": 100,
                "completion_tokens": 5, "total_tokens": 105}

    sem = asyncio.Semaphore(1)
    res = asyncio.run(sw.invoke(fake_complete, "prompt", sem, max_retries=0, base_delay=0.0))
    assert res.ok is True
    assert res.completion_tokens == 5, "completion tokens must come from usage, not content length"
    assert res.prompt_tokens == 100
    assert res.total_tokens == 105


def test_summarize_math_and_percentiles():
    results = [
        sw.CallResult(ok=True, latency_ms=10.0, prompt_tokens=100, completion_tokens=20, total_tokens=120),
        sw.CallResult(ok=True, latency_ms=20.0, prompt_tokens=100, completion_tokens=20, total_tokens=120),
        sw.CallResult(ok=True, latency_ms=30.0, prompt_tokens=100, completion_tokens=20, total_tokens=120),
        sw.CallResult(ok=False, latency_ms=40.0),
    ]
    s = sw.summarize(results, wall_time_s=1.0)
    assert s["requests"] == 4
    assert s["successes"] == 3
    assert s["failures"] == 1
    assert s["prompt_tokens"] == 300
    assert s["completion_tokens"] == 60
    assert s["total_tokens"] == 360
    assert s["input_tokens_per_sec"] == 300.0
    assert s["output_tokens_per_sec"] == 60.0
    assert s["latency_ms"]["p50"] == 20.0
    assert s["latency_ms"]["p95"] == 40.0
    assert s["latency_ms"]["p99"] == 40.0


def test_summarize_empty():
    s = sw.summarize([], wall_time_s=0.0)
    assert s["requests"] == 0
    assert s["latency_ms"]["p50"] is None
    assert s["input_tokens_per_sec"] == 0.0


def test_percentile_nearest_rank():
    xs = [5.0, 10.0, 15.0, 20.0, 25.0]
    assert sw.percentile(sorted(xs), 50) == 15.0
    assert sw.percentile(sorted(xs), 95) == 25.0
    assert sw.percentile([], 50) is None


def test_retry_then_success():
    fake = sw.FakeLLM(seed=1, fail_first=2, delay=0.0)
    sem = asyncio.Semaphore(1)
    res = asyncio.run(sw.invoke(fake.complete, "p", sem, max_retries=3, base_delay=0.0))
    assert res.ok is True
    assert fake.calls == 3, "should have retried twice then succeeded"
    assert res.completion_tokens > 0


def test_retry_exhausted_marks_failure():
    fake = sw.FakeLLM(seed=1, fail_first=99, delay=0.0)
    sem = asyncio.Semaphore(1)
    res = asyncio.run(sw.invoke(fake.complete, "p", sem, max_retries=2, base_delay=0.0))
    assert res.ok is False
    assert "RetryableHTTP" in (res.error or "")
    assert res.completion_tokens == 0


def test_non_retryable_fails_immediately():
    async def boom(prompt):
        raise ValueError("not a 429")

    sem = asyncio.Semaphore(1)
    res = asyncio.run(sw.invoke(boom, "p", sem, max_retries=5, base_delay=0.0))
    assert res.ok is False
    assert "ValueError" in (res.error or "")


def test_parse_failures_are_not_reported_as_successes():
    async def invalid_json(prompt):
        return {
            "content": '{"view":"bullish"',
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    cfg = sw.SwarmConfig(agents=3, rounds=1, concurrency=3,
                         dry_run=True, base_delay=0.0)
    out = asyncio.run(sw.run_swarm_with_complete(cfg, invalid_json))
    total = out["metrics"]["total"]
    assert total["transport_successes"] == 3
    assert total["valid_opinions"] == 0
    assert total["successes"] == 0
    assert total["failures"] == 3
    assert all(error["kind"] == "opinion_parse" for error in out["errors"])
    assert all(not agent["ok"] for agent in out["rounds"][0]["agents"])


def test_failures_recorded_in_swarm():
    cfg = sw.SwarmConfig(agents=3, rounds=1, peers=1, concurrency=3,
                        seed=1, dry_run=True, base_delay=0.0, max_retries=0)
    async def fail(prompt):
        raise sw.RetryableHTTP(503)

    out = asyncio.run(sw.run_swarm_with_complete(cfg, fail))
    total = out["metrics"]["total"]
    assert total["requests"] == 3
    assert total["successes"] == 0
    assert total["failures"] == 3
    assert len(out["errors"]) == 3
    for e in out["errors"]:
        assert "503" in e["error"]


def test_missing_dossier_is_rejected(monkeypatch):
    monkeypatch.setattr(
        sw,
        "ch_query",
        lambda sql, params, cfg=None: [{"ticker": "MISS", "latest_annual_date": None}],
    )
    with pytest.raises(RuntimeError, match="No fundamentals dossier"):
        sw.fetch_dossier("MISS", "2026-03-31")


def test_short_universe_is_rejected(monkeypatch):
    monkeypatch.setattr(sw, "fetch_ticker_universe", lambda limit, cfg=None: [{"ticker": "ONE"}])
    monkeypatch.setattr(sw, "fetch_holding_quarter", lambda cfg=None: "2026-03-31")
    cfg = sw.SwarmConfig(agents=2, dry_run=False, clickhouse_url="https://db.example")
    with pytest.raises(RuntimeError, match="Requested 2 agents"):
        asyncio.run(sw.fetch_live_universe(cfg))


def test_hosts_redacted_by_default():
    cfg = sw.SwarmConfig(agents=1, rounds=1, dry_run=True, base_delay=0.0,
                         llm_base_url="http://10.0.0.1:8080/v1",
                         clickhouse_url="https://db.example:8443")
    out = asyncio.run(sw.run_swarm(cfg))
    assert out["config"]["llm_base_url"] is None
    assert out["config"]["clickhouse_url"] is None


def test_sanitize_url_strips_credentials():
    assert sw.sanitize_url("https://u:p@host.example:8123/path?x=1") == "https://host.example:8123"
    assert sw.sanitize_url("http://localhost:8123") == "http://localhost:8123"
    assert sw.sanitize_url(None) is None
    assert sw.sanitize_url("") is None


def test_parse_opinion_extracts_json():
    op = sw.parse_opinion('```json\n{"view": "bullish", "score": 0.8}\n```')
    assert op == {"view": "bullish", "score": 0.8}
    assert sw.parse_opinion("no json here")["parse_error"] == "no json object"
    assert sw.parse_opinion(None) is None
