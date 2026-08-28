"""Process-local lifecycle coordination for Zep Cloud graphs.

The lock is intentionally keyed by graph ID so graph deletion/reset and a new
simulation updater claim cannot pass each other between validation and their
Cloud mutation.  It complements (but does not replace) a distributed lock in
multi-worker deployments.
"""

import threading


_graph_locks: dict[str, threading.RLock] = {}
_graph_locks_guard = threading.Lock()
_graph_readers: dict[str, set[str]] = {}


def graph_lifecycle_lock(graph_id: str) -> threading.RLock:
    """Return the process-local re-entrant lifecycle lock for ``graph_id``."""

    if not graph_id:
        raise ValueError("graph_id is required for lifecycle locking")
    with _graph_locks_guard:
        return _graph_locks.setdefault(graph_id, threading.RLock())


def register_graph_reader(graph_id: str, reader_id: str) -> None:
    """Register a long-running read lease under the graph lifecycle lock."""

    if not reader_id:
        raise ValueError("reader_id is required")
    with graph_lifecycle_lock(graph_id):
        _graph_readers.setdefault(graph_id, set()).add(reader_id)


def unregister_graph_reader(graph_id: str, reader_id: str) -> None:
    """Release a previously registered graph read lease."""

    with graph_lifecycle_lock(graph_id):
        readers = _graph_readers.get(graph_id)
        if not readers:
            return
        readers.discard(reader_id)
        if not readers:
            _graph_readers.pop(graph_id, None)


def get_graph_readers(graph_id: str) -> list[str]:
    """Return active reader IDs while serializing with lifecycle mutations."""

    with graph_lifecycle_lock(graph_id):
        return sorted(_graph_readers.get(graph_id, set()))
