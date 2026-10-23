"""
OASIS-facing helpers shared by the simulation run scripts.

``sim_behavior`` holds the pure decisions (who acts, who follows whom, which
events fire). This module executes them against an OASIS environment: seeding
the follow graph, injecting scheduled events and interviewing agents (used by
both the IPC command loop and the end-of-run poll).

``oasis`` is imported lazily, inside the functions that need its action classes,
so the module loads (and can be unit tested with fakes) without the simulation
stack installed.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import sqlite3
import threading
import time
import traceback
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: Seconds to wait before each retry of the agents that gave no reply to the final poll. A provider
#: that throttles ("402: retry after in-flight requests settle", "429") needs the pause: retrying at
#: once only meets the same wall. The number of delays is the number of retries.
FINAL_POLL_RETRY_DELAYS: Tuple[float, ...] = (5.0, 15.0, 30.0)


def _action_classes():
    """``(ActionType, ManualAction)`` from OASIS (patched in tests)."""
    from oasis import ActionType, ManualAction

    return ActionType, ManualAction


# --- database helpers --------------------------------------------------------

def max_trace_rowid(db_path: str) -> int:
    """Highest rowid in the platform's ``trace`` table (0 when empty/missing).

    The run scripts log agent actions by reading new ``trace`` rows after each
    round. Advancing their cursor to this value after a manual step (seeded
    follows, injected events, initial posts) keeps those rows from being logged
    a second time as ordinary round actions.
    """
    if not os.path.exists(db_path):
        return 0
    try:
        connection = sqlite3.connect(db_path)
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM trace"
            ).fetchone()
        finally:
            connection.close()
        return int(row[0])
    except sqlite3.Error:
        return 0


def read_interview_result(
    db_path: str, agent_id: int, after_rowid: int = 0
) -> Dict[str, Any]:
    """The agent's latest interview recorded in ``trace`` after ``after_rowid``.

    Returns ``{"agent_id", "response", "timestamp"}``; ``response`` is None when
    no interview row exists yet.
    """
    ActionType, _ = _action_classes()
    result: Dict[str, Any] = {"agent_id": agent_id, "response": None, "timestamp": None}
    if not os.path.exists(db_path):
        return result

    try:
        connection = sqlite3.connect(db_path)
        try:
            row = connection.execute(
                """
                SELECT info, created_at FROM trace
                WHERE action = ? AND user_id = ? AND rowid > ?
                ORDER BY rowid DESC LIMIT 1
                """,
                (ActionType.INTERVIEW.value, agent_id, after_rowid),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as error:
        print(f"  读取Interview结果失败: {error}")
        return result

    if row:
        info_json, created_at = row
        try:
            info = json.loads(info_json) if info_json else {}
            result["response"] = info.get("response", info)
        except (json.JSONDecodeError, AttributeError):
            result["response"] = info_json
        result["timestamp"] = created_at
    return result


# --- model-call failures: what OASIS swallows --------------------------------

ERROR_MESSAGE_LIMIT = 240
_STATUS_RE = re.compile(r"Error code:\s*(\d{3})|\bHTTP\s*(\d{3})\b|status[_ ]code[:= ]+(\d{3})", re.I)


def classify_error(error: Any) -> Tuple[str, str]:
    """``(kind, short message)`` for a failed model call (an exception or its text).

    Kinds: ``http_402`` (no credit / token budget), ``http_429`` (rate limit), ``auth`` (401/403, key
    rejected), ``http_5xx`` (provider error), ``timeout``, ``connection`` and ``other``. The UI turns the
    kind into advice; the message is the provider's own words, shortened.
    """
    text = " ".join(str(error).split())
    message = text[:ERROR_MESSAGE_LIMIT]
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        match = _STATUS_RE.search(text)
        status = int(next(group for group in match.groups() if group)) if match else None

    if status == 402:
        return "http_402", message
    if status == 429:
        return "http_429", message
    if status in (401, 403):
        return "auth", message
    if status == 408:
        return "timeout", message
    if status is not None and status >= 500:
        return "http_5xx", message
    name = type(error).__name__.lower() if isinstance(error, BaseException) else ""
    lowered = text.lower()
    if "timeout" in name or "timed out" in lowered or "timeout" in lowered:
        return "timeout", message
    if "connection" in name or "connect" in lowered:
        return "connection", message
    return "other", message


_FALLBACK_KINDS = {"http_402", "http_429", "auth", "http_5xx", "timeout", "connection"}


def should_fall_back(error: BaseException) -> bool:
    """Whether another model could succeed where this call failed (quota, size, outage, bad key).

    A malformed request (HTTP 400, a bug in our code) would fail on any model, so it is not retried.
    """
    kind, _ = classify_error(error)
    if kind in _FALLBACK_KINDS:
        return True
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        match = _STATUS_RE.search(str(error))
        status = int(next(group for group in match.groups() if group)) if match else None
    return status == 413  # request too large for this model's per-minute token limit


DEFAULT_LLM_CONCURRENCY = 30


def platform_llm_concurrency(
    platform: str,
    run_settings: Optional[Mapping[str, Any]],
    environ: Mapping[str, str],
) -> int:
    """Max simultaneous model requests for one platform of a run.

    1. ``LLM_<PLATFORM>_MAX_CONCURRENCY`` (``LLM_TWITTER_...`` / ``LLM_REDDIT_...``) when set: that platform's own cap.
    2. else ``LLM_MAX_CONCURRENCY`` (default 30) for every platform.
    3. A replicate of an ensemble shares the provider with the other replicates running at the same time
       (``llm_concurrency_share``), so it gets its share of the number from 1 or 2.
    Older replicates carry a precomputed ``llm_semaphore`` instead; a plain run may set ``run.llm_semaphore``
    in its config. Both are used when neither 1 nor a share applies.
    """
    def read(name: str) -> Optional[int]:
        try:
            value = int(environ.get(name) or 0)
        except ValueError:
            return None
        return value if value > 0 else None

    settings = run_settings or {}
    specific = read(f"LLM_{platform.upper()}_MAX_CONCURRENCY")
    general = read("LLM_MAX_CONCURRENCY")
    try:
        share = max(1, int(settings.get("llm_concurrency_share") or 1))
    except (TypeError, ValueError):
        share = 1
    has_share = bool(settings.get("llm_concurrency_share"))

    if specific is not None:
        return max(1, specific // share)
    if has_share:
        return max(1, (general or DEFAULT_LLM_CONCURRENCY) // share)
    if settings.get("llm_semaphore"):
        return max(1, int(settings["llm_semaphore"]))
    return general or DEFAULT_LLM_CONCURRENCY


def model_client_options(environ: Mapping[str, str]) -> Dict[str, Any]:
    """``timeout`` / ``max_retries`` for the model client, from LLM_MODEL_TIMEOUT / LLM_MODEL_MAX_RETRIES.

    camel's own defaults (180 s, 3 silent retries) let one stuck request hold a round for ~12 minutes
    before any error, or the backup model, shows up. A value that is unset or not a valid number is
    left out, so the library default applies.
    """
    options: Dict[str, Any] = {}
    try:
        timeout = float(environ.get("LLM_MODEL_TIMEOUT") or 0)
    except ValueError:
        timeout = 0.0
    if timeout > 0:
        options["timeout"] = timeout
    raw_retries = environ.get("LLM_MODEL_MAX_RETRIES")
    if raw_retries not in (None, ""):
        try:
            retries = int(raw_retries)
        except ValueError:
            retries = -1
        if retries >= 0:
            options["max_retries"] = retries
    return options


def apply_model_client_options(model: Any, options: Mapping[str, Any]) -> Any:
    """Make ``max_retries`` take effect on a camel OpenAI model.

    camel's OpenAIModel accepts ``max_retries`` but its base class resets it to 3 before the clients are
    built, so the factory argument alone does nothing. The SDK clients read ``max_retries`` on every
    request, so setting it on them works. (``timeout`` is honoured by the factory as is.)
    """
    if "max_retries" not in options:
        return model
    retries = int(options["max_retries"])
    for name in ("_client", "_async_client"):
        client = getattr(model, name, None)
        if client is not None and hasattr(client, "max_retries"):
            client.max_retries = retries
    if hasattr(model, "_max_retries"):
        model._max_retries = retries
    return model


# --- agents' chat memory ------------------------------------------------------------------------

def dump_agent_memory(agent: Any) -> str:
    """The agent's chat memory (system prompt, observations, replies, tool calls) as camel's own JSON."""
    from camel.storages.key_value_storages.json import CamelJSONEncoder

    records = [context.memory_record.to_dict() for context in agent.memory.retrieve()]
    return json.dumps(records, ensure_ascii=False, cls=CamelJSONEncoder)


def load_agent_memory(agent: Any, blob: str) -> int:
    """Replace the agent's chat memory with what ``dump_agent_memory`` produced; returns the records loaded.

    The agent is left untouched when the blob cannot be read at all (a half-restored memory would be worse
    than a fresh one). A single unreadable record is skipped.
    """
    from camel.memories import MemoryRecord
    from camel.storages.key_value_storages.json import CamelJSONEncoder, JsonStorage

    def hook(data):
        if "__enum__" in data:
            name, member = data["__enum__"].split(".")
            return getattr(CamelJSONEncoder.CAMEL_ENUMS[name], member)
        return data

    records = []
    for record_dict in json.loads(blob, object_hook=hook):
        try:
            records.append(MemoryRecord.from_dict(record_dict))
        except Exception:
            continue
    if not records:
        return 0
    agent.memory.clear()
    agent.memory.write_records(records)
    return len(records)


def collect_agent_memories(agent_graph: Any) -> Dict[int, str]:
    """``{agent_id: memory JSON}`` for every agent of the graph (an agent that cannot be dumped is left out)."""
    memories: Dict[int, str] = {}
    for agent_id, agent in agent_graph.get_agents():
        try:
            memories[int(agent_id)] = dump_agent_memory(agent)
        except Exception:
            continue
    return memories


def restore_agent_memories(agent_graph: Any, memories: Mapping[int, str]) -> Tuple[int, List[int]]:
    """Give each agent back its saved chat memory. Returns ``(agents restored, agent ids that failed)``."""
    restored, failed = 0, []
    for agent_id, blob in memories.items():
        try:
            agent = agent_graph.get_agent(agent_id)
            if load_agent_memory(agent, blob):
                restored += 1
            else:
                failed.append(agent_id)
        except Exception:
            failed.append(agent_id)
    return restored, failed


class ModelCallLog:
    """The last few model calls (which model, how long, what came back), for explaining a failure.

    OASIS reads ``response.output_messages[0]`` and fails with a bare ``list index out of range`` when a model
    answered with nothing usable; the exception says nothing about the reply. Every model the run builds is
    wrapped by ``install_call_recording`` and writes one line here per call, so a failed step can print what
    each of its calls really did. Cheap: a ring buffer of short text lines.
    """

    def __init__(self, size: int = 40) -> None:
        self._calls: "deque[Dict[str, Any]]" = deque(maxlen=size)

    def add(self, entry: Dict[str, Any]) -> None:
        self._calls.append(entry)

    def recent(self, count: int = 8) -> List[Dict[str, Any]]:
        return list(self._calls)[-count:]

    def format_recent(self, count: int = 8) -> List[str]:
        return [format_call(entry) for entry in self.recent(count)]


CALL_LOG = ModelCallLog()


def format_call(entry: Mapping[str, Any]) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(entry["at"]))
    if not entry["ok"]:
        return f"{stamp} {entry['label']}: {entry['seconds']:.1f}s FAILED {entry['error']}"
    flag = "  <-- NO USABLE ANSWER (the agent step will fail)" if entry["empty"] else ""
    return (
        f"{stamp} {entry['label']}: {entry['seconds']:.1f}s choices={entry['choices']} "
        f"finish={entry['finish']} content_chars={entry['content_chars']} tool_calls={entry['tool_calls']} "
        f"tokens={entry['tokens']}{flag}"
    )


def summarize_response(response: Any) -> Dict[str, Any]:
    """What a chat completion contains, in a few numbers (never the text itself)."""
    choices = list(getattr(response, "choices", None) or [])
    first = choices[0] if choices else None
    message = getattr(first, "message", None)
    content = getattr(message, "content", None) or ""
    tool_calls = len(getattr(message, "tool_calls", None) or [])
    usage = getattr(response, "usage", None)
    return {
        "choices": len(choices),
        "finish": getattr(first, "finish_reason", None),
        "content_chars": len(content) if isinstance(content, str) else -1,
        "tool_calls": tool_calls,
        "tokens": getattr(usage, "total_tokens", None),
        # no choice, or a choice with neither text nor a tool call: camel drops it and OASIS then fails
        "empty": not choices or (not content and not tool_calls),
    }


def install_call_recording(model: Any, label: str, call_log: Optional[ModelCallLog] = None) -> Any:
    """Make ``model`` note every call (sync and async) in ``call_log``. Behaviour is otherwise unchanged."""
    log = CALL_LOG if call_log is None else call_log
    original_run, original_arun = model.run, model.arun

    def note(started: float, response: Any = None, error: Optional[BaseException] = None) -> None:
        try:
            entry: Dict[str, Any] = {"at": time.time(), "label": label, "seconds": time.time() - started}
            if error is not None:
                kind, message = classify_error(error)
                entry.update(ok=False, error=f"{kind}: {message[:140]}")
            else:
                entry.update(ok=True, **summarize_response(response))
            log.add(entry)
        except Exception:
            pass  # recording must never change what a call does

    def run(*args, **kwargs):
        started = time.time()
        try:
            response = original_run(*args, **kwargs)
        except BaseException as error:
            note(started, error=error)
            raise
        note(started, response)
        return response

    async def arun(*args, **kwargs):
        started = time.time()
        try:
            response = await original_arun(*args, **kwargs)
        except BaseException as error:
            note(started, error=error)
            raise
        note(started, response)
        return response

    model.run, model.arun = run, arun
    return model


class Pacer:
    """Spaces calls at least ``interval`` seconds apart, however many callers wait.

    Each caller reserves the next free slot and sleeps until it, so the order is first come first served
    and nobody holds a lock while sleeping. Share one pacer between everything that talks to the same
    provider (here: the fallback model of both platforms).
    """

    def __init__(self, interval: float) -> None:
        self.interval = max(0.0, float(interval or 0.0))
        self._next = 0.0
        self._lock = threading.Lock()

    def reserve(self) -> float:
        """Seconds the caller must wait before its call may start."""
        if self.interval <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
            return start - now

    def wait(self) -> None:
        delay = self.reserve()
        if delay > 0:
            time.sleep(delay)

    async def await_turn(self) -> None:
        delay = self.reserve()
        if delay > 0:
            await asyncio.sleep(delay)


def install_model_fallback(
    primary: Any,
    fallback: Any,
    on_fallback: Optional[Callable[[BaseException], None]] = None,
    pacer: Optional[Pacer] = None,
) -> Any:
    """Make ``primary`` hand a failed call to ``fallback`` (camel model backends, sync and async).

    Only calls that failed in a way another model could fix (see ``should_fall_back``) are retried, once,
    on ``fallback``; any other error, and a failure of the fallback itself, propagates unchanged.
    """
    original_run, original_arun = primary.run, primary.arun

    def run(*args, **kwargs):
        try:
            return original_run(*args, **kwargs)
        except Exception as error:
            if not should_fall_back(error):
                raise
            _notify(on_fallback, error)
            if pacer is not None:
                pacer.wait()
            return fallback.run(*args, **kwargs)

    async def arun(*args, **kwargs):
        try:
            return await original_arun(*args, **kwargs)
        except Exception as error:
            if not should_fall_back(error):
                raise
            _notify(on_fallback, error)
            if pacer is not None:
                await pacer.await_turn()
            return await fallback.arun(*args, **kwargs)

    primary.run, primary.arun = run, arun
    return primary


def _notify(callback: Optional[Callable[[BaseException], None]], error: BaseException) -> None:
    if callback is None:
        return
    try:
        callback(error)
    except Exception:
        pass  # reporting must never break the simulation


# id(agent) -> (tracker, agent_id) for the agents of the round that is running
_WATCHED: Dict[int, Tuple["FailureTracker", int]] = {}


class FailureTracker:
    """Records the agents whose model call failed during a round.

    OASIS catches an exception from the model, logs it to its own agent log and returns it, so the round
    loop only sees an agent that did nothing. ``install_failure_tracking`` wraps the agent method; the loop
    calls ``begin_round`` with the agents it woke and ``end_round`` afterwards to get the failures. A failure
    is also reported at once through ``on_failure`` so the UI can show it while the round is still running.
    """

    def __init__(self) -> None:
        self.failures: List[Dict[str, Any]] = []
        self._watched: List[int] = []
        self._on_failure: Optional[Callable[[Dict[str, Any]], None]] = None

    def begin_round(
        self,
        agents: Iterable[Tuple[int, Any]],
        on_failure: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._release()
        self.failures = []
        self._on_failure = on_failure
        for agent_id, agent in agents:
            _WATCHED[id(agent)] = (self, agent_id)
            self._watched.append(id(agent))

    def end_round(self) -> List[Dict[str, Any]]:
        self._release()
        done, self.failures = self.failures, []
        return done

    def _release(self) -> None:
        for key in self._watched:
            _WATCHED.pop(key, None)
        self._watched = []

    def _record(self, agent_id: int, error: BaseException) -> None:
        kind, message = classify_error(error)
        failure = {"agent_id": agent_id, "kind": kind, "message": message}
        self.failures.append(failure)
        if self._on_failure is not None:
            try:
                self._on_failure(failure)
            except Exception:
                pass  # reporting must never break the simulation


def install_failure_tracking(agent_class: Any) -> bool:
    """Wrap ``agent_class.perform_action_by_llm`` so a returned exception is recorded. Idempotent."""
    if getattr(agent_class, "_failure_tracking_installed", False):
        return False
    original = agent_class.perform_action_by_llm

    @functools.wraps(original)
    async def tracked(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        if isinstance(result, BaseException):
            entry = _WATCHED.get(id(self))
            if entry is not None:
                entry[0]._record(entry[1], result)
        return result

    agent_class.perform_action_by_llm = tracked
    agent_class._failure_tracking_installed = True
    return True


# --- interviews --------------------------------------------------------------

async def batch_interview(
    env,
    agent_graph,
    db_path: str,
    prompts: Mapping[int, str],
    *,
    chunk_size: Optional[int] = None,
    log: Callable[[str], None] = print,
) -> Dict[int, Dict[str, Any]]:
    """Interview several agents, returning ``{agent_id: result}``.

    Every prompt is sent as an ``INTERVIEW`` ``ManualAction``; agents in one
    chunk are interviewed concurrently by a single ``env.step`` (a chunk
    defaults to all agents). With a smaller ``chunk_size`` one failing step only
    costs that chunk. Each result is read back from the ``trace`` rows written
    *after* the step started, so an older interview of the same agent is never
    returned by mistake. An agent that could not be interviewed gets a result
    with ``response`` None and an ``error`` message.
    """
    ActionType, ManualAction = _action_classes()
    agent_ids = list(prompts)
    size = chunk_size or max(1, len(agent_ids))
    results: Dict[int, Dict[str, Any]] = {}

    for start in range(0, len(agent_ids), size):
        chunk = agent_ids[start:start + size]
        before = max_trace_rowid(db_path)
        actions = {}
        for agent_id in chunk:
            try:
                agent = agent_graph.get_agent(agent_id)
            except Exception as error:
                log(f"  警告: 无法获取Agent {agent_id}: {error}")
                results[agent_id] = {
                    "agent_id": agent_id,
                    "response": None,
                    "timestamp": None,
                    "error": f"unknown agent: {error}",
                    "unknown_agent": True,
                }
                continue
            actions[agent] = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompts[agent_id]},
            )
        if not actions:
            continue

        step_error: Optional[str] = None
        try:
            await env.step(actions)
        except Exception as error:
            step_error = str(error)
            log(f"  Interview步骤失败: {type(error).__name__}: {error}")
            # The bare message (e.g. "list index out of range") hides where it came from and what the model
            # returned; print both so the cause can be read from the log.
            for line in traceback.format_exc().rstrip().splitlines()[-8:]:
                log(f"    {line}")
            recent = CALL_LOG.format_recent(8)
            if recent:
                log("  最近的模型调用 (recent model calls):")
                for line in recent:
                    log(f"    {line}")

        for agent_id in chunk:
            if agent_id in results:
                continue
            result = read_interview_result(db_path, agent_id, after_rowid=before)
            if result["response"] is None and step_error:
                result["error"] = step_error
            results[agent_id] = result
    return results


# --- manual steps: seeded follows and scheduled events -----------------------

async def apply_seed_follows(
    env, follows: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Execute the planned ``(follower, followee)`` pairs in a single step.

    Returns the pairs that were submitted (pairs whose follower is not in the
    agent graph are skipped).
    """
    ActionType, ManualAction = _action_classes()
    per_agent: Dict[Any, List[Any]] = {}
    submitted: List[Tuple[int, int]] = []
    for follower_id, followee_id in follows:
        try:
            follower = env.agent_graph.get_agent(follower_id)
        except Exception:
            continue
        per_agent.setdefault(follower, []).append(
            ManualAction(
                action_type=ActionType.FOLLOW,
                action_args={"followee_id": followee_id},
            )
        )
        submitted.append((follower_id, followee_id))

    if per_agent:
        await env.step(
            {
                agent: (actions[0] if len(actions) == 1 else actions)
                for agent, actions in per_agent.items()
            }
        )
    return submitted


