from types import SimpleNamespace
import threading
import time
from queue import Queue

import pytest

from app.services import zep_graph_memory_updater as updater_module
from app.services.zep_graph_memory_updater import (
    AgentActivity,
    ZepGraphMemoryManager,
    ZepGraphMemoryUpdater,
)


def _activity(index=1, content="hello"):
    return AgentActivity(
        platform="twitter",
        agent_id=index,
        agent_name=f"Agent {index}",
        action_type="CREATE_POST",
        action_args={"content": content},
        round_num=index,
        timestamp="2026-07-22T12:00:00+08:00",
    )


def _client(add):
    return SimpleNamespace(
        graph=SimpleNamespace(
            add=add,
            episode=SimpleNamespace(
                get=lambda **_kwargs: SimpleNamespace(processed=True)
            ),
        )
    )


def _updater(monkeypatch, add, simulation_id="sim-1"):
    client = _client(add)
    monkeypatch.setattr(updater_module, "get_zep_client", lambda _key: client)
    updater = ZepGraphMemoryUpdater(
        "graph-1",
        api_key="test-key",
        simulation_id=simulation_id,
    )
    updater.SEND_INTERVAL = 0
    return updater


def test_stop_drains_an_immediately_queued_tail_activity(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
    )

    updater.start()
    updater.add_activity(_activity())
    updater.stop()

    assert len(writes) == 1
    assert updater.get_stats()["items_sent"] == 1
    assert updater.get_stats()["queue_size"] == 0
    assert updater.get_stats()["ingestion_incomplete"] is False


def test_network_write_happens_outside_the_buffer_lock(monkeypatch):
    lock_was_available = []
    updater = None

    def add(**_kwargs):
        acquired = updater._buffer_lock.acquire(blocking=False)
        lock_was_available.append(acquired)
        if acquired:
            updater._buffer_lock.release()
        return SimpleNamespace(uuid_="episode-1")

    updater = _updater(monkeypatch, add)
    updater.start()
    for index in range(updater.BATCH_SIZE):
        updater.add_activity(_activity(index))
    updater.stop()

    assert lock_was_available == [True]


def test_activity_episode_has_provenance_time_and_a_safe_size(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
        simulation_id="sim-provenance",
    )

    updater._send_batch_activities(
        [_activity(content="x" * 20_000)],
        "twitter",
    )

    assert len(writes) == 1
    write = writes[0]
    assert len(write["data"]) <= updater.MAX_EPISODE_CHARS
    assert write["created_at"] == "2026-07-22T12:00:00+08:00"
    assert write["source_description"] == "MiroFish simulation activity batch"
    assert write["metadata"]["simulation_id"] == "sim-provenance"
    assert write["metadata"]["platform"] == "twitter"
    assert write["metadata"]["activity_count"] == 1


def test_failed_non_idempotent_write_is_reported_by_stop(monkeypatch):
    def add(**_kwargs):
        raise RuntimeError("write failed")

    updater = _updater(monkeypatch, add)
    updater.start()
    updater.add_activity(_activity())

    with pytest.raises(RuntimeError, match="ingestion is incomplete"):
        updater.stop()

    assert updater.get_stats()["failed_count"] == 1


def test_failed_simulation_action_is_not_ingested(monkeypatch):
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="unused"),
    )

    updater.add_activity_from_dict(
        {
            "agent_id": 1,
            "agent_name": "Agent",
            "action_type": "CREATE_POST",
            "action_args": {"content": "not actually posted"},
            "success": False,
        },
        "twitter",
    )

    assert updater.get_stats()["queue_size"] == 0
    assert updater.get_stats()["skipped_count"] == 1


def test_stop_cannot_finish_between_acceptance_check_and_enqueue(monkeypatch):
    writes = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
    )

    put_entered = threading.Event()
    allow_put = threading.Event()

    class BlockingQueue(Queue):
        def put(self, item, block=True, timeout=None):
            put_entered.set()
            assert allow_put.wait(timeout=2)
            return super().put(item, block=block, timeout=timeout)

    updater._activity_queue = BlockingQueue()
    updater.start()
    producer = threading.Thread(target=updater.add_activity, args=(_activity(),))
    producer.start()
    assert put_entered.wait(timeout=1)

    stopper = threading.Thread(target=updater.stop)
    stopper.start()
    stopper.join(timeout=0.1)
    assert stopper.is_alive()

    allow_put.set()
    producer.join(timeout=2)
    stopper.join(timeout=2)

    assert not producer.is_alive()
    assert not stopper.is_alive()
    assert len(writes) == 1


def test_wait_confirms_episode_when_processed_never_flips(monkeypatch):
    # Issue #795: graph.add() returning a UUID is the write confirmation.
    # `processed` is an async extraction flag that may never flip, so a
    # readable episode must confirm immediately instead of gating the
    # terminal state for 600s.
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-1"]
    updater.client.graph.episode.get = lambda **_kwargs: SimpleNamespace(
        processed=False
    )
    sleeps = []
    monkeypatch.setattr(updater_module.time, "sleep", sleeps.append)

    updater._wait_for_pending_episodes()

    assert sleeps == []
    assert updater.get_stats()["pending_episode_count"] == 0


