"""Subprocess watchdog: aborts the simulation when the parent dies.

Embedded into ``run_parallel_simulation.py`` (and other long-running
spawnable scripts) to prevent the leak where a parent Flask backend
dies ungracefully (SIGKILL, system sleep, OS shutdown) and the
child keeps running, burning LLM credits.

Two independent liveness signals must both pass on every tick:

1. **Parent PID exists.** ``os.kill(pid, 0)`` returns success if the
   process is alive; raises ``ProcessLookupError`` if the PID has
   been reaped. We do not rely on ``os.getppid()`` because once the
   parent dies the child gets re-parented to ``init`` (PID 1) and
   ``getppid`` returns 1, which is not a clear signal.
2. **Heartbeat file is fresh.** The parent refreshes
   ``${TMPDIR}/mirofish-parent-<ppid>.heartbeat`` every 5 seconds;
   if its mtime is older than ``stale_threshold_seconds`` (default
   30s), we treat the parent as wedged even if its PID still exists.

If either check fails, the watchdog logs a clear message and calls
the user-supplied ``on_parent_lost`` callback (typically setting an
asyncio shutdown event and calling :func:`sys.exit`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("mirofish.child_watchdog")

DEFAULT_CHECK_INTERVAL_SECONDS = 10
DEFAULT_STALE_THRESHOLD_SECONDS = 30


def _parent_alive(pid: int) -> bool:
    """Return True if the parent process is still around.

    ``os.kill(pid, 0)`` is the standard POSIX way to ask "is this
    PID alive without disturbing it"; on Windows a different
    mechanism would be needed but MiroFish's leak primarily affects
    Unix-like systems where the simulation backend runs.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # We are not allowed to signal it, but it does exist.
        return True


def _heartbeat_fresh(path: Path, stale_after: float) -> bool:
    """Return True if ``path`` exists and was written recently."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - mtime) <= stale_after


def start_watchdog(
    parent_pid: int,
    heartbeat_path: Optional[str],
    on_parent_lost: Callable[[str], None],
    *,
    check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
    stale_threshold_seconds: float = DEFAULT_STALE_THRESHOLD_SECONDS,
) -> threading.Thread:
    """Spawn a daemon watchdog thread.

    Parameters
    ----------
    parent_pid:
        PID the child should monitor. The simulation runner passes
        the Flask backend PID here.
    heartbeat_path:
        Filesystem path where the parent refreshes a timestamp.
        ``None`` disables the freshness check (PID-only mode).
    on_parent_lost:
        Callback invoked exactly once when the parent is determined
        to have died. Receives a one-line reason string. The
        callback is expected to begin a graceful shutdown and then
        ``sys.exit`` or raise.
    check_interval_seconds:
        How often to re-check liveness.
    stale_threshold_seconds:
        Maximum acceptable age of the heartbeat file before the
        parent is considered wedged.

    Returns the started :class:`threading.Thread` so callers can
    join on it during cleanup if they wish.
    """
    if parent_pid <= 0:
        logger.warning(
            "Child watchdog disabled: invalid parent_pid=%r", parent_pid
        )
        return _noop_thread()

    hb = Path(heartbeat_path) if heartbeat_path else None

    def _loop() -> None:
        logger.info(
            "Child watchdog started: parent_pid=%d heartbeat=%s interval=%.0fs stale=%.0fs",
            parent_pid,
            hb,
            check_interval_seconds,
            stale_threshold_seconds,
        )
        # Stagger the first check by one full interval so the parent has
        # a chance to write its first heartbeat after spawning us.
        time.sleep(check_interval_seconds)

        while True:
            if not _parent_alive(parent_pid):
                _trigger("parent process disappeared")
                return
            if hb is not None and not _heartbeat_fresh(
                hb, stale_threshold_seconds
            ):
                _trigger(
                    f"parent heartbeat at {hb} is older than {stale_threshold_seconds:.0f}s"
                )
                return
            time.sleep(check_interval_seconds)

    triggered = threading.Event()

    def _trigger(reason: str) -> None:
        # Guard: deliver the on_parent_lost callback exactly once.
        if triggered.is_set():
            return
        triggered.set()
        logger.error(
            "Child watchdog: parent appears dead (%s); shutting down",
            reason,
        )
        try:
            on_parent_lost(reason)
        except Exception as exc:  # noqa: BLE001
            # The callback is supposed to exit; if it raised, we make
            # sure the process still terminates so credits stop burning.
            logger.error("on_parent_lost callback raised: %s", exc)
            os._exit(137)

    thread = threading.Thread(
        target=_loop, name="child-watchdog", daemon=True
    )
    thread.start()
    return thread


def _noop_thread() -> threading.Thread:
    """Return a finished daemon thread for the disabled case."""
    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    return t
