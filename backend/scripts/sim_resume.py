"""Resume a stopped or interrupted run from its last finished round.

What a resume can and cannot do
-------------------------------
* The platform databases and ``actions.jsonl`` are kept. The log is cut back to the end of the last
  finished round (a round that started but did not finish is dropped and redone).
* The behaviour engine's scheduling (who is woken, reaction delays, scheduled events) depends only on the
  run seed and the configuration, never on what the model said. It is *replayed* for the finished rounds
  without any model call, so its random generators are exactly where they were, and the replay is checked
  against the ``active_agent_ids`` that were logged for every finished round.
* Agent chat memory lives in the process. It is saved into the checkpoint together with the database (see
  below) and loaded back on resume, so agents continue with their real history. A run whose checkpoint has
  no memory (it was started before memory was saved, or there is no checkpoint) resumes with empty chat
  memory: agents then know their persona and the platform as it is, not what they experienced. Either way a
  resumed run is not bit-identical to an uninterrupted one: the model is not deterministic.

Exactness of the unfinished round
---------------------------------
After every finished round the run script writes a *checkpoint*: a consistent copy of the platform database
(``<db>.ckpt``) that carries the round number in a ``mirofish_checkpoint`` table, so the copy and its round
can never disagree. A resume restores it, which undoes whatever the unfinished round had already written.
A run that has no checkpoint (it was started before this feature) can still be resumed from the database as
it is; then the actions the unfinished round had already taken stay in the database and the round is redone
on top of them (``exact`` is False).

This module has no dependencies, so the backend and the run script can both use it.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional

CHECKPOINT_SUFFIX = ".ckpt"
CHECKPOINT_TABLE = "mirofish_checkpoint"
MEMORY_TABLE = "mirofish_agent_memory"
#: Log records with these phases are not agent behaviour and are not counted as actions.
NON_ACTION_PHASES = {"setup", "poll"}


class ScheduleMismatch(RuntimeError):
    """The replayed scheduling disagrees with what the original run logged."""


# --- reading the action log ----------------------------------------------------

@dataclass
class LogScan:
    exists: bool = False
    #: round 0 (seed follows + initial posts) finished
    setup_done: bool = False
    #: last round n >= 1 whose ``round_end`` is logged (0 = none)
    last_round: int = 0
    #: byte offset just after the ``round_end`` line of each finished round, round 0 included
    round_offsets: Dict[int, int] = field(default_factory=dict)
    #: actions counted the way the run loop counts them, up to the end of each finished round
    round_totals: Dict[int, int] = field(default_factory=dict)
    #: ``round_start`` active agent ids per round (rounds >= 1), also for an unfinished round
    started: Dict[int, List[int]] = field(default_factory=dict)


def scan_log(path: str) -> LogScan:
    """Walk an ``actions.jsonl`` and find where each finished round ended.

    Only complete lines count: a line the script was still writing is ignored.
    """
    scan = LogScan()
    if not os.path.isfile(path):
        return scan
    scan.exists = True
    counted = 0
    offset = 0
    with open(path, "rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            offset += len(raw)
            try:
                record = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            event = record.get("event_type")
            if event is None:
                if record.get("phase") not in NON_ACTION_PHASES:
                    counted += 1
            elif event == "round_start":
                ids = record.get("active_agent_ids")
                number = record.get("round")
                if isinstance(number, int) and number >= 1 and isinstance(ids, list):
                    scan.started[number] = [int(i) for i in ids]
            elif event == "round_end":
                number = record.get("round")
                if number == 0:
                    scan.setup_done = True
                    scan.round_offsets[0] = offset
                    scan.round_totals[0] = counted
                elif isinstance(number, int) and scan.setup_done and number == scan.last_round + 1:
                    scan.last_round = number
                    scan.round_offsets[number] = offset
                    scan.round_totals[number] = counted
    return scan


# --- checkpoints ---------------------------------------------------------------

def checkpoint_path(db_path: str) -> str:
    return db_path + CHECKPOINT_SUFFIX


def write_checkpoint(
    db_path: str,
    round_num: int,
    clock: Optional[Mapping[str, Any]] = None,
    memories: Optional[Mapping[int, str]] = None,
) -> str:
    """Copy the database (consistently) next to itself, tagged with ``round_num``.

    ``memories`` maps an agent id to that agent's chat memory as a JSON string. It is stored in a table of
    the copy itself, so the database, the round number and the memory are saved in one step and can never
    disagree.
    """
    target = checkpoint_path(db_path)
    temp = target + ".tmp"
    if os.path.exists(temp):
        os.remove(temp)
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(temp)
    try:
        source.backup(destination)
        destination.execute(f"CREATE TABLE IF NOT EXISTS {CHECKPOINT_TABLE} (round INTEGER, clock TEXT, written_at TEXT)")
        destination.execute(f"DELETE FROM {CHECKPOINT_TABLE}")
        destination.execute(
            f"INSERT INTO {CHECKPOINT_TABLE} (round, clock, written_at) VALUES (?, ?, ?)",
            (int(round_num), json.dumps(dict(clock or {})), datetime.now().isoformat()),
        )
        # a database restored from an older checkpoint still carries that checkpoint's memory: replace it
        destination.execute(f"DROP TABLE IF EXISTS {MEMORY_TABLE}")
        if memories:
            destination.execute(
                f"CREATE TABLE {MEMORY_TABLE} (agent_id INTEGER PRIMARY KEY, records TEXT NOT NULL, round INTEGER NOT NULL)"
            )
            destination.executemany(
                f"INSERT INTO {MEMORY_TABLE} (agent_id, records, round) VALUES (?, ?, ?)",
                [(int(agent_id), blob, int(round_num)) for agent_id, blob in memories.items()],
            )
        destination.commit()
    finally:
        destination.close()
        source.close()
    os.replace(temp, target)
    return target


def read_checkpoint_info(db_path: str) -> Optional[Dict[str, Any]]:
    """``{"round", "clock"}`` of the checkpoint, or None when there is none (or it is unreadable)."""
    return _read_marker(checkpoint_path(db_path))


def read_db_marker(db_path: str) -> Optional[Dict[str, Any]]:
    """The marker carried by the live database itself (present once a checkpoint has been restored)."""
    return _read_marker(db_path)


def _read_marker(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(f"SELECT round, clock FROM {CHECKPOINT_TABLE} LIMIT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        clock = json.loads(row[1]) if row[1] else {}
    except ValueError:
        clock = {}
    return {"round": int(row[0]), "clock": clock if isinstance(clock, dict) else {}}


def read_memories(db_path: str, *, expect_round: Optional[int] = None) -> Dict[int, str]:
    """``{agent_id: memory JSON}`` stored in a database or checkpoint file ({} when it holds none).

    Every stored memory is tagged with the round of the checkpoint that wrote it. With ``expect_round`` only
    memory of exactly that round is returned, so a database that still carries the memory of an older
    checkpoint (its newer checkpoint failed to write) can never hand agents a history from the wrong round.
    This only reads: the live database is open in the platform's own connection, which may hold a lock, so a
    resume must not try to modify it.
    """
    if not os.path.isfile(db_path):
        return {}
    try:
        connection = sqlite3.connect(db_path, timeout=5)
        try:
            rows = connection.execute(f"SELECT agent_id, records, round FROM {MEMORY_TABLE}").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return {
        int(agent_id): records
        for agent_id, records, stored_round in rows
        if expect_round is None or stored_round == expect_round
    }


def checkpoint_has_memory(db_path: str, expect_round: Optional[int] = None) -> bool:
    return bool(read_memories(checkpoint_path(db_path), expect_round=expect_round))


def restore_checkpoint(db_path: str) -> None:
    """Make the checkpoint the live database (any half-written journal of the old one is dropped)."""
    source = checkpoint_path(db_path)
    for suffix in ("-journal", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass
    shutil.copyfile(source, db_path)


# --- the plan ------------------------------------------------------------------

@dataclass
class ResumePlan:
    platform: str
    resumable: bool
    reason: Optional[str] = None
    #: the run continues with round ``round + 1``
    round: int = 0
    #: the log is cut back to this many bytes
    offset: int = 0
    #: the database is restored from a checkpoint of exactly this round
    exact: bool = False
    #: that checkpoint also carries the agents' chat memory
    memory: bool = False
    total_actions: int = 0
    #: ``round_start`` ids of the unfinished round that will be redone, if it was logged
    unfinished_ids: Optional[List[int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform, "resumable": self.resumable, "reason": self.reason,
            "round": self.round, "exact": self.exact, "memory": self.memory,
        }


def plan_resume(sim_dir: str, platform: str) -> ResumePlan:
    """Where to resume ``platform`` of the run in ``sim_dir``."""
    log_path = os.path.join(sim_dir, platform, "actions.jsonl")
    db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
    scan = scan_log(log_path)
    if not scan.exists:
        return ResumePlan(platform, False, "no action log (only the parallel script writes one)")
    if not scan.setup_done:
        return ResumePlan(platform, False, "the run stopped while it was still setting up; start it over")

    resume_round = scan.last_round
    checkpoint = read_checkpoint_info(db_path)
    exact = False
    if checkpoint is not None:
        if checkpoint["round"] <= scan.last_round and checkpoint["round"] in scan.round_offsets:
            # The log can be ahead of the checkpoint by one round (a stop between the two writes):
            # go back to the checkpoint so the database and the log agree.
            resume_round = checkpoint["round"]
            exact = True
    elif not os.path.isfile(db_path):
        return ResumePlan(platform, False, "the platform database is missing")

    return ResumePlan(
        platform=platform,
        resumable=True,
        round=resume_round,
        offset=scan.round_offsets[resume_round],
        exact=exact,
        memory=exact and checkpoint_has_memory(db_path, expect_round=resume_round),
        total_actions=scan.round_totals.get(resume_round, 0),
        unfinished_ids=scan.started.get(resume_round + 1),
    )


def truncate_log(path: str, offset: int) -> None:
    """Cut an action log back to ``offset`` bytes (drops the unfinished round and anything after it)."""
    with open(path, "r+b") as handle:
        handle.truncate(offset)


# --- replaying the scheduling ---------------------------------------------------

def replay_schedule(
    behavior: Any,
    rounds_done: int,
    *,
    agent_exists: Callable[[int], bool],
    initial_posted: bool,
    logged_ids: Mapping[int, List[int]],
) -> List[List[int]]:
    """Run the behaviour engine through the finished rounds without any model call.

    ``behavior`` is a ``sim_behavior.PlatformBehavior`` in its fresh state. Afterwards its random generators
    and reaction delays are what they were when round ``rounds_done`` ended. ``rounds_done`` is the number
    of finished loop rounds (log rounds ``1..rounds_done``). The ids chosen for each of them must equal the
    logged ``round_start`` ids; a mismatch (a changed configuration or seed) raises ``ScheduleMismatch``.

    The steps mirror the run loop exactly: initial posts start the reaction delays, then every round fires
    its due events and picks its agents.
    """
    if behavior.v2 and initial_posted:
        behavior.initial_posts_published()

    minutes_per_round = behavior.minutes_per_round
    planned: List[List[int]] = []
    for loop_round in range(rounds_done):
        simulated_hour = ((loop_round * minutes_per_round) // 60) % 24
        if behavior.v2:
            behavior.events_due(loop_round)
        chosen = [agent_id for agent_id in behavior.select_active(loop_round, simulated_hour) if agent_exists(agent_id)]
        planned.append(chosen)
        expected = logged_ids.get(loop_round + 1)
        if expected is not None and list(expected) != chosen:
            raise ScheduleMismatch(
                f"round {loop_round + 1}: the original run woke agents {list(expected)}, "
                f"the replay chose {chosen}. The configuration or the seed changed since that run."
            )
    return planned


# --- restoring the platform clocks ----------------------------------------------

def clock_snapshot(platform_name: str, platform_obj: Any) -> Dict[str, Any]:
    """What a checkpoint stores about the platform's clock (best effort)."""
    try:
        if platform_name == "twitter":
            return {"time_step": int(platform_obj.sandbox_clock.time_step)}
        simulated_now = platform_obj.sandbox_clock.time_transfer(datetime.now(), platform_obj.start_time)
        return {"sim_time": simulated_now.isoformat()}
    except Exception:
        return {}


