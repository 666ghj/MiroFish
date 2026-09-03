"""
OASIS simulation runner
Runs a simulation in a background process, records every agent action and exposes live status.
"""

import os
import sys
import json
import time
import asyncio
import threading
import subprocess
import signal
import atexit
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep import (
    ZEP_HTTP_REQUEST_TIMEOUT_SECONDS,
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
)
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('sosim.simulation_runner')

# Tracks whether the shutdown cleanup has been registered
_cleanup_registered = False

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

# The backend's own rotating log, written by utils.logger beside the app. It is
# the only trace a simulation leaves before it has a simulation.log of its own.
BACKEND_LOG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
)

# Explains a run that a backend restart cut short. The child is spawned with
# start_new_session=True, so it can outlive the backend; when it did not, the
# run is finished here rather than left claiming to be running forever.
RUN_INTERRUPTED_ERROR = (
    "The backend restarted while this simulation was running and the run did "
    "not survive. Restart it to run again."
)


class RunnerStatus(str, Enum):
    """Runner status"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class SimulationStopPending(TimeoutError):
    """The monitor still owns a bounded graph-ingestion finalization."""


class _AdoptedProcess:
    """
    Stands in for subprocess.Popen around a process this backend did not spawn.

    A simulation child is started with start_new_session=True, so it survives a
    backend restart - but it is no longer a child of this process and cannot be
    waited on. Liveness is polled by signal instead, which is all the monitor
    and the terminator need.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode

        if not IS_WINDOWS:
            # An adopted PID is normally reparented to init, but the same shim
            # is used to reap a child this backend spawned and then forgot.
            # Such a child stays a signalable zombie until it is waited on.
            try:
                reaped, status = os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                reaped = 0
            if reaped == self.pid:
                self.returncode = os.waitstatus_to_exitcode(status)
                return self.returncode

        if not SimulationRunner._pid_alive(self.pid):
            # The exit status of a process that is not our child is not
            # observable. Report a clean exit and let the action logs decide
            # whether the run actually finished.
            self.returncode = 0
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout)
            time.sleep(0.2)
        return self.returncode

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(getattr(signal, 'SIGKILL', signal.SIGTERM))

    def _signal(self, sig) -> None:
        try:
            os.kill(self.pid, sig)
        except OSError:
            pass


@dataclass
class AgentAction:
    """One recorded agent action"""
    round_num: int
    timestamp: str
    platform: str  # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str  # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "action_args": self.action_args,
            "result": self.result,
            "success": self.success,
        }


