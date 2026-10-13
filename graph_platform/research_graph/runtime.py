"""Single-owner durable ingestion worker with cancellation and failure visibility."""

import asyncio
import fcntl
import logging
import os

from .task_scope import ingestion_tasks

logger = logging.getLogger(__name__)


class GraphRuntime:
    def __init__(self, store, engine):
        self.store = store
        self.engine = engine
        self.task = None
        self.owner = None

    async def start(self):
        self.owner = open(str(self.store.path) + '.owner.lock', 'a')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            self.owner = None
            raise RuntimeError('The local graph worker is already running for this data directory.') from None
        self.store.recover_interrupted()
        self.task = asyncio.create_task(self._work())

    async def _work(self):
        while True:
            job = self.store.claim_next()
            if job is None:
                await asyncio.sleep(0.1)
                continue
            try:
                timeout = float(os.environ.get('LOCAL_GRAPH_EPISODE_TIMEOUT_SECONDS', '1800'))
                async with ingestion_tasks(), asyncio.timeout(timeout):
                    await self.engine.ingest(job, self.store.graph(job['graph_id'])['ontology'])
            except asyncio.CancelledError:
                self.store.finish(job['uuid'], error='Ingestion interrupted during shutdown. Resume this operation.')
                raise
            except Exception as error:
                # Codex transport already sanitizes credential/provider errors.
                message = str(error) or type(error).__name__
                self.store.finish(job['uuid'], error=message[:2000])
                logger.error('Episode %s failed: %s', job['uuid'], message)
            else:
                self.store.finish(job['uuid'])

    async def close(self):
        try:
            if self.task is not None:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            await self.engine.close()
        finally:
            if self.owner is not None:
                self.owner.close()
                self.owner = None
