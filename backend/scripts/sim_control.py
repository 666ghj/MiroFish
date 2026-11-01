"""Pause and stop a running simulation between two rounds, without killing it.

The backend writes ``control.json`` into the simulation folder; the run script reads it at the start of every round
(after the previous round's checkpoint is written), so a request never cuts a round in half:

    {"action": "run"}     keep going (the default when the file is missing or unreadable)
    {"action": "pause"}   finish the round in progress, then wait here until the action changes
    {"action": "stop"}    finish the round in progress, then end the run cleanly

A file, not a signal, because Windows has no way to deliver a catchable signal to a console child process: the only
thing the backend could do there is kill it, in the middle of a round.

A run that stopped this way has a checkpoint (database + agents' chat memory) for its last finished round, so it
resumes exactly from there.
"""

import asyncio
import json
import os
import time
from typing import Awaitable, Callable, Optional

CONTROL_FILE = "control.json"
RUN, PAUSE, STOP = "run", "pause", "stop"
ACTIONS = (RUN, PAUSE, STOP)
POLL_SECONDS = 1.0


def control_path(sim_dir: str) -> str:
    return os.path.join(sim_dir, CONTROL_FILE)


def read_action(sim_dir: str) -> str:
    """The requested action. A missing, half-written or unknown file means ``run``: it must never stop a run."""
    try:
        with open(control_path(sim_dir), "r", encoding="utf-8") as handle:
            action = json.load(handle).get("action")
    except (OSError, ValueError, AttributeError):
        return RUN
    return action if action in ACTIONS else RUN


def write_action(sim_dir: str, action: str) -> None:
    """Request ``action`` (used by the backend). Written atomically, so the script never reads half a file."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    path = control_path(sim_dir)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"action": action, "requested_at": time.time()}, handle)
    try:
        os.replace(temporary, path)
    except PermissionError:
        # Windows refuses to replace a file another process has open at that instant; a second try is enough
        time.sleep(0.05)
        os.replace(temporary, path)


def clear(sim_dir: str) -> None:
    """Forget an old request (a new run must not start paused, or already stopped)."""
    try:
        os.remove(control_path(sim_dir))
    except OSError:
        pass


async def honour(
    sim_dir: str,
    log: Callable[[str], None],
    label: str,
    round_num: int,
    *,
    should_abort: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Called before round ``round_num`` (0-based). Returns ``"stop"`` when the run must end, else ``"run"``.

    While paused it waits here, once a second, and says so once; ``should_abort`` (the process's own shutdown flag)
    ends the wait so a pause can never keep a process from exiting.
    """
    action = read_action(sim_dir)
    if action == PAUSE:
        log(f"[{label}] 已暂停: 第 {round_num} 轮已完成，等待继续 / paused after round {round_num}, waiting to continue")
        paused_at = time.time()
        while action == PAUSE and not should_abort():
            await sleep(POLL_SECONDS)
            action = read_action(sim_dir)
        if action == RUN:
            log(f"[{label}] 继续运行 (暂停了 {time.time() - paused_at:.0f}秒) / continuing after {time.time() - paused_at:.0f}s")
    if action == STOP:
        log(f"[{label}] 已按请求在第 {round_num} 轮之前停止 / stopping as requested after round {round_num}")
        return STOP
    return RUN
