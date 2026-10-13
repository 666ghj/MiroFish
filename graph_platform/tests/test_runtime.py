import asyncio

import pytest

from research_graph.store import GraphStore


class Engine:
    async def ingest(self, job, ontology):
        if job['data'] == 'bad':
            raise RuntimeError('Extraction failed')
        if job['data'] == 'slow':
            await asyncio.sleep(30)

    async def close(self):
        pass


async def finished(store, eid):
    for _ in range(100):
        if store.episode(eid)['status'] in {'succeeded', 'failed'}:
            return store.episode(eid)
        await asyncio.sleep(0.01)
    pytest.fail('Worker did not complete')


@pytest.mark.asyncio
async def test_worker_persists_completion_and_keeps_running_after_failure(tmp_path):
    from research_graph.runtime import GraphRuntime
    store = GraphStore(tmp_path / 'jobs.db')
    for gid in ['good', 'bad']:
        store.create_graph(gid, gid, '')
    bad = store.add_episode('bad', 'text', 'bad')
    good = store.add_episode('good', 'text', 'ok')
    runtime = GraphRuntime(store, Engine())
    await runtime.start()
    try:
        assert (await finished(store, bad['uuid']))['status'] == 'failed'
        assert (await finished(store, good['uuid']))['processed'] is True
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_shutdown_marks_partial_work_failed_and_releases_ownership(tmp_path):
    from research_graph.runtime import GraphRuntime
    store = GraphStore(tmp_path / 'jobs.db')
    store.create_graph('g1', 'one', '')
    job = store.add_episode('g1', 'text', 'slow')
    runtime = GraphRuntime(store, Engine())
    await runtime.start()
    try:
        other = GraphRuntime(store, Engine())
        with pytest.raises(RuntimeError, match='already running'):
            await other.start()
        for _ in range(100):
            if store.episode(job['uuid'])['status'] == 'running':
                break
            await asyncio.sleep(0.01)
    finally:
        await runtime.close()
    assert store.episode(job['uuid'])['status'] == 'failed'
    assert 'interrupted' in store.episode(job['uuid'])['error'].lower()
    await other.start()
    await other.close()


@pytest.mark.asyncio
async def test_failed_graphiti_gather_cancels_children_before_unlocking_graph(tmp_path):
    from graphiti_core.helpers import semaphore_gather
    from research_graph.runtime import GraphRuntime
    started = asyncio.Event()
    canceled = asyncio.Event()
    release = asyncio.Event()
    class SiblingEngine(Engine):
        async def ingest(self, job, ontology):
            async def blocking_extraction():
                started.set()
                try:
                    await release.wait()
                finally:
                    canceled.set()
            async def invalid_extraction():
                await started.wait()
                raise ValueError('Invalid schema')
            await semaphore_gather(blocking_extraction(), invalid_extraction(), max_coroutines=2)
    store = GraphStore(tmp_path / 'jobs.db')
    store.create_graph('g1', 'one', '')
    job = store.add_episode('g1', 'text', 'test')
    unrelated = asyncio.create_task(asyncio.sleep(30))
    runtime = GraphRuntime(store, SiblingEngine())
    await runtime.start()
    try:
        await finished(store, job['uuid'])
        assert canceled.is_set(), 'The failed graph still owns active extraction tasks'
        assert not unrelated.done(), 'Cleanup must not cancel concurrent API/search tasks'
        store.reserve_delete('g1')
    finally:
        release.set()
        unrelated.cancel()
        await asyncio.gather(unrelated, return_exceptions=True)
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('shutdown_during_drain', [False, True])
async def test_failure_drains_shielded_codex_thread_before_journal_finish(tmp_path, monkeypatch, shutdown_during_drain):
    import threading
    import time
    from graphiti_core.helpers import semaphore_gather
    from graphiti_core.prompts.models import Message
    from research_graph import models
    from research_graph.runtime import GraphRuntime
    cli_started = threading.Event()
    cli_finished = threading.Event()
    cli_canceled = threading.Event()
    emergency_stop = threading.Event()
    def blocking_cli(prompt, schema, cancel_event=None):
        cli_started.set()
        while not cancel_event.is_set() and not emergency_stop.is_set():
            time.sleep(0.005)
        cli_canceled.set()
        time.sleep(0.05)  # Simulate subprocess reap after cancellation.
        cli_finished.set()
        raise RuntimeError('Canceled')
    monkeypatch.setattr(models, 'run_codex', blocking_cli)
    class SiblingEngine(Engine):
        async def ingest(self, job, ontology):
            async def fail():
                while not cli_started.is_set():
                    await asyncio.sleep(0.005)
                raise ValueError('One extraction failed')
            await semaphore_gather(models.CodexGraphClient()._generate_response(
                [Message(role='user', content='Synthetic source')]), fail(), max_coroutines=2)
    store = GraphStore(tmp_path / 'jobs.db')
    store.create_graph('g1', 'one', '')
    job = store.add_episode('g1', 'text', 'test')
    runtime = GraphRuntime(store, SiblingEngine())
    await runtime.start()
    try:
        if shutdown_during_drain:
            while not cli_canceled.is_set():
                await asyncio.sleep(0.002)
            await runtime.close()
        await finished(store, job['uuid'])
        assert cli_finished.is_set(), 'Journal finalized before Codex subprocess cleanup'
    finally:
        emergency_stop.set()
        await runtime.close()