async def inject_scheduled_events(
    env,
    events: Sequence[Mapping[str, Any]],
    *,
    log_round: int,
    agent_names: Mapping[int, str],
    action_logger=None,
    log: Callable[[str], None] = print,
) -> List[Mapping[str, Any]]:
    """Post each due scheduled event as its ``poster_agent_id``.

    Events whose poster is not in the agent graph are skipped (and reported
    through ``log``). Each posted event is written to ``actions.jsonl`` as a
    ``CREATE_POST`` with ``phase: "injected"`` and its ``event_id``. Returns the
    events that were posted.
    """
    ActionType, ManualAction = _action_classes()
    per_agent: Dict[Any, List[Any]] = {}
    posted: List[Mapping[str, Any]] = []
    for event in events:
        poster_id = event.get("poster_agent_id")
        content = event.get("content", "")
        try:
            poster = env.agent_graph.get_agent(poster_id)
        except Exception:
            log(f"  警告: 定时事件 {event.get('id')} 的发布者 Agent {poster_id} 不存在，已跳过")
            continue
        per_agent.setdefault(poster, []).append(
            ManualAction(
                action_type=ActionType.CREATE_POST,
                action_args={"content": content},
            )
        )
        posted.append(event)

    if per_agent:
        await env.step(
            {
                agent: (actions[0] if len(actions) == 1 else actions)
                for agent, actions in per_agent.items()
            }
        )

    if action_logger is not None:
        for event in posted:
            poster_id = event.get("poster_agent_id")
            action_logger.log_action(
                round_num=log_round,
                agent_id=poster_id,
                agent_name=agent_names.get(poster_id, f"Agent_{poster_id}"),
                action_type="CREATE_POST",
                action_args={"content": event.get("content", "")},
                phase="injected",
                extra={"event_id": event.get("id")},
            )
    return posted