@dataclass
class RoundSummary:
    """Summary of one round"""
    round_num: int
    start_time: str
    end_time: Optional[str] = None
    simulated_hour: int = 0
    twitter_actions: int = 0
    reddit_actions: int = 0
    active_agents: List[int] = field(default_factory=list)
    actions: List[AgentAction] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "simulated_hour": self.simulated_hour,
            "twitter_actions": self.twitter_actions,
            "reddit_actions": self.reddit_actions,
            "active_agents": self.active_agents,
            "actions_count": len(self.actions),
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class SimulationRunState:
    """Live run state of a simulation"""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE
    
    # Progress
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0
    
    # Per-platform rounds and simulated time, for the dual-platform display
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0
    
    # Platform status
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    
    # Platform completion, detected from simulation_end events in actions.jsonl
    twitter_completed: bool = False
    reddit_completed: bool = False
    
    # Per-round summaries
    rounds: List[RoundSummary] = field(default_factory=list)
    
    # Recent actions, rendered live by the frontend
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50
    
    # Timestamps
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    # Failure detail
    error: Optional[str] = None
    
    # Process ID, used to stop the run
    process_pid: Optional[int] = None
    
    def add_action(self, action: AgentAction):
        """Record an action in the recent-actions list."""
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > self.max_recent_actions:
            self.recent_actions = self.recent_actions[:self.max_recent_actions]
        
        if action.platform == "twitter":
            self.twitter_actions_count += 1
        else:
            self.reddit_actions_count += 1
        
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "runner_status": self.runner_status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "simulated_hours": self.simulated_hours,
            "total_simulation_hours": self.total_simulation_hours,
            "progress_percent": round(self.current_round / max(self.total_rounds, 1) * 100, 1),
            # Per-platform rounds and simulated time
            "twitter_current_round": self.twitter_current_round,
            "reddit_current_round": self.reddit_current_round,
            "twitter_simulated_hours": self.twitter_simulated_hours,
            "reddit_simulated_hours": self.reddit_simulated_hours,
            "twitter_running": self.twitter_running,
            "reddit_running": self.reddit_running,
            "twitter_completed": self.twitter_completed,
            "reddit_completed": self.reddit_completed,
            "twitter_actions_count": self.twitter_actions_count,
            "reddit_actions_count": self.reddit_actions_count,
            "total_actions_count": self.twitter_actions_count + self.reddit_actions_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "process_pid": self.process_pid,
        }
    
    def to_detail_dict(self) -> Dict[str, Any]:
        """Return the full state, including recent actions."""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    Simulation runner
    
    Responsibilities:
    1. Run an OASIS simulation in a background process.
    2. Parse the run logs and record every agent action.
    3. Serve live status queries.
    4. Stop, reap and reconcile runs, including ones stranded by a backend restart.
    """
    
    # Run-state directory
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )
    
    # Runner script directory
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )
    
    # In-memory run state
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # Open stdout file handles
    _stderr_files: Dict[str, Any] = {}  # Open stderr file handles
    
    # Graph memory update settings
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    _finalization_locks: Dict[str, threading.Lock] = {}
    _finalization_locks_guard = threading.Lock()
    _manual_stop_requests: set[str] = set()

    # Statuses in which a run still owns a process or an ingestion drain.
    ACTIVE_STATUSES = frozenset({
        RunnerStatus.STARTING,
        RunnerStatus.RUNNING,
        RunnerStatus.PAUSED,
        RunnerStatus.STOPPING,
    })

    # Log viewer limits. A log is read through a bounded window so a multi-
    # gigabyte actions.jsonl can never be pulled into memory by one request.
    LOG_SOURCES = ("main", "twitter", "reddit", "backend")
    MAX_LOG_TAIL_BYTES = 256 * 1024
    MAX_LOG_TAIL_LINES = 2000

    @classmethod
    def _simulation_dir(cls, simulation_id: str) -> str:
        """Return a simulation's directory, without creating it."""
        from .simulation_manager import validate_simulation_id

        validate_simulation_id(simulation_id)
        return os.path.join(cls.RUN_STATE_DIR, simulation_id)

    @classmethod
    def _finalization_lock(cls, simulation_id: str) -> threading.Lock:
        with cls._finalization_locks_guard:
            return cls._finalization_locks.setdefault(
                simulation_id, threading.Lock()
            )

    @classmethod
    def _sync_simulation_status(
        cls,
        simulation_id: str,
        runner_status: RunnerStatus,
        error: str | None = None,
    ) -> None:
        """Keep persisted simulation metadata aligned with run_state.json."""

        from .simulation_manager import SimulationManager, SimulationStatus

        status_map = {
            RunnerStatus.RUNNING: SimulationStatus.RUNNING,
            RunnerStatus.STOPPING: SimulationStatus.STOPPING,
            RunnerStatus.STOPPED: SimulationStatus.STOPPED,
            RunnerStatus.COMPLETED: SimulationStatus.COMPLETED,
            RunnerStatus.FAILED: SimulationStatus.FAILED,
        }
        status = status_map.get(runner_status)
        if status is None:
            return
        try:
            manager = SimulationManager()
            simulation = manager.get_simulation(simulation_id)
            if simulation is None:
                return
            simulation.status = status
            simulation.error = error
            manager._save_simulation_state(simulation)
        except Exception as sync_error:
            # state.json is a secondary projection. Never let a projection
            # failure skip the authoritative run-state finalization or Zep
            # ingestion drain.
            logger.error(
                "Failed to sync simulation status: simulation_id=%s, status=%s, error=%s",
                simulation_id,
                runner_status.value,
                sync_error,
            )
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Return the live run state."""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]
        
        # Fall back to the persisted state
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Load the run state from disk."""
        state_file = os.path.join(cls._simulation_dir(simulation_id), "run_state.json")
        if not os.path.exists(state_file):
            return None
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = SimulationRunState(
                simulation_id=simulation_id,
                runner_status=RunnerStatus(data.get("runner_status", "idle")),
                current_round=data.get("current_round", 0),
                total_rounds=data.get("total_rounds", 0),
                simulated_hours=data.get("simulated_hours", 0),
                total_simulation_hours=data.get("total_simulation_hours", 0),
                # Per-platform rounds and simulated time
                twitter_current_round=data.get("twitter_current_round", 0),
                reddit_current_round=data.get("reddit_current_round", 0),
                twitter_simulated_hours=data.get("twitter_simulated_hours", 0),
                reddit_simulated_hours=data.get("reddit_simulated_hours", 0),
                twitter_running=data.get("twitter_running", False),
                reddit_running=data.get("reddit_running", False),
                twitter_completed=data.get("twitter_completed", False),
                reddit_completed=data.get("reddit_completed", False),
                twitter_actions_count=data.get("twitter_actions_count", 0),
                reddit_actions_count=data.get("reddit_actions_count", 0),
                started_at=data.get("started_at"),
                updated_at=data.get("updated_at", datetime.now().isoformat()),
                completed_at=data.get("completed_at"),
                error=data.get("error"),
                process_pid=data.get("process_pid"),
            )
            
            # Recent actions
            actions_data = data.get("recent_actions", [])
            for a in actions_data:
                state.recent_actions.append(AgentAction(
                    round_num=a.get("round_num", 0),
                    timestamp=a.get("timestamp", ""),
                    platform=a.get("platform", ""),
                    agent_id=a.get("agent_id", 0),
                    agent_name=a.get("agent_name", ""),
                    action_type=a.get("action_type", ""),
                    action_args=a.get("action_args", {}),
                    result=a.get("result"),
                    success=a.get("success", True),
                ))
            
            return state
        except Exception as e:
            logger.error(f"Failed to load the run state: {e}")
            return None
    
    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """Write the run state to disk."""
        sim_dir = cls._simulation_dir(state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state

    @classmethod
    def describe_start_blocker(cls, simulation_id: str) -> Optional[str]:
        """
        Return why start_simulation would refuse right now, or None.

        This is the exact predicate start_simulation enforces under the
        finalization lock, lifted out so a caller can ask "can we actually
        start?" BEFORE it deletes anything. cleanup_simulation_logs is
        irreversible - it removes run_state.json, simulation.log, both
        actions.jsonl files and both platform databases - so a caller that
        cleans first and discovers the refusal afterwards has destroyed the
        previous run and delivered no new one.

        The answer is advisory: start_simulation re-checks it while holding the
        lock, so a run that goes live in between still fails closed there.

        Args:
            simulation_id: Simulation ID

        Returns:
            A human-readable reason, or None when a start would proceed
        """
        existing = cls.get_run_state(simulation_id)
        if (
            existing and existing.runner_status in cls.ACTIVE_STATUSES
        ) or ZepGraphMemoryManager.get_updater(simulation_id) is not None:
            return f"Simulation is already running or finalizing: {simulation_id}."
        return None

    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # Cap on rounds, to truncate an over-long simulation
        enable_graph_memory_update: bool = False,  # Push activity into the Zep graph
        graph_id: str = None  # Zep graph ID, required when graph updates are on
    ) -> SimulationRunState:
        """
        Start a simulation.
        
        Args:
            simulation_id: Simulation ID
            platform: Platform to run (twitter/reddit/parallel)
            max_rounds: Cap on rounds, to truncate an over-long simulation
            enable_graph_memory_update: Push agent activity into the Zep graph
            graph_id: Zep graph ID, required when graph updates are on
            
        Returns:
            SimulationRunState
        """
        # Load the simulation configuration
        sim_dir = cls._simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            raise ValueError("Simulation config not found. Call /prepare first.")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Initialize the run state
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # Truncate when a round cap was given
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"Truncated rounds: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=datetime.now().isoformat(),
        )
        
        # Atomically claim this simulation ID. The expensive updater/process
        # startup happens after releasing the lock, while the persisted
        # STARTING state makes every concurrent start fail closed.
        with cls._finalization_lock(simulation_id):
            blocker = cls.describe_start_blocker(simulation_id)
            if blocker is not None:
                raise ValueError(blocker)
            cls._save_run_state(state)
        
        # Create the updater when graph memory is enabled
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("Graph memory updates require a graph_id.")
            
            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"Enabled graph memory updates: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"Failed to create the graph memory updater: {e}")
                cls._graph_memory_enabled[simulation_id] = False
                state.runner_status = RunnerStatus.FAILED
                state.error = f"Failed to initialize the Zep graph updater: {e}"
                with cls._finalization_lock(simulation_id):
                    cls._save_run_state(state)
                    cls._sync_simulation_status(
                        simulation_id,
                        RunnerStatus.FAILED,
                        state.error,
                    )
                raise RuntimeError(state.error) from e
        else:
            cls._graph_memory_enabled[simulation_id] = False
        
        # Pick the script to run; they all live in backend/scripts/
        if platform == "twitter":
            script_name = "run_twitter_simulation.py"
            state.twitter_running = True
        elif platform == "reddit":
            script_name = "run_reddit_simulation.py"
            state.reddit_running = True
        else:
            script_name = "run_parallel_simulation.py"
            state.twitter_running = True
            state.reddit_running = True
        
        script_path = os.path.join(cls.SCRIPTS_DIR, script_name)
        
        if not os.path.exists(script_path):
            cleanup_error = None
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    cls._graph_memory_enabled.pop(simulation_id, None)
                except Exception as error:
                    cleanup_error = error
            state.runner_status = RunnerStatus.FAILED
            state.twitter_running = False
            state.reddit_running = False
            state.error = f"Script not found: {script_path}"
            if cleanup_error is not None:
                state.error += f"; failed to clean up the Zep graph writer: {cleanup_error}"
            with cls._finalization_lock(simulation_id):
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.FAILED,
                    state.error,
                )
            raise ValueError(state.error)
        
        # Create the action queue
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue

        process = None
        main_log_file = None

        # Start the simulation process
        try:
            # Build the command with absolute paths.
            # Log layout:
            #   twitter/actions.jsonl - Twitter action log
            #   reddit/actions.jsonl  - Reddit action log
            #   simulation.log        - main process log
            
            cmd = [
                sys.executable,  # Python interpreter
                script_path,
                "--config", config_path,  # Absolute config path
            ]
            
            # Pass the round cap through to the script
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])
            
            # Redirect into a file so a full stdout/stderr pipe cannot block the child
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')
            
            # Force UTF-8 in the child so third-party libraries such as OASIS cannot
            # fall back to the console code page when they open a file on Windows.
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+, makes every open() default to UTF-8
            env['PYTHONIOENCODING'] = 'utf-8'  # UTF-8 on stdout and stderr
            
            # Run inside the simulation directory, where the databases are written.
            # start_new_session=True gives the child its own process group, so os.killpg ends the whole tree.
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # stderr goes to the same file
                text=True,
                encoding='utf-8',  # Explicit encoding
                bufsize=1,
                env=env,  # Environment carrying the UTF-8 settings
                start_new_session=True,  # Own process group, so shutdown ends the whole tree
            )
            
            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id,),
                daemon=True
            )

            # Atomically publish every resource needed by stop/finalization.
            # The monitor is registered before start; if it exits immediately,
            # it waits on the same lock until RUNNING is fully visible.
            with cls._finalization_lock(simulation_id):
                cls._stdout_files[simulation_id] = main_log_file
                cls._stderr_files[simulation_id] = None
                state.process_pid = process.pid
                state.runner_status = RunnerStatus.RUNNING
                cls._processes[simulation_id] = process
                cls._monitor_threads[simulation_id] = monitor_thread
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.RUNNING,
                )
                monitor_thread.start()
            
            logger.info(f"Started simulation {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            cleanup_errors = []
            if process is not None and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except Exception as error:
                    cleanup_errors.append(f"failed to terminate the child process: {error}")
            cls._processes.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._stdout_files.pop(simulation_id, None)
            cls._stderr_files.pop(simulation_id, None)
            if main_log_file is not None:
                try:
                    main_log_file.close()
                except Exception as error:
                    cleanup_errors.append(f"failed to close the log file: {error}")
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    cls._graph_memory_enabled.pop(simulation_id, None)
                except Exception as error:
                    cleanup_errors.append(f"failed to clean up the Zep graph writer: {error}")
            state.runner_status = RunnerStatus.FAILED
            state.twitter_running = False
            state.reddit_running = False
            state.error = str(e)
            if cleanup_errors:
                state.error += "; " + "; ".join(cleanup_errors)
            with cls._finalization_lock(simulation_id):
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.FAILED,
                    state.error,
                )
            raise
        
        return state
    
    @classmethod
    def _monitor_simulation(
        cls,
        simulation_id: str,
        twitter_position: int = 0,
        reddit_position: int = 0,
    ):
        """
        Monitor the simulation process and parse its action logs.

        The two positions are byte offsets to resume from. A fresh run starts
        at zero; a run adopted after a backend restart starts at the current
        end of each log, because everything before it is already counted in
        the persisted run state.
        """
        sim_dir = cls._simulation_dir(simulation_id)
        
        # Per-platform action logs
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        monitor_error: Exception | None = None
        exit_code: int | None = None
        try:
            while process.poll() is None:  # The process is still running
                # Read the Twitter action log
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )
                
                # Read the Reddit action log
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )
                
                # Publish the state
                cls._save_run_state(state)
                time.sleep(2)
            
            # Read one final time after the process exits
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")
            
            exit_code = process.returncode
            
        except Exception as e:
            logger.error(f"Monitor thread failed: {simulation_id}, error={e}")
            monitor_error = e
        
        finally:
            # Manual stop and natural completion can observe the same process
            # exit. Serialize terminal state and updater drain so only one path
            # owns the final result.
            with cls._finalization_lock(simulation_id):
                latest_state = cls.get_run_state(simulation_id)
                if latest_state is not None:
                    state = latest_state

                if state.runner_status not in {
                    RunnerStatus.STOPPED,
                    RunnerStatus.FAILED,
                }:
                    manual_stop = simulation_id in cls._manual_stop_requests
                    desired_status = (
                        RunnerStatus.STOPPED
                        if manual_stop
                        else RunnerStatus.COMPLETED
                    )
                    error_message = None
                    if not manual_stop and monitor_error is not None:
                        desired_status = RunnerStatus.FAILED
                        error_message = str(monitor_error)
                    elif not manual_stop and exit_code != 0:
                        desired_status = RunnerStatus.FAILED
                        main_log_path = os.path.join(sim_dir, "simulation.log")
                        error_info = ""
                        try:
                            if os.path.exists(main_log_path):
                                with open(main_log_path, 'r', encoding='utf-8') as f:
                                    error_info = f.read()[-2000:]
                        except Exception:
                            pass
                        error_message = (
                            f"Process exit code {exit_code}, log tail: {error_info}"
                        )

                    state.twitter_running = False
                    state.reddit_running = False

                    if cls._graph_memory_enabled.get(simulation_id, False):
                        # STOPPING is a non-terminal ingestion barrier. The UI
                        # and report API must not observe COMPLETED until every
                        # accepted episode is processed by Zep Cloud.
                        state.runner_status = RunnerStatus.STOPPING
                        cls._save_run_state(state)
                        cls._sync_simulation_status(
                            simulation_id,
                            RunnerStatus.STOPPING,
                        )
                        try:
                            ZepGraphMemoryManager.stop_updater(simulation_id)
                            cls._graph_memory_enabled.pop(simulation_id, None)
                            logger.info(
                                "Stopped graph memory updates: simulation_id=%s",
                                simulation_id,
                            )
                        except Exception as error:
                            logger.error(f"Failed to stop the graph memory updater: {error}")
                            desired_status = RunnerStatus.FAILED
                            error_message = f"Zep graph writes did not complete: {error}"

                    state.runner_status = desired_status
                    state.error = error_message
                    state.completed_at = datetime.now().isoformat()
                    cls._save_run_state(state)
                    cls._sync_simulation_status(
                        simulation_id,
                        desired_status,
                        error_message,
                    )
                    if desired_status == RunnerStatus.COMPLETED:
                        logger.info(f"Completed simulation {simulation_id}")
                    elif desired_status == RunnerStatus.STOPPED:
                        logger.info(f"Stopped simulation {simulation_id}")
                    else:
                        logger.error(f"Simulation failed: {simulation_id}, error={state.error}")
                cls._manual_stop_requests.discard(simulation_id)
            
            # Release the process resources
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            
            # Close the log file handles
            if simulation_id in cls._stdout_files:
                try:
                    cls._stdout_files[simulation_id].close()
                except Exception:
                    pass
                cls._stdout_files.pop(simulation_id, None)
            if simulation_id in cls._stderr_files and cls._stderr_files[simulation_id]:
                try:
                    cls._stderr_files[simulation_id].close()
                except Exception:
                    pass
                cls._stderr_files.pop(simulation_id, None)
    
    @classmethod
    def _read_action_log(
        cls, 
        log_path: str, 
        position: int, 
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        Read new lines from an action log.
        
        Args:
            log_path: Action log path
            position: Byte offset read up to last time
            state: Run state to update
            platform: Platform name (twitter/reddit)
            
        Returns:
            The new byte offset
        """
        # Graph memory updates are optional
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = ZepGraphMemoryManager.get_updater(state.simulation_id)
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            action_data = json.loads(line)
                            
                            # Event entries, rather than agent actions
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")
                                
                                # simulation_end marks a platform finished
                                if event_type == "simulation_end":
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter simulation finished: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit simulation finished: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    
                                    # A platform counts as enabled when its action log exists, so a
                                    # single-platform run waits only for that platform and a
                                    # dual-platform run waits for both.
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        # Platform completion is only an input
                                        # signal. The monitor publishes the
                                        # terminal status after the process has
                                        # exited and Zep ingestion has drained.
                                        logger.info(
                                            f"Every platform has finished; waiting for the process and the graph writes: "
                                            f"{state.simulation_id}"
                                        )
                                
                                # Round progress comes from round_end events
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)
                                    
                                    # Per-platform rounds and simulated time
                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours
                                    
                                    # The overall round is the furthest of the two platforms
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    # The overall time is the furthest of the two platforms
                                    state.simulated_hours = max(state.twitter_simulated_hours, state.reddit_simulated_hours)
                                
                                continue
                            
                            action = AgentAction(
                                round_num=action_data.get("round", 0),
                                timestamp=action_data.get("timestamp", datetime.now().isoformat()),
                                platform=platform,
                                agent_id=action_data.get("agent_id", 0),
                                agent_name=action_data.get("agent_name", ""),
                                action_type=action_data.get("action_type", ""),
                                action_args=action_data.get("action_args", {}),
                                result=action_data.get("result"),
                                success=action_data.get("success", True),
                            )
                            state.add_action(action)
                            
                            # Advance the round counter
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num
                            
                            # Push the activity to Zep when graph memory is on
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except Exception as e:
            logger.warning(f"Failed to read the action log {log_path}: {e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        Report whether every enabled platform has finished.
        
        A platform counts as enabled when its actions.jsonl exists.
        
        Returns:
            True when every enabled platform has finished
        """
        sim_dir = cls._simulation_dir(state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        # A platform is enabled when its action log exists
        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)
        
        # An enabled platform that has not finished blocks completion
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False
        
        # At least one platform must be enabled and finished
        return twitter_enabled or reddit_enabled
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        Terminate a process and its children, on any platform.
        
        Args:
            process: Process to terminate
            simulation_id: Simulation ID, for the log line
            timeout: Seconds to wait for the process to exit
        """
        if IS_WINDOWS:
            # Windows: taskkill ends the whole process tree.
            # /F = force, /T = include child processes
            logger.info(f"Terminating the process tree (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # Ask politely first
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force it
                    logger.warning(f"Process did not respond; forcing termination: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill failed, falling back to terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: terminate the process group.
            # start_new_session=True makes the group ID equal the child PID.
            pgid = os.getpgid(process.pid)
            logger.info(f"Terminating the process group (Unix): simulation={simulation_id}, pgid={pgid}")
            
            # SIGTERM the whole group first
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Still alive after the timeout, so SIGKILL it
                logger.warning(f"Process group did not respond to SIGTERM; forcing termination: {simulation_id}")
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError) as error:
                    # The group emptied between the two signals.
                    logger.warning(f"Could not signal process group {pgid}: {error}")
                else:
                    process.wait(timeout=5)
    
    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """Stop a running simulation."""
        with cls._finalization_lock(simulation_id):
            state = cls.get_run_state(simulation_id)
            if not state:
                raise ValueError(f"Simulation not found: {simulation_id}.")
            if state.runner_status == RunnerStatus.STOPPED:
                return state

            pending_updater = ZepGraphMemoryManager.get_updater(simulation_id)
            retrying_finalization = (
                pending_updater is not None
                and state.runner_status in {
                    RunnerStatus.STOPPING,
                    RunnerStatus.FAILED,
                }
            )
            if (
                state.runner_status not in [
                    RunnerStatus.STARTING,
                    RunnerStatus.RUNNING,
                    RunnerStatus.PAUSED,
                    RunnerStatus.STOPPING,
                ]
                and not retrying_finalization
            ):
                raise ValueError(
                    f"Simulation is not running: {simulation_id}, status={state.runner_status}."
                )

            state.runner_status = RunnerStatus.STOPPING
            cls._manual_stop_requests.add(simulation_id)
            cls._save_run_state(state)
            cls._sync_simulation_status(simulation_id, RunnerStatus.STOPPING)

            # Terminate the process, in this backend or outside it
            process = cls._processes.get(simulation_id)
            if process and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.error(f"Failed to terminate the process group: {simulation_id}, error={e}")
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except Exception:
                        process.kill()
            else:
                # After a backend restart the registry is empty while the child
                # is still alive, because it was spawned with
                # start_new_session=True. Reap it by its persisted PID rather
                # than reporting a stop that killed nothing.
                try:
                    reaped_pid = cls.reap_simulation(simulation_id)
                except Exception as e:
                    reaped_pid = None
                    logger.error(f"Failed to reap the orphaned process: {simulation_id}, error={e}")
                if reaped_pid is not None:
                    logger.info(f"Reaped orphaned pid {reaped_pid} while stopping simulation {simulation_id}")

        # Let the monitor consume the final action-log tail and own the single
        # updater drain. It will publish STOPPED (rather than COMPLETED) because
        # the manual-stop marker is set above.
        monitor = cls._monitor_threads.get(simulation_id)
        if (
            not retrying_finalization
            and
            monitor is not None
            and monitor is not threading.current_thread()
            and monitor.is_alive()
        ):
            wait_timeout = max(
                30.0,
                ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
                + ZEP_HTTP_REQUEST_TIMEOUT_SECONDS
                + 5,
            )
            monitor.join(timeout=wait_timeout)
            if monitor.is_alive():
                # The monitor still owns finalization and may be inside one
                # bounded HTTP request. Do not block on or overwrite its lock;
                # leave the observable state as STOPPING and let polling expose
                # the eventual STOPPED/FAILED result.
                raise SimulationStopPending(
                    f"Simulation is still stopping; the graph writes did not finish within {wait_timeout:.0f}s."
                )
        else:
            # Restart recovery or tests may have no monitor thread. Complete
            # the same barrier synchronously in this request.
            with cls._finalization_lock(simulation_id):
                state = cls.get_run_state(simulation_id) or state
                if cls._graph_memory_enabled.get(simulation_id, False):
                    try:
                        ZepGraphMemoryManager.stop_updater(simulation_id)
                        cls._graph_memory_enabled.pop(simulation_id, None)
                    except Exception as error:
                        state.runner_status = RunnerStatus.FAILED
                        state.twitter_running = False
                        state.reddit_running = False
                        state.completed_at = datetime.now().isoformat()
                        state.error = f"Zep graph writes did not complete: {error}"
                        cls._save_run_state(state)
                        cls._sync_simulation_status(
                            simulation_id,
                            RunnerStatus.FAILED,
                            state.error,
                        )
                        raise RuntimeError(state.error) from error
                state.runner_status = RunnerStatus.STOPPED
                state.twitter_running = False
                state.reddit_running = False
                state.completed_at = datetime.now().isoformat()
                state.error = None
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.STOPPED,
                )
                cls._manual_stop_requests.discard(simulation_id)

        state = cls.get_run_state(simulation_id) or state
        if state.runner_status == RunnerStatus.FAILED:
            raise RuntimeError(state.error or "Failed to stop the simulation.")
        if state.runner_status != RunnerStatus.STOPPED:
            raise RuntimeError(
                f"Simulation did not reach a terminal state: {simulation_id}, status={state.runner_status}."
            )

        logger.info(f"Stopped simulation {simulation_id}")
        return state

    @classmethod
    def _read_actions_from_file(
        cls,
        file_path: str,
        default_platform: Optional[str] = None,
        platform_filter: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Read actions from one action file.
        
        Args:
            file_path: Action log path
            default_platform: Platform to use when a record carries no platform field
            platform_filter: Keep only this platform
            agent_id: Keep only this agent
            round_num: Keep only this round
        """
        if not os.path.exists(file_path):
            return []
        
        actions = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    
                    # Skip event records such as simulation_start, round_start and round_end
                    if "event_type" in data:
                        continue
                    
                    # Skip records with no agent_id, which are not agent actions
                    if "agent_id" not in data:
                        continue
                    
                    # Prefer the record's own platform, fall back to the default
                    record_platform = data.get("platform") or default_platform or ""
                    
                    # Filters
                    if platform_filter and record_platform != platform_filter:
                        continue
                    if agent_id is not None and data.get("agent_id") != agent_id:
                        continue
                    if round_num is not None and data.get("round") != round_num:
                        continue
                    
                    actions.append(AgentAction(
                        round_num=data.get("round", 0),
                        timestamp=data.get("timestamp", ""),
                        platform=record_platform,
                        agent_id=data.get("agent_id", 0),
                        agent_name=data.get("agent_name", ""),
                        action_type=data.get("action_type", ""),
                        action_args=data.get("action_args", {}),
                        result=data.get("result"),
                        success=data.get("success", True),
                    ))
                    
                except json.JSONDecodeError:
                    continue
        
        return actions
    
    @classmethod
    def get_all_actions(
        cls,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Return the full action history across platforms, with no paging.
        
        Args:
            simulation_id: Simulation ID
            platform: Keep only this platform (twitter/reddit)
            agent_id: Keep only this agent
            round_num: Keep only this round
            
        Returns:
            Every action, newest first
        """
        sim_dir = cls._simulation_dir(simulation_id)
        actions = []
        
        # The Twitter file implies platform=twitter
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",  # Fill in the platform field
                platform_filter=platform,
                agent_id=agent_id, 
                round_num=round_num
            ))
        
        # The Reddit file implies platform=reddit
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",  # Fill in the platform field
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))
        
        # Fall back to the older single-file layout
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # The old format carries its own platform field
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )
        
        # Newest first
        actions.sort(key=lambda x: x.timestamp, reverse=True)
        
        return actions
    
    @classmethod
    def get_actions(
        cls,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Return the action history, paged.
        
        Args:
            simulation_id: Simulation ID
            limit: Maximum number of actions to return
            offset: Offset into the history
            platform: Keep only this platform
            agent_id: Keep only this agent
            round_num: Keep only this round
            
        Returns:
            Action list
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # Page
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Return the simulation timeline, rolled up per round.
        
        Args:
            simulation_id: Simulation ID
            start_round: First round to include
            end_round: Last round to include
            
        Returns:
            One summary per round
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        # Group by round
        rounds: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            round_num = action.round_num
            
            if round_num < start_round:
                continue
            if end_round is not None and round_num > end_round:
                continue
            
            if round_num not in rounds:
                rounds[round_num] = {
                    "round_num": round_num,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "active_agents": set(),
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            r = rounds[round_num]
            
            if action.platform == "twitter":
                r["twitter_actions"] += 1
            else:
                r["reddit_actions"] += 1
            
            r["active_agents"].add(action.agent_id)
            r["action_types"][action.action_type] = r["action_types"].get(action.action_type, 0) + 1
            r["last_action_time"] = action.timestamp
        
        # Flatten into a list
        result = []
        for round_num in sorted(rounds.keys()):
            r = rounds[round_num]
            result.append({
                "round_num": round_num,
                "twitter_actions": r["twitter_actions"],
                "reddit_actions": r["reddit_actions"],
                "total_actions": r["twitter_actions"] + r["reddit_actions"],
                "active_agents_count": len(r["active_agents"]),
                "active_agents": list(r["active_agents"]),
                "action_types": r["action_types"],
                "first_action_time": r["first_action_time"],
                "last_action_time": r["last_action_time"],
            })
        
        return result
    
    @classmethod
    def get_agent_stats(cls, simulation_id: str) -> List[Dict[str, Any]]:
        """
        Return per-agent statistics.
        
        Returns:
            One record per agent
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        agent_stats: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            agent_id = action.agent_id
            
            if agent_id not in agent_stats:
                agent_stats[agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": action.agent_name,
                    "total_actions": 0,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            stats = agent_stats[agent_id]
            stats["total_actions"] += 1
            
            if action.platform == "twitter":
                stats["twitter_actions"] += 1
            else:
                stats["reddit_actions"] += 1
            
            stats["action_types"][action.action_type] = stats["action_types"].get(action.action_type, 0) + 1
            stats["last_action_time"] = action.timestamp
        
        # Busiest agents first
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Delete the run logs of a simulation, so the next run starts clean.
        
        Deletes:
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - twitter_simulation.db (simulation database)
        - reddit_simulation.db (simulation database)
        - env_status.json (environment status)
        
        The configuration and profile files are kept.
        
        Args:
            simulation_id: Simulation ID
            
        Returns:
            Cleanup result
        """
        import shutil
        
        sim_dir = cls._simulation_dir(simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory not found; nothing to clean up"}
        
        cleaned_files = []
        errors = []
        
        # Files to delete, including the databases
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter platform database
            "reddit_simulation.db",   # Reddit platform database
            "env_status.json",        # Environment status file
        ]
        
        # Directories holding the action logs
        dirs_to_clean = ["twitter", "reddit"]
        
        # Delete the files
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"Failed to delete {filename}: {e}")
        
        # Delete the action logs inside the platform directories
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"Failed to delete {dir_name}/actions.jsonl: {e}")
        
        # Drop the cached run state
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]
        
        logger.info(f"Cleaned up the simulation logs: {simulation_id}, deleted: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # Guards against a repeated cleanup
    _cleanup_done = False
    
    @classmethod
    def cleanup_all_simulations(cls):
        """
        Terminate every running simulation process.
        
        Called at server shutdown so no child process is left behind.
        """
        # Guard against a repeated cleanup
        if cls._cleanup_done:
            return
        cls._cleanup_done = True

        updater_ids = set(ZepGraphMemoryManager.get_simulation_ids())
        simulation_ids = sorted(
            set(cls._processes)
            | set(cls._graph_memory_enabled)
            | updater_ids
        )
        if not simulation_ids:
            return

        logger.info("Finalizing every simulation process and graph write")
        cleanup_failed = False

        # Each simulation follows the normal stop/finalization path: terminate
        # its producer, let the monitor consume the final action-log tail, and
        # only then drain Zep. This avoids dropping actions emitted during
        # SIGTERM handling.
        for simulation_id in simulation_ids:
            try:
                state = cls.get_run_state(simulation_id)
                updater = ZepGraphMemoryManager.get_updater(simulation_id)
                process = cls._processes.get(simulation_id)

                if state is None:
                    # Missing/corrupt state is exceptional, but retain the
                    # critical producer-before-consumer shutdown ordering.
                    if process is not None and process.poll() is None:
                        cls._terminate_process(process, simulation_id, timeout=5)
                    if updater is not None:
                        ZepGraphMemoryManager.stop_updater(simulation_id)
                    continue

                if updater is not None:
                    cls._graph_memory_enabled[simulation_id] = True
                    if state.runner_status in {
                        RunnerStatus.IDLE,
                        RunnerStatus.STOPPED,
                        RunnerStatus.COMPLETED,
                    }:
                        # A retained updater means the old terminal projection
                        # was premature. Restore the ingestion barrier first.
                        state.runner_status = RunnerStatus.STOPPING
                        cls._save_run_state(state)
                        cls._sync_simulation_status(
                            simulation_id,
                            RunnerStatus.STOPPING,
                        )

                needs_finalization = bool(
                    (process is not None and process.poll() is None)
                    or updater is not None
                    or state.runner_status in {
                        RunnerStatus.STARTING,
                        RunnerStatus.RUNNING,
                        RunnerStatus.PAUSED,
                        RunnerStatus.STOPPING,
                    }
                )
                if needs_finalization:
                    cls.stop_simulation(simulation_id)

                # A recovery path without a monitor does not run the monitor's
                # resource cleanup block. Release only successfully stopped
                # resources; FAILED/STOPPING resources remain retryable.
                latest = cls.get_run_state(simulation_id)
                if latest and latest.runner_status == RunnerStatus.STOPPED:
                    stopped_process = cls._processes.get(simulation_id)
                    if stopped_process is None or stopped_process.poll() is not None:
                        cls._processes.pop(simulation_id, None)
                        cls._action_queues.pop(simulation_id, None)
                        cls._monitor_threads.pop(simulation_id, None)
                        for file_map in (cls._stdout_files, cls._stderr_files):
                            file_handle = file_map.pop(simulation_id, None)
                            if file_handle:
                                try:
                                    file_handle.close()
                                except Exception:
                                    pass
            except Exception as error:
                cleanup_failed = True
                logger.error(
                    "Failed to clean up a simulation; keeping its state for a retry: simulation_id=%s, error=%s",
                    simulation_id,
                    error,
                )

        if cleanup_failed:
            # Retained updaters and FAILED run states continue to block report
            # generation and graph deletion. Permit an explicit retry.
            cls._cleanup_done = False
            logger.error("Some simulations did not finish cleanup safely")
        else:
            logger.info("Finished cleaning up the simulation processes and graph writes")
    
    @classmethod
    def register_cleanup(cls):
        """
        Register the shutdown cleanup.
        
        Called from the Flask app factory so shutdown terminates every simulation.
        """
        global _cleanup_registered
        
        if _cleanup_registered:
            return
        
        # Under the Flask reloader only the child process runs the app, and it is
        # the one with WERKZEUG_RUN_MAIN=true. Outside debug mode the variable is
        # absent and this process must register.
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        
        # In debug mode register only in the reloader child
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # Keep the parent from trying again
            return
        
        # Keep the original signal handlers
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP exists only on Unix
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)
        
        def cleanup_handler(signum=None, frame=None):
            """Clean up the simulations, then chain to the original handler."""
            # Only say something when there is work to do
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"Received signal {signum}; cleaning up")
            cls.cleanup_all_simulations()
            
            # Chain to the original handler so Flask exits normally
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP arrives when the terminal closes
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # Default behaviour: exit normally
                    sys.exit(0)
            else:
                # An uncallable original handler, such as SIG_DFL, falls back here
                raise KeyboardInterrupt
        
        # atexit is the backstop
        atexit.register(cls.cleanup_all_simulations)
        
        # Signal handlers can only be installed on the main thread
        try:
            # SIGTERM: the default signal sent by kill
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: the terminal closed (Unix only)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # Not on the main thread, so atexit is all that is left
            logger.warning("Cannot install signal handlers off the main thread; using atexit only")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        Return the IDs of every simulation running in this process.
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Process identity, reaping and reconciliation ==============

    @staticmethod
    def _pid_alive(pid: Optional[int]) -> bool:
        """Report whether a PID currently belongs to a live process."""
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The process exists; it simply belongs to another user.
            return True
        except OSError:
            return False
        return True

    @staticmethod
    def _process_command_line(pid: int) -> Optional[str]:
        """Return the command line of a PID, or None when it cannot be read."""
        try:
            import psutil
        except ImportError:
            psutil = None

        if psutil is not None:
            try:
                return ' '.join(psutil.Process(pid).cmdline())
            except Exception:
                return None

        if IS_WINDOWS:
            return None

        try:
            result = subprocess.run(
                ['ps', '-o', 'args=', '-p', str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    @classmethod
    def _pid_owns_simulation(cls, pid: Optional[int], simulation_id: str) -> bool:
        """
        Report whether a live PID really is this simulation's runner.

        The child is launched as `python <script> --config <sim_dir>/simulation_config.json`,
        so the simulation id always appears in its command line. Without that
        confirmation the PID is treated as gone: an id recycled by the operating
        system would otherwise make a stop or a delete signal an unrelated
        process.
        """
        if not cls._pid_alive(pid):
            return False

        command_line = cls._process_command_line(pid)
        if command_line is None:
            logger.warning(
                "Cannot read the command line of pid %s, so it is not reaped "
                "for simulation %s",
                pid,
                simulation_id,
            )
            return False
        return simulation_id in command_line

    @classmethod
    def describe_activity(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Describe whether a simulation is active, in this process or outside it.

        The in-memory registries answer for runs this backend started. After a
        restart they are empty while the child is still alive, so the persisted
        PID is checked too - that orphan is exactly the row the Simulations menu
        must offer Stop and Restart on.

        Returns:
            {"simulation_id", "active", "reason", "runner_status", "pid",
             "adopted", "has_monitor", "has_updater", "stale"}
        """
        state = cls.get_run_state(simulation_id)
        runner_status = state.runner_status if state else RunnerStatus.IDLE

        process = cls._processes.get(simulation_id)
        live_child = process is not None and process.poll() is None
        monitor = cls._monitor_threads.get(simulation_id)
        updater = ZepGraphMemoryManager.get_updater(simulation_id)

        orphan_pid = None
        if not live_child and runner_status in cls.ACTIVE_STATUSES:
            persisted_pid = state.process_pid if state else None
            if cls._pid_owns_simulation(persisted_pid, simulation_id):
                orphan_pid = persisted_pid

        pid = process.pid if live_child else orphan_pid
        active = live_child or orphan_pid is not None or updater is not None

        if live_child:
            reason = f"running as pid {pid}"
        elif orphan_pid is not None:
            reason = f"running as orphaned pid {orphan_pid}"
        elif updater is not None:
            reason = "still writing to the knowledge graph"
        else:
            reason = f"not running, status {runner_status.value}"

        return {
            "simulation_id": simulation_id,
            "active": active,
            "reason": reason,
            "runner_status": runner_status.value,
            "pid": pid,
            "adopted": orphan_pid is not None,
            "has_monitor": monitor is not None and monitor.is_alive(),
            "has_updater": updater is not None,
            # Stale means the saved state claims a run that nothing is holding
            # any more, which is what makes a row safe to act on. It is the
            # exact negation of `active`, never an independent test: keying it
            # on `pid is None` alone reported active=true and stale=true
            # together for a run whose child had exited while its Zep updater
            # was still finalizing, and the frontend reads stale as "no process
            # to protect" and offers the destructive actions.
            "stale": runner_status in cls.ACTIVE_STATUSES and not active,
        }

    @classmethod
    def reap_simulation(cls, simulation_id: str) -> Optional[int]:
        """
        Terminate a simulation's process, wherever this backend can find it.

        Prefers the process this backend spawned and falls back to the PID
        persisted in run_state.json, so a stop still kills the child after a
        backend restart instead of reporting success while the orphan keeps
        appending to actions.jsonl.

        Returns:
            The terminated PID, or None when nothing was running
        """
        process = cls._processes.get(simulation_id)
        if process is not None and process.poll() is None:
            pid = process.pid
            cls._terminate_process(process, simulation_id)
            return pid

        state = cls.get_run_state(simulation_id)
        pid = state.process_pid if state else None
        if not cls._pid_owns_simulation(pid, simulation_id):
            return None

        logger.warning(
            "Reaping a simulation process that outlived the backend: "
            "simulation_id=%s, pid=%s",
            simulation_id,
            pid,
        )
        try:
            cls._terminate_process(_AdoptedProcess(pid), simulation_id)
        except ProcessLookupError:
            # The orphan exited between the liveness check and the signal,
            # which is the outcome the caller wanted anyway.
            pass
        return pid

    @classmethod
    def release_simulation(cls, simulation_id: str) -> None:
        """
        Drop every in-memory resource this backend holds for a simulation.

        A retained Zep updater still owes the graph the tail of the run, so it
        is drained rather than dropped. A drain failure propagates: the caller's
        delete or restart must not proceed over data Zep has accepted but not
        yet processed.
        """
        if ZepGraphMemoryManager.get_updater(simulation_id) is not None:
            ZepGraphMemoryManager.stop_updater(simulation_id)

        cls._graph_memory_enabled.pop(simulation_id, None)
        cls._processes.pop(simulation_id, None)
        cls._monitor_threads.pop(simulation_id, None)
        cls._action_queues.pop(simulation_id, None)
        cls._run_states.pop(simulation_id, None)
        cls._manual_stop_requests.discard(simulation_id)

        for file_map in (cls._stdout_files, cls._stderr_files):
            handle = file_map.pop(simulation_id, None)
            if handle:
                try:
                    handle.close()
                except Exception:
                    pass

        with cls._finalization_locks_guard:
            cls._finalization_locks.pop(simulation_id, None)

    @classmethod
    def restart_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",
        max_rounds: int = None,
        enable_graph_memory_update: bool = False,
        graph_id: str = None,
    ) -> SimulationRunState:
        """
        Restart a simulation from a clean slate.

        Every restart quiesces the previous run and clears its logs first. This
        is not an optimization: the child opens twitter/actions.jsonl and
        reddit/actions.jsonl in append mode while a new monitor reads them from
        byte 0, so a restart that skips the cleanup replays the whole previous
        run - it re-counts every action, trips the completion flags off the old
        simulation_end events, and pushes every old action to Zep a second time.

        Args:
            simulation_id: Simulation ID
            platform: Platform to run (twitter/reddit/parallel)
            max_rounds: Cap on rounds, to truncate an over-long simulation
            enable_graph_memory_update: Push agent activity into the Zep graph
            graph_id: Zep graph ID, required when graph updates are on

        Returns:
            SimulationRunState for the new run
        """
        reaped_pid = cls.reap_simulation(simulation_id)
        if reaped_pid is not None:
            logger.info(
                "Reaped pid %s before restarting simulation %s",
                reaped_pid,
                simulation_id,
            )

        monitor = cls._monitor_threads.get(simulation_id)
        if (
            monitor is not None
            and monitor is not threading.current_thread()
            and monitor.is_alive()
        ):
            # Let the previous monitor publish its terminal state first.
            # Otherwise it writes run_state.json after the cleanup below has
            # deleted it, and the stale terminal status lands on top of the new
            # run.
            monitor.join(timeout=30)
            if monitor.is_alive():
                raise SimulationStopPending(
                    f"The previous run of {simulation_id} is still finalizing. "
                    f"Retry the restart shortly."
                )

        cls.release_simulation(simulation_id)

        cleanup = cls.cleanup_simulation_logs(simulation_id)
        if not cleanup.get("success"):
            errors = "; ".join(cleanup.get("errors") or [])
            raise RuntimeError(
                f"Failed to clear the previous run before restarting: {errors}"
            )

        state = cls.start_simulation(
            simulation_id=simulation_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=enable_graph_memory_update,
            graph_id=graph_id,
        )
        logger.info(f"Restarted simulation {simulation_id}, platform={platform}")
        return state

    @classmethod
    def _adopt_running_simulation(cls, state: SimulationRunState) -> None:
        """
        Re-attach a monitor to a run that outlived the backend.

        The monitor resumes at the current end of each action log. Actions
        written while the backend was down stay in actions.jsonl and are still
        returned by get_actions; they are deliberately not replayed into the
        live counters, which already include everything up to the restart.
        Graph memory updates cannot be resumed, because the updater's queue died
        with the previous process.
        """
        simulation_id = state.simulation_id
        sim_dir = cls._simulation_dir(simulation_id)

        positions = {}
        for platform in ("twitter", "reddit"):
            log_path = os.path.join(sim_dir, platform, "actions.jsonl")
            positions[platform] = (
                os.path.getsize(log_path) if os.path.exists(log_path) else 0
            )

        monitor = threading.Thread(
            target=cls._monitor_simulation,
            args=(simulation_id, positions["twitter"], positions["reddit"]),
            daemon=True,
        )

        with cls._finalization_lock(simulation_id):
            cls._processes[simulation_id] = _AdoptedProcess(state.process_pid)
            cls._monitor_threads[simulation_id] = monitor
            cls._action_queues.setdefault(simulation_id, Queue())
            cls._graph_memory_enabled[simulation_id] = False
            state.runner_status = RunnerStatus.RUNNING
            state.error = None
            cls._save_run_state(state)
            cls._sync_simulation_status(simulation_id, RunnerStatus.RUNNING)
            monitor.start()

        logger.warning(
            "Adopted a simulation that outlived the backend: simulation_id=%s, "
            "pid=%s. Graph memory updates are not resumed for this run.",
            simulation_id,
            state.process_pid,
        )

    @classmethod
    def reconcile_runs(cls) -> List[Dict[str, Any]]:
        """
        Repair run states left mid-flight by a backend restart.

        A child spawned with start_new_session=True survives the backend, so a
        live orphan is adopted and monitored again rather than killed. One whose
        stop was already requested is finished, and one whose process is gone is
        failed with an explanatory error, so the row stops claiming to be
        running and the menu can offer Restart.

        Returns:
            One record per repaired run
        """
        from .simulation_manager import SIMULATION_ID_PATTERN

        results: List[Dict[str, Any]] = []
        if not os.path.isdir(cls.RUN_STATE_DIR):
            return results

        for simulation_id in sorted(os.listdir(cls.RUN_STATE_DIR)):
            if not SIMULATION_ID_PATTERN.match(simulation_id):
                continue
            if not os.path.isdir(os.path.join(cls.RUN_STATE_DIR, simulation_id)):
                continue
            if simulation_id in cls._processes or simulation_id in cls._monitor_threads:
                continue

            state = cls._load_run_state(simulation_id)
            if state is None or state.runner_status not in cls.ACTIVE_STATUSES:
                continue

            previous_status = state.runner_status.value
            alive = cls._pid_owns_simulation(state.process_pid, simulation_id)

            if alive and state.runner_status == RunnerStatus.STOPPING:
                # A stop was already requested, so finish it rather than
                # resurrecting a run the user asked to end.
                reaped_pid = cls.reap_simulation(simulation_id)
                state.runner_status = RunnerStatus.STOPPED
                state.twitter_running = False
                state.reddit_running = False
                state.completed_at = datetime.now().isoformat()
                state.error = None
                cls._save_run_state(state)
                cls._sync_simulation_status(simulation_id, RunnerStatus.STOPPED)
                action, pid, error = "stopped", reaped_pid, None
            elif alive:
                cls._adopt_running_simulation(state)
                action, pid, error = "adopted", state.process_pid, None
            else:
                state.runner_status = RunnerStatus.FAILED
                state.twitter_running = False
                state.reddit_running = False
                state.completed_at = datetime.now().isoformat()
                state.error = RUN_INTERRUPTED_ERROR
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.FAILED,
                    state.error,
                )
                action, pid, error = "failed", None, state.error

            results.append({
                "simulation_id": simulation_id,
                "previous_status": previous_status,
                "status": state.runner_status.value,
                "action": action,
                "pid": pid,
                "error": error,
            })
            logger.warning(
                "Reconciled an interrupted run: simulation_id=%s, %s -> %s (%s)",
                simulation_id,
                previous_status,
                state.runner_status.value,
                action,
            )

        return results

    @classmethod
    def reconcile_startup(cls) -> Dict[str, Any]:
        """
        Repair every simulation stranded by a backend restart.

        Call this once from the Flask app factory, beside register_cleanup and
        behind the same WERKZEUG_RUN_MAIN guard, so the reloader parent does not
        run it twice.

        Preparation and monitoring both run in daemon threads, so a restart
        kills them with no exception and no failure handler ever runs. Without
        this pass state.json stays 'preparing' forever - and every later start
        is refused with "Simulation not ready. Current status: preparing." -
        while run_state.json stays 'running' behind a PID this process knows
        nothing about.

        Returns:
            {"preparations": [...], "runs": [...]}
        """
        from .simulation_manager import SimulationManager

        try:
            preparations = SimulationManager().reconcile_preparations()
        except Exception as error:
            # Reconciliation runs during app startup. A failure here must not
            # take the backend down with it.
            logger.error(f"Failed to reconcile interrupted preparations: {error}")
            preparations = []

        try:
            runs = cls.reconcile_runs()
        except Exception as error:
            logger.error(f"Failed to reconcile interrupted runs: {error}")
            runs = []

        if preparations or runs:
            logger.warning(
                "Startup reconciliation repaired %s interrupted preparations "
                "and %s interrupted runs",
                len(preparations),
                len(runs),
            )
        return {"preparations": preparations, "runs": runs}

    # ============== Log viewer ==============

    @classmethod
    def _log_source_path(cls, simulation_id: str, source: str) -> tuple:
        """Return the absolute path and the display path of one log source."""
        if source == "backend":
            filename = datetime.now().strftime('%Y-%m-%d') + '.log'
            return os.path.join(BACKEND_LOG_DIR, filename), f"logs/{filename}"

        sim_dir = cls._simulation_dir(simulation_id)
        if source == "main":
            return os.path.join(sim_dir, "simulation.log"), "simulation.log"
        if source in ("twitter", "reddit"):
            return (
                os.path.join(sim_dir, source, "actions.jsonl"),
                f"{source}/actions.jsonl",
            )
        raise ValueError(
            f"Unknown log source: {source}. Options: {', '.join(cls.LOG_SOURCES)}."
        )

    @classmethod
    def tail_log(
        cls,
        simulation_id: str,
        source: str = "main",
        max_lines: int = 500,
        max_bytes: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Read a bounded window of one log.

        A long run writes hundreds of megabytes of actions.jsonl, so the file is
        never read whole: with no offset the window is the last max_bytes of the
        file, and with one it is the next max_bytes from there, which lets a
        viewer poll forward by byte offset the way the monitor already does.

        Args:
            simulation_id: Simulation ID
            source: One of main, twitter, reddit, backend
            max_lines: Maximum number of lines to return
            max_bytes: Size of the window, capped at MAX_LOG_TAIL_BYTES
            offset: Byte offset to read forward from, or None for the tail.
                Pass back the next_offset of the previous call; an arbitrary
                offset may land mid-line.

        Returns:
            {"simulation_id", "source", "path", "exists", "size", "offset",
             "next_offset", "eof", "truncated", "restarted", "lines"}
        """
        if source not in cls.LOG_SOURCES:
            raise ValueError(
                f"Unknown log source: {source}. Options: {', '.join(cls.LOG_SOURCES)}."
            )

        path, display_path = cls._log_source_path(simulation_id, source)
        window = min(max_bytes or cls.MAX_LOG_TAIL_BYTES, cls.MAX_LOG_TAIL_BYTES)
        max_lines = max(1, min(max_lines, cls.MAX_LOG_TAIL_LINES))

        result: Dict[str, Any] = {
            "simulation_id": simulation_id,
            "source": source,
            "path": display_path,
            "exists": False,
            "size": 0,
            "offset": 0,
            "next_offset": 0,
            "eof": True,
            "truncated": False,
            "restarted": False,
            "lines": [],
        }

        if not os.path.isfile(path):
            return result

        size = os.path.getsize(path)
        result["exists"] = True
        result["size"] = size

        start = 0
        if offset is None:
            start = max(0, size - window)
        else:
            start = max(0, int(offset))
            if start > size:
                # Every run reopens simulation.log with mode='w', so a restart
                # truncates it and a caller's offset now points past the end.
                result["restarted"] = True
                start = 0

        with open(path, 'rb') as f:
            f.seek(start)
            raw = f.read(window)

        head = 0
        if offset is None and start > 0:
            # A tail window begins mid-line, so drop that first fragment. An
            # offset supplied by the caller is line-aligned already, because it
            # came from a previous next_offset.
            newline = raw.find(b'\n')
            head = len(raw) if newline == -1 else newline + 1

        tail = len(raw)
        if start + len(raw) < size and not raw.endswith(b'\n'):
            # Leave a partial trailing line for the next read.
            newline = raw.rfind(b'\n')
            tail = max(head, 0 if newline == -1 else newline + 1)

        result["offset"] = start
        result["next_offset"] = start + max(head, tail)
        result["eof"] = result["next_offset"] >= size
        result["truncated"] = start > 0

        lines = raw[head:tail].decode('utf-8', errors='replace').splitlines()
        if source == "backend":
            # The backend log is shared by every simulation.
            lines = [line for line in lines if simulation_id in line]
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
            result["truncated"] = True
        result["lines"] = lines

        return result
    
    # ============== Interviews ==============
    
    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        Report whether the simulation environment can accept interview commands.

        Args:
            simulation_id: Simulation ID

        Returns:
            True when the environment is alive
        """
        sim_dir = cls._simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Return the detailed status of the simulation environment.

        Args:
            simulation_id: Simulation ID

        Returns:
            Status detail: status, twitter_available, reddit_available, timestamp
        """
        sim_dir = cls._simulation_dir(simulation_id)
        status_file = os.path.join(sim_dir, "env_status.json")
        
        default_status = {
            "status": "stopped",
            "twitter_available": False,
            "reddit_available": False,
            "timestamp": None
        }
        
        if not os.path.exists(status_file):
            return default_status
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return {
                "status": status.get("status", "stopped"),
                "twitter_available": status.get("twitter_available", False),
                "reddit_available": status.get("reddit_available", False),
                "timestamp": status.get("timestamp")
            }
        except (json.JSONDecodeError, OSError):
            return default_status

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """
        Interview a single agent.

        Args:
            simulation_id: Simulation ID
            agent_id: Agent ID
            prompt: Interview question
            platform: Platform to interview on (optional)
                - "twitter": Twitter only
                - "reddit": Reddit only
                - None: both platforms on a dual-platform simulation, merged into one result
            timeout: Response timeout, in seconds

        Returns:
            Interview result

        Raises:
            ValueError: The simulation does not exist, or its environment is not running
            TimeoutError: No response arrived within the timeout
        """
        sim_dir = cls._simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}.")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running, so it cannot be interviewed: {simulation_id}.")

        logger.info(f"Sending an interview command: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

        response = ipc_client.send_interview(
            agent_id=agent_id,
            prompt=prompt,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "agent_id": agent_id,
                "prompt": prompt,
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_agents_batch(
        cls,
        simulation_id: str,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        Interview several agents in one command.

        Args:
            simulation_id: Simulation ID
            interviews: Interview list, each item {"agent_id": int, "prompt": str, "platform": str (optional)}
            platform: Default platform, overridden by an item's own platform
                - "twitter": Twitter only by default
                - "reddit": Reddit only by default
                - None: both platforms on a dual-platform simulation
            timeout: Response timeout, in seconds

        Returns:
            Batch interview result

        Raises:
            ValueError: The simulation does not exist, or its environment is not running
            TimeoutError: No response arrived within the timeout
        """
        sim_dir = cls._simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}.")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running, so it cannot be interviewed: {simulation_id}.")

        logger.info(f"Sending a batch interview command: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

        response = ipc_client.send_batch_interview(
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "interviews_count": len(interviews),
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "interviews_count": len(interviews),
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_all_agents(
        cls,
        simulation_id: str,
        prompt: str,
        platform: str = None,
        timeout: float = 180.0
    ) -> Dict[str, Any]:
        """
        Interview every agent in the simulation.

        Every agent is asked the same question.

        Args:
            simulation_id: Simulation ID
            prompt: Interview question, asked of every agent
            platform: Platform to interview on (optional)
                - "twitter": Twitter only
                - "reddit": Reddit only
                - None: both platforms on a dual-platform simulation
            timeout: Response timeout, in seconds

        Returns:
            Interview result for every agent
        """
        sim_dir = cls._simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}.")

        # Every agent is listed in the generated configuration
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"Simulation config not found: {simulation_id}.")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"Simulation config contains no agents: {simulation_id}.")

        # Build the batch interview list
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"Sending an interview command for every agent: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

        return cls.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )
    
    @classmethod
    def close_simulation_env(
        cls,
        simulation_id: str,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """
        Close the simulation environment, leaving the process alive.
        
        Asks the simulation to leave command-wait mode and shut down gracefully.
        
        Args:
            simulation_id: Simulation ID
            timeout: Response timeout, in seconds
            
        Returns:
            Operation result
        """
        sim_dir = cls._simulation_dir(simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}.")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": "Environment is already closed"
            }
        
        logger.info(f"Sending a close-environment command: simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "Close-environment command sent",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # A timeout most likely means the environment is already shutting down
            return {
                "success": True,
                "message": "Close-environment command sent; no response arrived, so the environment may still be shutting down"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Read the interview history from one simulation database."""
        import sqlite3
        
        if not os.path.exists(db_path):
            return []
        
        results = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            if agent_id is not None:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview' AND user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            else:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview'
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            for user_id, info_json, created_at in cursor.fetchall():
                try:
                    info = json.loads(info_json) if info_json else {}
                except json.JSONDecodeError:
                    info = {"raw": info_json}
                
                results.append({
                    "agent_id": user_id,
                    "response": info.get("response", info),
                    "prompt": info.get("prompt", ""),
                    "timestamp": created_at,
                    "platform": platform_name
                })
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to read the interview history ({platform_name}): {e}")
        
        return results

    @classmethod
    def get_interview_history(
        cls,
        simulation_id: str,
        platform: str = None,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Return the interview history, read from the simulation databases.
        
        Args:
            simulation_id: Simulation ID
            platform: Platform (reddit/twitter/None)
                - "reddit": Reddit history only
                - "twitter": Twitter history only
                - None: history from both platforms
            agent_id: Return only this agent's history (optional)
            limit: Maximum number of records per platform
            
        Returns:
            Interview history records
        """
        sim_dir = cls._simulation_dir(simulation_id)
        
        results = []
        
        # Platforms to query
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # With no platform named, query both
            platforms = ["twitter", "reddit"]
        
        for p in platforms:
            db_path = os.path.join(sim_dir, f"{p}_simulation.db")
            platform_results = cls._get_interview_history_from_db(
                db_path=db_path,
                platform_name=p,
                agent_id=agent_id,
                limit=limit
            )
            results.extend(platform_results)
        
        # Newest first
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Cap the merged result when both platforms were queried
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results