def restore_clock(platform_name: str, platform_obj: Any, db_path: str, clock: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Continue the platform's clock from where the finished rounds left it.

    A fresh OASIS platform starts its clock at zero (Twitter: a step counter; Reddit: wall clock mapped to
    simulated time), so new posts would look older than the restored ones. Uses the checkpoint's clock
    when available, else the newest time found in the ``trace`` table. Returns a description of what was
    set, or None when nothing could be determined.
    """
    clock = dict(clock or {})
    try:
        if platform_name == "twitter":
            step = clock.get("time_step")
            if step is None:
                with closing(sqlite3.connect(db_path)) as connection:
                    row = connection.execute("SELECT MAX(CAST(created_at AS INTEGER)) FROM trace").fetchone()
                step = (int(row[0]) + 1) if row and row[0] is not None else None
            if step is None:
                return None
            platform_obj.sandbox_clock.time_step = int(step)
            return f"time_step={int(step)}"

        sim_time = clock.get("sim_time")
        if sim_time is None:
            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute("SELECT MAX(created_at) FROM trace").fetchone()
            sim_time = row[0] if row and row[0] else None
        if sim_time is None:
            return None
        resumed_at = datetime.fromisoformat(str(sim_time).replace(" ", "T", 1))
        platform_obj.start_time = resumed_at
        platform_obj.sandbox_clock.real_start_time = datetime.now()
        return f"sim_time={resumed_at.isoformat()}"
    except Exception:
        return None