# --- the end-of-run outcome poll ---------------------------------------------

async def run_final_poll(
    env,
    agent_graph,
    db_path: str,
    config: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    *,
    chunk_size: int = 5,
    retry_delays: Sequence[float] = FINAL_POLL_RETRY_DELAYS,
    log: Callable[[str], None] = print,
    status: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """Interview every agent once on the outcome questions.

    All agents get the same JSON-only prompt (``sim_poll.build_poll_prompt``).
    They are interviewed in chunks so one failing request only costs a chunk
    and only ``chunk_size`` requests are in flight at once. Agents that gave no
    reply at all (no row, or an empty one) are retried after each pause in
    ``retry_delays``, in ever smaller chunks (down to one at a time), until all
    have answered or the delays run out. Replies that cannot be parsed are kept
    (``parse_ok: false``) rather than dropped, and are not retried, so the
    ensemble can report a parse rate. Returns the ``final_poll.json`` rows,
    ordered by agent id.
    """
    import sim_poll

    prompt = sim_poll.build_poll_prompt(questions)
    agents = sorted(
        (cfg for cfg in config.get("agent_configs", []) if cfg.get("agent_id") is not None),
        key=lambda cfg: int(cfg["agent_id"]),
    )
    prompts = {int(cfg["agent_id"]): prompt for cfg in agents}

    def report(state: str, results: Mapping[int, Dict[str, Any]], attempt: int, retry_in: Optional[float] = None) -> None:
        """Tell the caller how many agents have answered and why the others have not (for the UI)."""
        if status is None:
            return
        errors = [r["error"] for r in results.values() if r.get("error") and _is_blank(r.get("response"))]
        kind, message = classify_error(errors[-1]) if errors else (None, None)
        snapshot = {
            "state": state,
            "answered": sum(1 for r in results.values() if not _is_blank(r.get("response"))),
            "total": len(prompts),
            "attempt": attempt,
            "max_attempts": len(retry_delays),
            "retry_in": retry_in,
            "error_kind": kind,
            "message": message,
        }
        try:
            status(snapshot)
        except Exception:
            pass  # reporting must never break the poll

    report("running", {}, 0)
    results = await batch_interview(
        env, agent_graph, db_path, prompts, chunk_size=chunk_size, log=log
    )
    report("running", results, 0)

    attempts_used = 0
    for attempt, delay in enumerate(retry_delays, start=1):
        silent = _silent_agents(results)
        if not silent:
            break
        attempts_used = attempt
        log(f"  最终问卷: {len(silent)} 个Agent没有回复，{delay:g}秒后重试（第 {attempt}/{len(retry_delays)} 次）")
        report("waiting", results, attempt, retry_in=delay)
        if delay > 0:
            await asyncio.sleep(delay)
        retried = await batch_interview(
            env,
            agent_graph,
            db_path,
            {agent_id: prompt for agent_id in silent},
            chunk_size=max(1, chunk_size // (2 ** attempt)),
            log=log,
        )
        for agent_id, result in retried.items():
            if not _is_blank(result.get("response")):
                results[agent_id] = result
            elif result.get("error"):
                results[agent_id]["error"] = result["error"]  # keep the latest reason
        report("running", results, attempt)

    report("done", results, attempts_used)

    rows: List[Dict[str, Any]] = []
    for cfg in agents:
        agent_id = int(cfg["agent_id"])
        result = results.get(agent_id, {})
        response = result.get("response")
        if response is not None and not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        error = result.get("error")
        if response is not None and not response.strip() and not error:
            error = "the model returned an empty reply"
        rows.append(
            sim_poll.poll_row(
                agent_id,
                cfg.get("entity_name", f"Agent_{agent_id}"),
                str(cfg.get("stance", "neutral")),
                response,
                questions,
                error=error,
            )
        )
    return rows


def _is_blank(response: Any) -> bool:
    """No reply at all: nothing was recorded, or the model sent an empty text."""
    return response is None or (isinstance(response, str) and not response.strip())


def _silent_agents(results: Mapping[int, Mapping[str, Any]]) -> List[int]:
    """The agents worth asking again (an unknown agent never will answer)."""
    return [
        agent_id for agent_id, result in results.items()
        if not result.get("unknown_agent") and _is_blank(result.get("response"))
    ]


def write_final_poll(sim_dir: str, rows: Sequence[Mapping[str, Any]]) -> str:
    """Write ``final_poll.json`` (a list of rows) atomically; returns its path."""
    path = os.path.join(sim_dir, "final_poll.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(list(rows), handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())  # a crash after the rename must not leave a zero-filled file
    os.replace(tmp_path, path)
    return path
