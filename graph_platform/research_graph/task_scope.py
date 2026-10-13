"""Own Graphiti's child tasks, including siblings left behind by failed gather()."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

_owner = ContextVar('graph_ingestion_owner', default=None)


@asynccontextmanager
async def ingestion_tasks():
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    children = {}

    def factory(loop, coroutine, **kwargs):
        context = kwargs.get('context')
        owner = context.get(_owner, None) if context is not None else _owner.get()
        task = (previous_factory(loop, coroutine, **kwargs) if previous_factory
                else asyncio.Task(coroutine, loop=loop, **kwargs))
        if owner is not None:
            owner[task] = asyncio.current_task(loop=loop)
        return task

    loop.set_task_factory(factory)
    token = _owner.set(children)
    try:
        yield
    finally:
        _owner.reset(token)

        async def drain():
            while pending := {task for task in children if not task.done()}:
                # Cancel from the outside in. Canceling shielded to_thread tasks
                # directly would bypass Codex's cancel-event + subprocess drain.
                roots = {task for task in pending if children[task] not in pending}
                for task in roots:
                    task.cancel()
                await asyncio.gather(*roots, return_exceptions=True)
            # Retrieve orphan exceptions too, without masking the original failure.
            if children:
                await asyncio.gather(*children, return_exceptions=True)

        # A shutdown may arrive while failure cleanup is already running. Keep
        # draining before exposing failed status or closing the database driver.
        cleanup = asyncio.create_task(drain())
        interrupted = False
        try:
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    interrupted = True
            cleanup.result()
        finally:
            loop.set_task_factory(previous_factory)
        if interrupted:
            raise asyncio.CancelledError
