"""
Seeded ensembles: N replicate runs of one prepared simulation, aggregated.

A single simulation run is one stochastic sample, so it cannot say how much of
a result is signal and how much is luck. An ensemble clones a prepared
("base") simulation into N *replicates* that differ only in their seed, runs
them with bounded concurrency, has every replicate finish with a structured
poll of its agents, and aggregates polls and behavioural metrics into
distributions (``ensemble_aggregator``).

A seed makes the *schedule* of a replicate reproducible (who is woken when,
reaction delays, the seeded follow graph, scheduled events). It does not make
LLM output identical, so replicates with different seeds really are different
samples, and the same seed does not replay a run.

Files, under ``uploads/ensembles/<ensemble_id>/``::

    ensemble.json           definition + live status of the ensemble and its replicates
    outcome_questions.json  the questions every replicate's agents answer at the end
    summary.json            written by the aggregator
    summary.md

Replicates are ordinary simulation directories (``<base>__<token>__rNN``)
hidden from the simulation list. They never write to the Zep graph: N copies of simulated
chatter would pollute the knowledge graph.
"""

import copy
import hashlib
import json
import math
import os
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..utils.atomic_write import write_json_atomic
from ..utils.logger import get_logger
from .ensemble_aggregator import build_summary, write_summary
from .outcome_questions import derive_outcome_questions, validate_outcome_questions
from .simulation_manager import SimulationManager, SimulationState, SimulationStatus
from .simulation_runner import RunnerStatus, SimulationRunner

logger = get_logger('mirofish.ensemble')

DEFAULT_REPLICATES = 5
MAX_REPLICATES = 50
MAX_CONCURRENCY = 4
MAX_ROUNDS_LIMIT = 100000
#: Fewer successful replicates than this cannot be aggregated into a distribution.
MIN_REPLICATES_TO_AGGREGATE = 2
POLL_INTERVAL_SECONDS = 2.0
#: Maximum concurrent LLM requests per platform for one run; shared among replicates.
def _base_llm_semaphore() -> int:
    """LLM_MAX_CONCURRENCY from .env (shared by the ensemble's runs), default 30."""
    try:
        return max(1, int(os.environ.get("LLM_MAX_CONCURRENCY") or 30))
    except ValueError:
        return 30


BASE_LLM_SEMAPHORE = 30  # default, kept for reference; see _base_llm_semaphore()
PLATFORMS_SUPPORTED = ("parallel",)

TERMINAL_STATUSES = ("completed", "partial", "failed", "stopped")
#: An ensemble in one of these states can be resumed (its unfinished runs continue, finished ones are kept).
RESUMABLE_STATUSES = ("stopped", "failed", "partial")
#: A replicate that failed with this error was cut off, not broken, and may be resumed.
INTERRUPTED_ERROR = "interrupted"
#: ... as did one whose process left no run state at all (it never got going; resume_info decides what to do).
NO_RUN_STATE_ERROR = "no run state was recorded"
#: ``SimulationRunner.resume_info`` reasons that mean the run produced nothing worth keeping: start it over.
_NOTHING_TO_KEEP = ("has not been run yet", "still setting up", "database is missing")
REPLICATE_TERMINAL = ("completed", "failed", "stopped")


class EnsembleError(ValueError):
    """An ensemble request that cannot be honoured; ``status_code`` is the HTTP status."""

    status_code = 400


class EnsembleNotFound(EnsembleError):
    status_code = 404


class EnsembleConflict(EnsembleError):
    status_code = 409


class EnsembleCorrupt(EnsembleError):
    """``ensemble.json`` exists but cannot be read (for example zero-filled by a crash)."""

    status_code = 500


def derive_replicate_seed(base_seed: int, index: int) -> int:
    """A 32-bit seed derived deterministically from the base seed and replicate index."""
    return int(hashlib.sha256(f"{base_seed}:{index}".encode("utf-8")).hexdigest()[:8], 16)


def replicate_simulation_id(base_simulation_id: str, ensemble_id: str, index: int) -> str:
    """``<base>__<ensemble token>__rNN``.

    The ensemble's own token keeps replicates of different ensembles built from
    the same base simulation from colliding.
    """
    token = ensemble_id[4:] if ensemble_id.startswith("ens_") else ensemble_id
    return f"{base_simulation_id}__{token}__r{index:02d}"


