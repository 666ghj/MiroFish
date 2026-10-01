"""
Durable state-machine building blocks shared by SimulationManager
(SimulationStatus, a best-effort projection of the run state) and
SimulationRunner (RunnerStatus, the authoritative run-phase state machine).

Provides:
- atomic_write_json: crash-safe persistence (write to a temp file in the same
  directory, fsync, then os.replace over the destination) so a process killed
  mid-write never leaves a truncated/corrupted state file behind.
- is_valid_transition: a pure check against an explicit transition graph, so
  "which state changes are legal" is documented as data instead of being
  implicit in scattered call sites.
- next_revision / ConcurrentModificationError: optimistic concurrency
  (compare-and-swap) support — a caller that read a state at revision N can
  ask to only overwrite it if it is still at revision N, and detect a
  concurrent writer instead of silently clobbering its update.
"""

import json
import os
import tempfile
from typing import Dict, Optional, Set


class InvalidStateTransitionError(ValueError):
    """Raised when an attempted state transition is not in the allowed graph."""


class ConcurrentModificationError(RuntimeError):
    """Raised when a compare-and-swap save loses a race with another writer."""


def atomic_write_json(path: str, data: dict) -> None:
    """
    Write `data` as JSON to `path` atomically.

    A crash (process kill, host power loss) at any point up to the final
    os.replace() call leaves the previous file (or no file, if this is the
    first write) intact — never a half-written one. os.replace() is atomic
    on POSIX and Windows as long as both paths are on the same filesystem,
    which they are here since the temp file is created in `path`'s own
    directory.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def is_valid_transition(
    transitions: Dict[str, Set[str]],
    current: Optional[str],
    target: str,
) -> bool:
    """
    True if moving from `current` to `target` is allowed.

    - No previous state (`current is None`) always allows `target`: this is
      object creation, not a transition.
    - A no-op re-save (`current == target`) is always allowed, since most
      saves only update progress fields, not the status itself.
    - Otherwise `target` must be reachable from `current` per `transitions`.
    """
    if current is None or current == target:
        return True
    return target in transitions.get(current, set())


def next_revision(previous_revision: Optional[int]) -> int:
    """The revision a new save should carry, given the last persisted one."""
    return (previous_revision or 0) + 1
