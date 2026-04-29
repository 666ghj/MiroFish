"""Parent-process liveness heartbeat.

This module is part of the subprocess watchdog mechanism that
prevents simulation children from leaking when the Flask backend
dies ungracefully (SIGKILL, system sleep, parent crash, OS-level
shutdown without atexit running).

Design
------

* On backend startup, :func:`start` spawns a daemon thread that
  every :data:`HEARTBEAT_INTERVAL_SECONDS` writes the current
  monotonic timestamp to a file under the system temp directory.

* On subprocess spawn, the simulation runner passes the Flask
  process PID and the heartbeat file path to the child via CLI
  flags. The child runs a parallel watchdog that aborts itself
  if either (a) the parent PID disappears or (b) the heartbeat
  file is older than :data:`STALE_THRESHOLD_SECONDS`.

* The heartbeat file is named with the Flask PID so multiple
  backend instances on the same machine do not collide and each
  child knows exactly which file belongs to its parent.

The mechanism is best-effort and intentionally simple — no IPC,
no ports, no shared memory. Just a file timestamp and a PID
liveness check.
"""

from __future__ import annotations

import atexit
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger("mirofish.parent_heartbeat")

HEARTBEAT_INTERVAL_SECONDS = 5
"""How often the parent refreshes the heartbeat timestamp."""

STALE_THRESHOLD_SECONDS = 30
"""Age beyond which the child treats the parent as dead.

Must be comfortably greater than :data:`HEARTBEAT_INTERVAL_SECONDS`
so brief stalls (GC pause, system suspend resume) do not kill
healthy simulations.
"""

_FILE_PREFIX = "mirofish-parent-"

_state_lock = threading.Lock()
_started = False
_heartbeat_path: Optional[Path] = None
_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None


def _heartbeat_file_for(pid: int) -> Path:
    """Return the canonical heartbeat path for a given parent PID."""
    return Path(tempfile.gettempdir()) / f"{_FILE_PREFIX}{pid}.heartbeat"


def get_heartbeat_path() -> Optional[str]:
    """Return the heartbeat file path managed by this process, if any."""
    if _heartbeat_path is None:
        return None
    return str(_heartbeat_path)


def get_parent_pid() -> int:
    """Return the PID that subprocesses should monitor."""
    return os.getpid()


def _heartbeat_loop(stop_event: threading.Event, path: Path) -> None:
    """Daemon-thread body that refreshes the heartbeat file."""
    logger.info(
        "Parent heartbeat started: pid=%d path=%s interval=%ds",
        os.getpid(),
        path,
        HEARTBEAT_INTERVAL_SECONDS,
    )
    while not stop_event.is_set():
        try:
            # Touch the file with the current wall-clock timestamp so
            # children can verify freshness via mtime alone.
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{time.time():.3f}\n")
        except Exception as exc:  # noqa: BLE001 — keep the loop alive
            logger.warning("Heartbeat write failed (non-fatal): %s", exc)
        if stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            break

    # Best-effort cleanup so the next backend instance starts clean.
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    logger.info("Parent heartbeat stopped")


def start() -> Optional[str]:
    """Start the heartbeat thread (idempotent).

    Returns the heartbeat file path so callers can pass it to
    children. If the thread is already running, returns the existing
    path without restarting.
    """
    global _started, _heartbeat_path, _thread, _stop_event

    with _state_lock:
        if _started:
            return str(_heartbeat_path) if _heartbeat_path else None

        _heartbeat_path = _heartbeat_file_for(os.getpid())
        _stop_event = threading.Event()
        _thread = threading.Thread(
            target=_heartbeat_loop,
            args=(_stop_event, _heartbeat_path),
            name="parent-heartbeat",
            daemon=True,
        )
        _thread.start()
        _started = True

        # Also remove the heartbeat file on graceful shutdown so a
        # follow-up child cannot race on a stale timestamp.
        atexit.register(stop)

        return str(_heartbeat_path)


def stop() -> None:
    """Stop the heartbeat thread and clean up the file."""
    global _started, _heartbeat_path, _thread, _stop_event

    with _state_lock:
        if not _started:
            return
        if _stop_event is not None:
            _stop_event.set()
        if _thread is not None:
            _thread.join(timeout=2)
        if _heartbeat_path is not None:
            try:
                _heartbeat_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
        _started = False
        _heartbeat_path = None
        _thread = None
        _stop_event = None