def _now() -> str:
    return datetime.now().isoformat()


def _read_json(path: str, attempts: int = 6, delay: float = 0.02) -> Any:
    """``json.load`` that retries a few times on ``PermissionError``.

    On Windows a read can fail briefly while another thread or process replaces
    the file (``os.replace`` needs the destination to be closed).
    """
    for attempt in range(attempts):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def _int_in_range(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnsembleError(f"{name} must be an integer")
    if not low <= value <= high:
        raise EnsembleError(f"{name} must be between {low} and {high}")
    return value


def estimate_cost(
    config: Dict[str, Any], n_replicates: int, max_rounds: int, n_questions: int, platforms: int = 2
) -> Dict[str, Any]:
    """A deliberately conservative upper bound on LLM calls.

    ``n * platforms * rounds * agents_per_hour_max_effective`` for the rounds
    (each woken agent makes one call, and ``agents_per_hour_max`` is boosted by
    the peak multiplier) plus ``n * platforms * agents * questions`` for the
    polls. The real figure is usually well below it: polls use one prompt per
    agent on one platform, and many agents do nothing in a given round.
    """
    time_config = config.get("time_config") or {}
    n_agents = len(config.get("agent_configs") or [])
    per_hour_max = time_config.get("agents_per_hour_max", 20)
    peak = max(1.0, float(time_config.get("peak_activity_multiplier", 1.5) or 1.0))
    effective = min(n_agents, math.ceil(per_hour_max * peak))
    minutes = max(1, int(time_config.get("minutes_per_round", 60) or 60))
    config_rounds = int(time_config.get("total_simulation_hours", 72) * 60 // minutes)
    rounds = min(max_rounds, config_rounds) if config_rounds > 0 else max_rounds

    simulation_calls = n_replicates * platforms * rounds * effective
    poll_calls = n_replicates * platforms * n_agents * n_questions
    return {
        "llm_calls_upper_bound": simulation_calls + poll_calls,
        "simulation_calls": simulation_calls,
        "poll_calls": poll_calls,
        "assumptions": {
            "replicates": n_replicates,
            "platforms": platforms,
            "rounds_per_run": rounds,
            "agents": n_agents,
            "agents_woken_per_round_max": effective,
            "questions": n_questions,
        },
    }


class EnsembleManager:
    """Creates, runs, stops and aggregates ensembles (all methods are classmethods)."""

    ENSEMBLE_DATA_DIR = os.path.join(os.path.dirname(__file__), '../../uploads/ensembles')

    _locks: Dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()
    _threads: Dict[str, threading.Thread] = {}
    _stop_requested: set = set()

    # --- paths and persistence ---------------------------------------------------

    @classmethod
    def _dir(cls, ensemble_id: str) -> str:
        return os.path.join(cls.ENSEMBLE_DATA_DIR, ensemble_id)

    @classmethod
    def _path(cls, ensemble_id: str, name: str = "ensemble.json") -> str:
        return os.path.join(cls._dir(ensemble_id), name)

    @classmethod
    def _lock(cls, ensemble_id: str) -> threading.RLock:
        with cls._locks_guard:
            return cls._locks.setdefault(ensemble_id, threading.RLock())

    @classmethod
    def _load(cls, ensemble_id: str) -> Dict[str, Any]:
        # Under the per-ensemble lock so a read never overlaps a save in this process.
        with cls._lock(ensemble_id):
            path = cls._path(ensemble_id)
            if not os.path.isfile(path):
                raise EnsembleNotFound(f"Ensemble not found: {ensemble_id}")
            try:
                return _read_json(path)
            except (ValueError, OSError) as error:
                raise EnsembleCorrupt(
                    f"The definition of {ensemble_id} cannot be read "
                    f"({type(error).__name__}); ensemble.json may be corrupt"
                ) from error

    @classmethod
    def _save(cls, ensemble: Dict[str, Any]) -> None:
        ensemble_id = ensemble["ensemble_id"]
        with cls._lock(ensemble_id):
            if not os.path.isdir(cls._dir(ensemble_id)):
                # Never resurrect an ensemble whose directory was removed while it ran.
                raise EnsembleNotFound(f"Ensemble not found: {ensemble_id}")
            ensemble["updated_at"] = _now()
            write_json_atomic(cls._path(ensemble_id), ensemble)

    @classmethod
    def _sim_dir(cls, simulation_id: str) -> str:
        return os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)

    @classmethod
    def load_outcome_questions(cls, ensemble_id: str) -> List[Dict[str, Any]]:
        with cls._lock(ensemble_id):
            try:
                return _read_json(cls._path(ensemble_id, "outcome_questions.json"))
            except (OSError, ValueError):
                return []

    # --- create ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        base_simulation_id: str,
        *,
        n_replicates: Any = DEFAULT_REPLICATES,
        max_rounds: Any = None,
        base_seed: Any = None,
        platform: str = "parallel",
        concurrency: Any = 1,
        outcome_questions: Any = None,
        llm_temperature: Any = None,
        llm_json: Optional[Callable[[List[Dict[str, str]]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Clone ``base_simulation_id`` into replicates and write the ensemble definition.

        ``max_rounds`` is required: it is the cost guard. Outcome questions are
        taken from the caller or derived from the simulation requirement (one
        LLM call, falling back to a generic stance question); the caller should
        show them to the user, who can still edit them before ``start``.
        """
        n = _int_in_range("n_replicates", n_replicates, 1, MAX_REPLICATES)
        if max_rounds is None:
            raise EnsembleError("max_rounds is required (it bounds the cost of the ensemble)")
        rounds = _int_in_range("max_rounds", max_rounds, 1, MAX_ROUNDS_LIMIT)
        concurrent = _int_in_range("concurrency", concurrency, 1, MAX_CONCURRENCY)
        if platform not in PLATFORMS_SUPPORTED:
            raise EnsembleError(
                "Only the 'parallel' (dual-platform) mode supports ensembles: it is the mode "
                "that records the action logs and runs the final poll"
            )
        if base_seed is None:
            seed_base = secrets.randbelow(2 ** 31)
        else:
            seed_base = _int_in_range("base_seed", base_seed, 0, 2 ** 63 - 1)
        if llm_temperature is not None:
            if (
                isinstance(llm_temperature, bool)
                or not isinstance(llm_temperature, (int, float))
                or not 0 <= llm_temperature <= 2
            ):
                raise EnsembleError("llm_temperature must be a number between 0 and 2")
            llm_temperature = float(llm_temperature)

        base_dir = cls._sim_dir(base_simulation_id)
        if not os.path.isfile(os.path.join(base_dir, "state.json")):
            raise EnsembleNotFound(f"Simulation not found: {base_simulation_id}")
        manager = SimulationManager()
        base_state = manager.get_simulation(base_simulation_id)
        if base_state is None:
            raise EnsembleNotFound(f"Simulation not found: {base_simulation_id}")
        if base_state.is_replicate:
            raise EnsembleError("An ensemble cannot be created from a replicate simulation")
        if not (base_state.config_generated and base_state.profiles_generated):
            raise EnsembleConflict(
                f"Simulation {base_simulation_id} is not prepared yet (profiles and config are required)"
            )
        base_config = manager.get_simulation_config(base_simulation_id)
        if not base_config:
            raise EnsembleConflict(f"Simulation {base_simulation_id} has no config file")

        if outcome_questions is None:
            questions, questions_source = derive_outcome_questions(base_config, llm_json)
        else:
            questions, errors = validate_outcome_questions(outcome_questions)
            if errors:
                raise EnsembleError("Invalid outcome questions: " + "; ".join(errors))
            questions_source = "user"

        ensemble_id = f"ens_{uuid.uuid4().hex[:12]}"
        ensemble_dir = cls._dir(ensemble_id)
        # If this fails nothing of ours exists yet, so there is nothing to clean up.
        os.makedirs(ensemble_dir, exist_ok=False)
        replicates: List[Dict[str, Any]] = []
        created_sim_dirs: List[str] = []
        try:
            for index in range(1, n + 1):
                replicate = {
                    "index": index,
                    "simulation_id": replicate_simulation_id(base_simulation_id, ensemble_id, index),
                    "seed": derive_replicate_seed(seed_base, index),
                    "status": "pending",
                    "error": None,
                    "started_at": None,
                    "completed_at": None,
                }
                replicate_dir = cls._sim_dir(replicate["simulation_id"])
                if os.path.exists(replicate_dir):
                    # Never touch (or later clean up) a directory we did not create.
                    raise EnsembleConflict(f"{replicate['simulation_id']} already exists")
                created_sim_dirs.append(replicate_dir)  # from here on it is ours
                cls._clone_replicate(
                    manager, base_state, base_config, replicate, ensemble_id,
                    rounds, questions, llm_temperature, concurrent,
                )
                replicates.append(replicate)

            ensemble = {
                "ensemble_id": ensemble_id,
                "base_simulation_id": base_simulation_id,
                "project_id": base_state.project_id,
                "graph_id": base_state.graph_id,
                "n_replicates": n,
                "base_seed": seed_base,
                "concurrency": concurrent,
                "platform": platform,
                "max_rounds": rounds,
                "llm_temperature": llm_temperature,
                "questions_source": questions_source,
                "replicates": replicates,
                "status": "created",
                "error": None,
                "created_at": _now(),
                "updated_at": _now(),
                "cost_estimate": estimate_cost(base_config, n, rounds, len(questions)),
            }
            write_json_atomic(cls._path(ensemble_id, "outcome_questions.json"), questions)
            write_json_atomic(cls._path(ensemble_id), ensemble)
        except Exception:
            # leave nothing half-built behind
            shutil.rmtree(ensemble_dir, ignore_errors=True)
            for path in created_sim_dirs:
                shutil.rmtree(path, ignore_errors=True)
            raise

        logger.info(
            f"Ensemble created: {ensemble_id} base={base_simulation_id} n={n} "
            f"rounds={rounds} concurrency={concurrent} questions={len(questions)} ({questions_source})"
        )
        return cls._with_progress(ensemble)

    @classmethod
    def _clone_replicate(
        cls,
        manager: SimulationManager,
        base_state: SimulationState,
        base_config: Dict[str, Any],
        replicate: Dict[str, Any],
        ensemble_id: str,
        max_rounds: int,
        questions: List[Dict[str, Any]],
        llm_temperature: Optional[float],
        concurrency: int,
    ) -> None:
        """A replicate is the base simulation's config and profiles plus its own seed.

        Databases, logs, run state, IPC directories and the environment marker
        are deliberately not copied: they belong to a run, not to a definition.
        """
        simulation_id = replicate["simulation_id"]
        base_dir = cls._sim_dir(base_state.simulation_id)
        target_dir = cls._sim_dir(simulation_id)
        os.makedirs(target_dir, exist_ok=False)

        config = copy.deepcopy(base_config)
        config["simulation_id"] = simulation_id
        run = dict(config.get("run") or {})
        run.update(
            seed=replicate["seed"],
            replicate_index=replicate["index"],
            ensemble_id=ensemble_id,
            max_rounds=max_rounds,
            outcome_questions=copy.deepcopy(questions),
            # replicates share the provider's rate limit
            llm_semaphore=max(1, _base_llm_semaphore() // concurrency),
            # how many replicates run at once; the run script divides each platform's cap by it
            llm_concurrency_share=concurrency,
        )
        if llm_temperature is not None:
            run["llm_temperature"] = llm_temperature
        else:
            run.pop("llm_temperature", None)
        config["run"] = run
        write_json_atomic(os.path.join(target_dir, "simulation_config.json"), config)

        for name in ("twitter_profiles.csv", "reddit_profiles.json"):
            source = os.path.join(base_dir, name)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(target_dir, name))

        manager._save_simulation_state(SimulationState(
            simulation_id=simulation_id,
            project_id=base_state.project_id,
            graph_id=base_state.graph_id,
            enable_twitter=base_state.enable_twitter,
            enable_reddit=base_state.enable_reddit,
            status=SimulationStatus.READY,
            entities_count=base_state.entities_count,
            profiles_count=base_state.profiles_count,
            entity_types=list(base_state.entity_types),
            profiles_generated=True,
            config_generated=True,
            config_reasoning=base_state.config_reasoning,
            ensemble_id=ensemble_id,
            replicate_index=replicate["index"],
        ))

    # --- outcome questions -------------------------------------------------------

    @classmethod
    def update_outcome_questions(cls, ensemble_id: str, questions: Any) -> Dict[str, Any]:
        """Replace the poll questions. Only possible before the ensemble starts."""
        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            if ensemble["status"] != "created":
                raise EnsembleConflict(
                    f"Outcome questions can only be edited before the ensemble starts "
                    f"(status is '{ensemble['status']}')"
                )
            normalized, errors = validate_outcome_questions(questions)
            if errors:
                raise EnsembleError("Invalid outcome questions: " + "; ".join(errors))

            for replicate in ensemble["replicates"]:
                path = os.path.join(cls._sim_dir(replicate["simulation_id"]), "simulation_config.json")
                with open(path, "r", encoding="utf-8") as handle:
                    config = json.load(handle)
                config.setdefault("run", {})["outcome_questions"] = copy.deepcopy(normalized)
                write_json_atomic(path, config)

            base_config = SimulationManager().get_simulation_config(ensemble["base_simulation_id"]) or {}
            ensemble["questions_source"] = "user"
            ensemble["cost_estimate"] = estimate_cost(
                base_config, ensemble["n_replicates"], ensemble["max_rounds"], len(normalized)
            )
            write_json_atomic(cls._path(ensemble_id, "outcome_questions.json"), normalized)
            cls._save(ensemble)
            return cls._with_progress(ensemble)

    # --- start / run ---------------------------------------------------------------

    @classmethod
    def start(cls, ensemble_id: str) -> Dict[str, Any]:
        """Start running the replicates in a background thread."""
        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            if ensemble["status"] != "created":
                raise EnsembleConflict(
                    f"Only a newly created ensemble can be started (status is '{ensemble['status']}')"
                )
            ensemble["status"] = "running"
            ensemble["started_at"] = _now()
            cls._stop_requested.discard(ensemble_id)
            cls._save(ensemble)

            thread = threading.Thread(
                target=cls._run, args=(ensemble_id,), name=f"ensemble-{ensemble_id}", daemon=True
            )
            cls._threads[ensemble_id] = thread
            thread.start()
            return cls._with_progress(ensemble)

    @classmethod
    def _observe(cls, replicate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The terminal outcome of a running replicate, or None while it still runs."""
        state = SimulationRunner.get_run_state(replicate["simulation_id"])
        if state is None:
            return {"status": "failed", "error": NO_RUN_STATE_ERROR}
        if state.runner_status == RunnerStatus.COMPLETED:
            return {"status": "completed", "error": None}
        if state.runner_status == RunnerStatus.FAILED:
            return {"status": "failed", "error": state.error or "the simulation failed"}
        if state.runner_status == RunnerStatus.STOPPED:
            return {"status": "stopped", "error": None}
        return None

    @classmethod
    def _run(cls, ensemble_id: str) -> None:
        """Keep at most ``concurrency`` replicates running until all are finished."""
        try:
            while True:
                with cls._lock(ensemble_id):
                    ensemble = cls._load(ensemble_id)
                    if ensemble["status"] != "running" or ensemble_id in cls._stop_requested:
                        return
                    replicates = ensemble["replicates"]
                    changed = False

                    for replicate in replicates:
                        if replicate["status"] == "running":
                            outcome = cls._observe(replicate)
                            if outcome:
                                replicate.update(outcome, completed_at=_now())
                                changed = True

                    active = sum(1 for r in replicates if r["status"] == "running")
                    for replicate in replicates:
                        if active >= ensemble["concurrency"]:
                            break
                        if replicate["status"] != "pending":
                            continue
                        try:
                            # Replicates never write to Zep and exit once finished.
                            SimulationRunner.start_simulation(
                                replicate["simulation_id"],
                                platform=ensemble["platform"],
                                max_rounds=ensemble["max_rounds"],
                                enable_graph_memory_update=False,
                                seed=replicate["seed"],
                                wait_for_commands=False,
                                resume=bool(replicate.get("resume")),
                            )
                            if replicate.pop("resume", None):
                                replicate["resumed"] = True
                            replicate.update(status="running", started_at=replicate.get("started_at") or _now())
                            active += 1
                        except Exception as error:
                            logger.error(f"Replicate {replicate['simulation_id']} failed to start: {error}")
                            replicate.update(status="failed", error=str(error), completed_at=_now())
                        changed = True

                    finished = all(r["status"] in REPLICATE_TERMINAL for r in replicates)
                    if changed:
                        cls._save(ensemble)
                if finished:
                    break
                time.sleep(POLL_INTERVAL_SECONDS)

            cls._finalize(ensemble_id)
        except Exception as error:  # the runner thread must never die silently
            logger.error(f"Ensemble {ensemble_id} runner crashed: {error}")
            try:
                with cls._lock(ensemble_id):
                    ensemble = cls._load(ensemble_id)
                    if ensemble["status"] in ("running", "aggregating"):
                        ensemble.update(status="failed", error=f"runner crashed: {error}")
                        cls._save(ensemble)
            except Exception:
                pass

    @classmethod
    def _final_status(cls, ensemble: Dict[str, Any]) -> str:
        """completed (all ok) / partial (>= 2 ok) / failed (fewer than 2 ok; a single-run ensemble needs its one run)."""
        replicates = ensemble["replicates"]
        ok = sum(1 for r in replicates if r["status"] == "completed")
        # An ensemble of one run needs that one run; larger ones need two.
        if ok < min(MIN_REPLICATES_TO_AGGREGATE, len(replicates)):
            return "failed"
        return "completed" if ok == len(replicates) else "partial"

    @classmethod
    def _finalize(cls, ensemble_id: str) -> None:
        """Aggregate what finished and publish the ensemble's final status."""
        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            if ensemble["status"] not in ("running", "aggregating") or ensemble_id in cls._stop_requested:
                return
            final = cls._final_status(ensemble)
            if final == "failed":
                needed = min(MIN_REPLICATES_TO_AGGREGATE, len(ensemble["replicates"]))
                reason = (
                    f"fewer than {needed} replicates completed"
                    if needed > 1 else "the run did not complete"
                )
                ensemble.update(status="failed", error=f"{reason}; nothing to aggregate")
                cls._save(ensemble)
                return
            ensemble["status"] = "aggregating"
            cls._save(ensemble)

            try:
                questions = cls.load_outcome_questions(ensemble_id)
                summary = build_summary(ensemble, questions, SimulationManager.SIMULATION_DATA_DIR)
                write_summary(cls._dir(ensemble_id), summary)
                ensemble.update(status=final, error=None, completed_at=_now())
            except Exception as error:
                logger.error(f"Ensemble {ensemble_id} aggregation failed: {error}")
                ensemble.update(status="failed", error=f"aggregation failed: {error}")
            cls._save(ensemble)

    # --- resume -------------------------------------------------------------------

    @classmethod
    def _resume_plan(cls, ensemble: Dict[str, Any]) -> List[Dict[str, Any]]:
        """What resuming would do to each replicate that was cut off.

        ``[{"simulation_id", "action": "resume" | "restart" | "skip", "round", "reason"}]``. A replicate that
        was stopped, or failed as ``interrupted``, continues after its last finished round when it can;
        one that never produced anything starts over; anything else is left alone.
        """
        plan = []
        for replicate in ensemble["replicates"]:
            cut_off = replicate["status"] == "stopped" or (
                replicate["status"] == "failed" and replicate.get("error") in (INTERRUPTED_ERROR, NO_RUN_STATE_ERROR)
            )
            if not cut_off:
                continue
            simulation_id = replicate["simulation_id"]
            info = SimulationRunner.resume_info(simulation_id)
            if info["resumable"]:
                plan.append({"simulation_id": simulation_id, "action": "resume", "round": info["round"],
                             "exact": info["exact"], "memory": info.get("memory"), "reason": None})
            elif any(text in (info["reason"] or "") for text in _NOTHING_TO_KEEP):
                plan.append({"simulation_id": simulation_id, "action": "restart", "round": 0,
                             "exact": None, "reason": info["reason"]})
            else:
                plan.append({"simulation_id": simulation_id, "action": "skip", "round": None,
                             "exact": None, "reason": info["reason"]})
        return plan

    @classmethod
    def resume_info(cls, ensemble_id: str) -> Dict[str, Any]:
        """Whether the ensemble can be resumed and what would happen to each of its runs."""
        ensemble = cls.reconcile(ensemble_id)
        if ensemble["status"] not in RESUMABLE_STATUSES:
            return {"resumable": False, "reason": f"an ensemble that is '{ensemble['status']}' cannot be resumed",
                    "replicates": []}
        plan = cls._resume_plan(ensemble)
        usable = [item for item in plan if item["action"] != "skip"]
        return {
            "resumable": bool(usable),
            "reason": None if usable else "none of its runs can continue",
            "replicates": plan,
        }

    @classmethod
    def resume(cls, ensemble_id: str) -> Dict[str, Any]:
        """Continue a stopped or interrupted ensemble: unfinished runs resume, finished ones are kept."""
        with cls._lock(ensemble_id):
            ensemble = cls.reconcile(ensemble_id)
            if ensemble["status"] not in RESUMABLE_STATUSES:
                raise EnsembleConflict(f"An ensemble that is '{ensemble['status']}' cannot be resumed")
            plan = cls._resume_plan(ensemble)
            chosen = {item["simulation_id"]: item for item in plan if item["action"] != "skip"}
            if not chosen:
                raise EnsembleConflict("None of this ensemble's runs can be resumed; create a new ensemble")

            for replicate in ensemble["replicates"]:
                item = chosen.get(replicate["simulation_id"])
                if item is None:
                    continue
                if item["action"] == "restart":
                    result = SimulationRunner.cleanup_simulation_logs(replicate["simulation_id"])
                    if not result.get("success"):
                        raise EnsembleConflict(f"Cannot reset {replicate['simulation_id']}: {result.get('errors')}")
                    replicate.pop("started_at", None)
                replicate.update(status="pending", error=None, completed_at=None)
                replicate["resume"] = item["action"] == "resume"
            ensemble.update(
                status="running", error=None, completed_at=None, resumed_at=_now(),
                resume_count=int(ensemble.get("resume_count") or 0) + 1,
            )
            cls._stop_requested.discard(ensemble_id)
            cls._save(ensemble)

            thread = threading.Thread(
                target=cls._run, args=(ensemble_id,), name=f"ensemble-{ensemble_id}", daemon=True
            )
            cls._threads[ensemble_id] = thread
            thread.start()
            return cls._with_progress(ensemble)

    # --- stop ---------------------------------------------------------------------

    @classmethod
    def stop(cls, ensemble_id: str) -> Dict[str, Any]:
        """Stop running replicates and mark the rest stopped. Idempotent once finished."""
        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            status = ensemble["status"]
            if status in TERMINAL_STATUSES:
                return cls._with_progress(ensemble)
            if status == "aggregating":
                raise EnsembleConflict("The ensemble is aggregating its results; wait for it to finish")

            cls._stop_requested.add(ensemble_id)
            running = []
            for replicate in ensemble["replicates"]:
                if replicate["status"] == "pending":
                    replicate.update(status="stopped", completed_at=_now())
                elif replicate["status"] == "running":
                    running.append(replicate["simulation_id"])
            cls._save(ensemble)

        errors: Dict[str, str] = {}
        for simulation_id in running:
            try:
                SimulationRunner.stop_simulation(simulation_id)
            except Exception as error:
                logger.warning(f"Stopping replicate {simulation_id}: {error}")
                errors[simulation_id] = str(error)

        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            for replicate in ensemble["replicates"]:
                if replicate["simulation_id"] in running:
                    state = SimulationRunner.get_run_state(replicate["simulation_id"])
                    if state and state.runner_status == RunnerStatus.COMPLETED:
                        replicate.update(status="completed", completed_at=_now())
                    else:
                        replicate.update(
                            status="stopped", completed_at=_now(),
                            error=errors.get(replicate["simulation_id"]),
                        )
            ensemble["status"] = "stopped"
            cls._save(ensemble)
            cls._stop_requested.discard(ensemble_id)
            return cls._with_progress(ensemble)

    # --- restart recovery -----------------------------------------------------------

    @classmethod
    def _thread_alive(cls, ensemble_id: str) -> bool:
        thread = cls._threads.get(ensemble_id)
        return thread is not None and thread.is_alive()

    @classmethod
    def reconcile(cls, ensemble_id: str) -> Dict[str, Any]:
        """Repair an ensemble left ``running`` by a process that is gone.

        Replicates whose process no longer exists and did not complete become
        ``failed`` with ``"interrupted"``; replicates that never started become
        ``stopped``. Nothing is resumed automatically. Whatever finished is then
        aggregated under the normal failure policy.
        """
        with cls._lock(ensemble_id):
            ensemble = cls._load(ensemble_id)
            if ensemble["status"] not in ("running", "aggregating") or cls._thread_alive(ensemble_id):
                return ensemble

            for replicate in ensemble["replicates"]:
                if replicate["status"] == "running":
                    outcome = cls._observe(replicate)
                    if outcome is None:
                        if SimulationRunner.has_live_process(replicate["simulation_id"]):
                            continue
                        outcome = {"status": "failed", "error": "interrupted"}
                    replicate.update(outcome, completed_at=_now())
                elif replicate["status"] == "pending":
                    replicate.update(status="stopped", error="interrupted", completed_at=_now())

            if any(r["status"] == "running" for r in ensemble["replicates"]):
                cls._save(ensemble)
                return ensemble
            ensemble["status"] = "running"  # so _finalize accepts it
            cls._save(ensemble)

        cls._finalize(ensemble_id)
        with cls._lock(ensemble_id):
            return cls._load(ensemble_id)

    # --- queries ----------------------------------------------------------------------

    @classmethod
    def _with_progress(cls, ensemble: Dict[str, Any]) -> Dict[str, Any]:
        """The ensemble plus live per-replicate progress read from the run states."""
        result = copy.deepcopy(ensemble)
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "stopped": 0}
        for replicate in result["replicates"]:
            counts[replicate["status"]] = counts.get(replicate["status"], 0) + 1
            state = SimulationRunner.get_run_state(replicate["simulation_id"])
            if state is not None:
                replicate["current_round"] = state.current_round
                replicate["total_rounds"] = state.total_rounds
                replicate["runner_status"] = state.runner_status.value
                # Live status for the UI. Read defensively: this view must never fail an ensemble listing.
                health = getattr(state, "health", None)
                replicate["activity"] = getattr(state, "activity", None) or {}
                replicate["poll"] = getattr(state, "poll", None)
                replicate["health"] = health() if callable(health) else None
            else:
                replicate["current_round"] = 0
                replicate["total_rounds"] = ensemble.get("max_rounds")
                replicate["runner_status"] = None
                replicate["activity"] = {}
                replicate["poll"] = None
                replicate["health"] = None
        result["progress"] = counts
        result["has_summary"] = os.path.isfile(cls._path(ensemble["ensemble_id"], "summary.json"))
        result["outcome_questions"] = cls.load_outcome_questions(ensemble["ensemble_id"])
        return result

    @classmethod
    def get(cls, ensemble_id: str) -> Dict[str, Any]:
        cls._load(ensemble_id)  # 404 early
        ensemble = cls.reconcile(ensemble_id)
        return cls._with_progress(ensemble)

    @classmethod
    def list_ensembles(cls, base_simulation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        results = []
        if not os.path.isdir(cls.ENSEMBLE_DATA_DIR):
            return results
        for name in sorted(os.listdir(cls.ENSEMBLE_DATA_DIR)):
            if not os.path.isfile(cls._path(name)):
                continue
            try:
                ensemble = cls.reconcile(name)
            except EnsembleError as error:
                logger.warning(f"Skipping ensemble {name} in the listing: {error}")
                continue
            if base_simulation_id and ensemble.get("base_simulation_id") != base_simulation_id:
                continue
            results.append(cls._with_progress(ensemble))
        results.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return results

    @classmethod
    def summary_markdown(cls, ensemble_id: str) -> Optional[str]:
        """The human-readable ``summary.md`` (opens with the caveat), or None until it exists."""
        cls._load(ensemble_id)  # 404 for unknown ensembles
        with cls._lock(ensemble_id):
            try:
                with open(cls._path(ensemble_id, "summary.md"), "r", encoding="utf-8") as handle:
                    return handle.read()
            except OSError:
                return None

    @classmethod
    def summary(cls, ensemble_id: str) -> Optional[Dict[str, Any]]:
        """The aggregated ``summary.json``, or None until it exists."""
        cls._load(ensemble_id)  # 404 for unknown ensembles
        with cls._lock(ensemble_id):
            try:
                return _read_json(cls._path(ensemble_id, "summary.json"))
            except (OSError, ValueError):
                return None