def test_wait_polls_until_a_written_episode_becomes_readable(monkeypatch):
    # A get() returning None (not yet readable) must be polled until the
    # episode confirms, still without requiring processed=True.
    calls = []
    results = iter([None, SimpleNamespace(processed=True)])

    def get(**_kwargs):
        calls.append(1)
        return next(results)

    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-1"]
    updater.client.graph.episode.get = get
    sleeps = []
    monkeypatch.setattr(updater_module.time, "sleep", sleeps.append)

    updater._wait_for_pending_episodes()

    assert len(calls) == 2
    assert sleeps == [3]
    assert updater.get_stats()["pending_episode_count"] == 0


def test_explicit_graph_destruction_can_discard_a_stopped_failed_updater():
    updater = SimpleNamespace(
        graph_id="graph-1",
        _running=False,
        _worker_thread=SimpleNamespace(is_alive=lambda: False),
    )
    ZepGraphMemoryManager._updaters["sim-failed"] = updater
    try:
        assert ZepGraphMemoryManager.discard_inactive_updater("sim-failed") is True
        assert "sim-failed" not in ZepGraphMemoryManager._updaters
    finally:
        ZepGraphMemoryManager._updaters.pop("sim-failed", None)


def test_flush_deadline_keeps_unattempted_platform_for_a_safe_retry(monkeypatch):
    now = [0.0]
    writes = []

    def add(**kwargs):
        writes.append(kwargs)
        now[0] = 2.0
        return SimpleNamespace(uuid_=f"episode-{len(writes)}")

    updater = _updater(monkeypatch, add)
    updater._platform_buffers["twitter"] = [_activity(1)]
    reddit_activity = _activity(2)
    reddit_activity.platform = "reddit"
    updater._platform_buffers["reddit"] = [reddit_activity]
    monkeypatch.setattr(updater_module.time, "time", lambda: now[0])

    with pytest.raises(TimeoutError, match="deadline"):
        updater._flush_remaining(deadline=1.0)

    assert updater._platform_buffers["twitter"] == []
    assert updater._platform_buffers["reddit"] == [reddit_activity]

    now[0] = 0.0
    updater._flush_remaining(deadline=1.0)
    assert updater._platform_buffers["reddit"] == []
    assert len(writes) == 2

def test_wait_degrades_to_warning_when_reads_fail_past_soft_window(monkeypatch):
    # A failed read of an already-confirmed write must not block the terminal
    # state: after the soft window elapses, episodes that could not be
    # read-confirmed are downgraded to a warning instead of raising
    # TimeoutError.
    warnings_logged = []
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-1"]

    def get(**_kwargs):
        raise RuntimeError("read boom")

    updater.client.graph.episode.get = get
    monkeypatch.setattr(
        updater_module.logger,
        "warning",
        lambda *args: warnings_logged.append(args),
    )
    timestamps = iter([0.0, 0.0, 0.0, 5.0])
    monkeypatch.setattr(updater_module, "ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(updater_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    updater._wait_for_pending_episodes()

    assert len(warnings_logged) == 1
    assert updater.get_stats()["pending_episode_count"] == 0


def test_wait_read_failure_on_one_episode_does_not_block_others(monkeypatch):
    # The per-episode exception guard must skip only the failing episode;
    # other already-written episodes in the same poll round still confirm.
    warnings_logged = []
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-bad", "episode-good"]
    seen = []

    def get(uuid_=None, **_kwargs):
        seen.append(uuid_)
        if uuid_ == "episode-bad":
            raise RuntimeError("read boom")
        return SimpleNamespace(processed=False)

    updater.client.graph.episode.get = get
    monkeypatch.setattr(
        updater_module.logger,
        "warning",
        lambda *args: warnings_logged.append(args),
    )
    timestamps = iter([0.0, 0.0, 0.0, 5.0])
    monkeypatch.setattr(updater_module, "ZEP_INGESTION_WAIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(updater_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    updater._wait_for_pending_episodes()

    assert "episode-good" in seen
    assert "episode-bad" in seen
    assert len(warnings_logged) == 1
    assert updater.get_stats()["pending_episode_count"] == 0


def test_soft_confirm_timeout_leaves_an_incomplete_marker(monkeypatch):
    # Soft-confirm 超时降级为 warning 的同时，未确认数必须留痕：调用方不翻日志
    # 也能从 get_stats() 读到 ingestion_incomplete（#795 review 的"report"面）。
    updater = _updater(
        monkeypatch,
        lambda **_kwargs: SimpleNamespace(uuid_="episode-1"),
    )
    updater._pending_episode_uuids = ["episode-x"]
    updater.client.graph.episode.get = lambda **_kwargs: None
    monkeypatch.setattr(updater_module, "ZEP_PROCESSED_SOFT_WINDOW_SECONDS", 1)
    monkeypatch.setattr(updater_module.logger, "warning", lambda *args: None)
    timestamps = iter([0.0, 0.0, 5.0])
    monkeypatch.setattr(updater_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    updater._wait_for_pending_episodes()

    stats = updater.get_stats()
    assert updater._unconfirmed_episode_count == 1
    assert stats["pending_episode_count"] == 0  # 列表按原语义清空
    assert stats["ingestion_incomplete"] is True
    assert "unconfirmed_episodes" in stats["ingestion_incomplete_reasons"]


def test_stop_degrades_when_the_worker_does_not_stop_in_the_soft_window(monkeypatch):
    # #795 follow-up: the drain join used to be bounded only by the 600s hard
    # deadline, so a worker stuck in a network retry held the simulation's
    # terminal state long past the 45s soft window. The join is soft-bounded
    # now and stop() reports the degrade instead of raising. The tail stays
    # untouched: the live worker may be mid-send on exactly those activities,
    # and graph.add() has no idempotency key to replay them safely.
    writes = []
    warnings_logged = []
    updater = _updater(
        monkeypatch,
        lambda **kwargs: writes.append(kwargs) or SimpleNamespace(uuid_="episode-1"),
    )
    monkeypatch.setattr(updater_module, "ZEP_STOP_DRAIN_SOFT_WINDOW_SECONDS", 0.2)
    monkeypatch.setattr(
        updater_module.logger,
        "warning",
        lambda *args: warnings_logged.append(args),
    )

    release = threading.Event()

    def stuck_worker():
        release.wait(timeout=5)  # never checks _running: stuck in a network retry

    worker = threading.Thread(target=stuck_worker, daemon=True)
    worker.start()
    updater._worker_thread = worker
    updater._running = True
    updater.add_activity(_activity())

    started = time.monotonic()
    updater.stop()
    elapsed = time.monotonic() - started
    release.set()
    worker.join(timeout=1)

    assert elapsed < 2.0, "stop() waited past the soft window"
    assert writes == [], "the tail was flushed while the worker could still send it"
    assert any("worker did not stop" in str(args[0]) for args in warnings_logged)
    # The drop is observable, not silent: stats record the degraded stop and
    # how many activities were left behind (P2 of the PTC review).
    stats = updater.get_stats()
    assert stats["stop_degraded"] is True
    assert stats["dropped_tail_items"] == 1
    assert stats["ingestion_incomplete"] is True
    assert "degraded_stop" in stats["ingestion_incomplete_reasons"]


def test_stop_still_reports_failed_batches_when_the_worker_never_stops(monkeypatch):
    # P1 of the PTC review: the degraded branch used to skip the failed-batch
    # check, so a known-incomplete graph write returned as success and
    # simulation_runner never flipped the simulation to FAILED. The check now
    # runs after both branches; the base revision raised here too (via the
    # hard-deadline TimeoutError).
    def add(**_kwargs):
        raise RuntimeError("write failed")

    updater = _updater(monkeypatch, add)
    updater._send_batch_activities([_activity(1)], "twitter")  # records a failed batch
    monkeypatch.setattr(updater_module, "ZEP_STOP_DRAIN_SOFT_WINDOW_SECONDS", 0.2)
    monkeypatch.setattr(updater_module.logger, "warning", lambda *args: None)

    release = threading.Event()

    def stuck_worker():
        release.wait(timeout=5)  # never checks _running

    worker = threading.Thread(target=stuck_worker, daemon=True)
    worker.start()
    updater._worker_thread = worker
    updater._running = True

    try:
        with pytest.raises(RuntimeError, match="ingestion is incomplete"):
            updater.stop()
    finally:
        release.set()
        worker.join(timeout=1)

    stats = updater.get_stats()
    assert stats["ingestion_incomplete"] is True
    assert "failed_batches" in stats["ingestion_incomplete_reasons"]


def test_stop_degrades_to_a_warning_when_the_tail_flush_misses_its_window(monkeypatch):
    # The flush is soft-bounded too: `_flush_remaining` keeps raising for
    # direct callers (pinned above), but stop() is the caller that turns the
    # drain timeout into a logged degrade, leaving the unattempted platform
    # buffered for a safe retry instead of gating terminal state on it.
    warnings_logged = []
    updater = _updater(monkeypatch, lambda **_kwargs: SimpleNamespace(uuid_="episode-1"))
    updater._platform_buffers["twitter"] = [_activity(1)]

    def deadline_flush(*, deadline=None):
        raise TimeoutError(
            "Zep updater drain deadline elapsed before flushing all activities"
        )

    monkeypatch.setattr(updater, "_flush_remaining", deadline_flush)
    monkeypatch.setattr(
        updater_module.logger,
        "warning",
        lambda *args: warnings_logged.append(args),
    )

    updater.stop()

    assert updater._platform_buffers["twitter"], "the buffered tail must survive for a retry"
    assert any("tail flush did not finish" in str(args[0]) for args in warnings_logged)
