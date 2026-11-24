"""
OASIS Simulation Runner
Runs the simulation in the background, records each Agent's actions, and supports real-time status monitoring.
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
from ..utils.locale import get_locale, set_locale
from ..utils.zep import (
    ZEP_HTTP_REQUEST_TIMEOUT_SECONDS,
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
)
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# Flag indicating whether the cleanup function has been registered
_cleanup_registered = False

# Platform detection
IS_WINDOWS = sys.platform == 'win32'


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


@dataclass
class AgentAction:
    """Agent action record"""
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
    """Per-round summary"""
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
    """Simulation run state (real-time)"""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE

    # Progress information
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0

    # Per-platform independent round counts and simulated time (for dual-platform parallel display)
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0

    # Platform status
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0

    # Platform completion state (detected via simulation_end events in actions.jsonl)
    twitter_completed: bool = False
    reddit_completed: bool = False

    # Per-round summaries
    rounds: List[RoundSummary] = field(default_factory=list)

    # Recent actions (for real-time frontend display)
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50

    # Timestamps
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None

    # Error information
    error: Optional[str] = None

    # Process ID (used for stopping)
    process_pid: Optional[int] = None

    def add_action(self, action: AgentAction):
        """Add an action to the recent actions list"""
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
            # Per-platform independent round counts and time
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
        """Detailed information including recent actions"""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    Simulation Runner

    Responsible for:
    1. Running the OASIS simulation in a background process
    2. Parsing run logs and recording each Agent's actions
    3. Providing real-time status query interface
    4. Supporting pause/stop/resume operations
    """

    # Run state storage directory
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )

    # Scripts directory
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )

    # In-memory run states
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # stores stdout file handles
    _stderr_files: Dict[str, Any] = {}  # stores stderr file handles

    # Graph memory update configuration
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    _finalization_locks: Dict[str, threading.Lock] = {}
    _finalization_locks_guard = threading.Lock()
    _manual_stop_requests: set[str] = set()

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
                "Failed to sync simulation state: simulation_id=%s, status=%s, error=%s",
                simulation_id,
                runner_status.value,
                sync_error,
            )
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Get run state"""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]

        # Try to load from file
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Load run state from file"""
        state_file = os.path.join(cls.RUN_STATE_DIR, simulation_id, "run_state.json")
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
                # Per-platform independent round counts and time
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
            
            # Load recent actions
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
            logger.error(f"Failed to load run state: {str(e)}")
            return None

    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """Save run state to file"""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state
    
    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # maximum simulation rounds (optional, to cap overly long simulations)
        enable_graph_memory_update: bool = False,  # whether to update activities to the Zep graph
        graph_id: str = None  # Zep graph ID (required when graph update is enabled)
    ) -> SimulationRunState:
        """
        Start the simulation.

        Args:
            simulation_id: Simulation ID
            platform: Run platform (twitter/reddit/parallel)
            max_rounds: Maximum simulation rounds (optional, to cap overly long simulations)
            enable_graph_memory_update: Whether to dynamically update Agent activities to the Zep graph
            graph_id: Zep graph ID (required when graph update is enabled)

        Returns:
            SimulationRunState
        """
        # Load simulation config
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            raise ValueError(f"Simulation configuration does not exist; please call the /prepare endpoint first")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Initialize run status
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # If a maximum round count was specified, truncate accordingly
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"Round count truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
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
            existing = cls.get_run_state(simulation_id)
            active_statuses = {
                RunnerStatus.STARTING,
                RunnerStatus.RUNNING,
                RunnerStatus.PAUSED,
                RunnerStatus.STOPPING,
            }
            if (
                existing and existing.runner_status in active_statuses
            ) or ZepGraphMemoryManager.get_updater(simulation_id) is not None:
                raise ValueError(f"Simulation is already running or finishing: {simulation_id}")
            cls._save_run_state(state)
        
        # If graph memory update is enabled, create the updater
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("graph_id must be provided when graph memory update is enabled")

            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"Graph memory update enabled: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"Failed to create graph memory updater: {e}")
                cls._graph_memory_enabled[simulation_id] = False
                state.runner_status = RunnerStatus.FAILED
                state.error = f"Failed to initialize Zep graph updater: {e}"
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
        
        # Determine which script to run (scripts are in the backend/scripts/ directory)
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
                state.error += f"; Zep graph write cleanup failed: {cleanup_error}"
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
            # Build run command using full paths
            # New log structure:
            #   twitter/actions.jsonl - Twitter action log
            #   reddit/actions.jsonl  - Reddit action log
            #   simulation.log        - Main process log
            
            cmd = [
                sys.executable,  # Python interpreter
                script_path,
                "--config", config_path,  # use full config file path
            ]

            # If a maximum round count was specified, add it to the command-line arguments
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])

            # Create the main log file to avoid blocking the process due to stdout/stderr pipe buffer overflow
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')

            # Set subprocess environment variables to ensure UTF-8 encoding on Windows.
            # This fixes issues where third-party libraries (e.g. OASIS) open files without specifying an encoding.
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+: makes all open() calls default to UTF-8
            env['PYTHONIOENCODING'] = 'utf-8'  # Ensures stdout/stderr use UTF-8

            # Set working directory to the simulation directory (databases and other files will be created here).
            # Use start_new_session=True to create a new process group, enabling os.killpg to terminate all child processes.
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # stderr also writes to the same file
                text=True,
                encoding='utf-8',  # explicit encoding
                bufsize=1,
                env=env,  # pass environment variables with UTF-8 settings
                start_new_session=True,  # create a new process group so all related processes can be terminated when the server shuts down
            )
            
            # Capture locale before spawning monitor thread
            current_locale = get_locale()

            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id, current_locale),
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
            
            logger.info(f"Simulation started successfully: {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            cleanup_errors = []
            if process is not None and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except Exception as error:
                    cleanup_errors.append(f"Failed to terminate subprocess: {error}")
            cls._processes.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._stdout_files.pop(simulation_id, None)
            cls._stderr_files.pop(simulation_id, None)
            if main_log_file is not None:
                try:
                    main_log_file.close()
                except Exception as error:
                    cleanup_errors.append(f"Failed to close log: {error}")
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    cls._graph_memory_enabled.pop(simulation_id, None)
                except Exception as error:
                    cleanup_errors.append(f"Zep graph write cleanup failed: {error}")
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
    def _monitor_simulation(cls, simulation_id: str, locale: str = 'zh'):
        """Monitor the simulation process and parse action logs"""
        set_locale(locale)
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)

        # New log structure: per-platform action logs
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        twitter_position = 0
        reddit_position = 0
        
        monitor_error: Exception | None = None
        exit_code: int | None = None
        try:
            while process.poll() is None:  # process is still running
                # Read Twitter action log
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )

                # Read Reddit action log
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )

                # Update state
                cls._save_run_state(state)
                time.sleep(2)

            # After the process ends, read the logs one final time
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")
            
            exit_code = process.returncode
            
        except Exception as e:
            logger.error(f"Monitor thread error: {simulation_id}, error={str(e)}")
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
                            f"Process exit code: {exit_code}, error: {error_info}"
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
                            logger.error(f"Failed to stop graph memory updater: {error}")
                            desired_status = RunnerStatus.FAILED
                            error_message = f"Zep graph writes did not fully complete: {error}"

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
                        logger.info(f"Simulation completed: {simulation_id}")
                    else:
                        logger.error(f"Simulation failed: {simulation_id}, error={state.error}")
                cls._manual_stop_requests.discard(simulation_id)
            
            # Clean up process resources
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            
            # Close log file handles
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
        Read an action log file.

        Args:
            log_path: Path to the log file
            position: Last read position
            state: Run state object
            platform: Platform name (twitter/reddit)

        Returns:
            New read position
        """
        # Check whether graph memory update is enabled
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
                            
                            # Handle event-type entries
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")

                                # Detect simulation_end event and mark platform as complete
                                if event_type == "simulation_end":
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")

                                    # Check whether all enabled platforms have completed.
                                    # If only one platform was run, check only that platform.
                                    # If two platforms were run, both must be complete.
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        # Platform completion is only an input
                                        # signal. The monitor publishes the
                                        # terminal status after the process has
                                        # exited and Zep ingestion has drained.
                                        logger.info(
                                            f"All platforms finished; waiting for the process and graph writes to complete: "
                                            f"{state.simulation_id}"
                                        )
                                
                                # Update round info (from round_end events)
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)

                                    # Update per-platform independent round counts and time
                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours

                                    # Overall round count is the maximum across both platforms
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    # Overall simulated time is the maximum across both platforms
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
                            
                            # Update round count
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num

                            # If graph memory update is enabled, send the activity to Zep
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except Exception as e:
            logger.warning(f"Failed to read action log: {log_path}, error={e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        Check whether all enabled platforms have completed the simulation.

        Platform enablement is determined by whether the corresponding actions.jsonl file exists.

        Returns:
            True if all enabled platforms have completed
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        # Check which platforms are enabled (determined by file existence)
        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)

        # If a platform is enabled but not yet completed, return False
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False

        # At least one platform is enabled and has completed
        return twitter_enabled or reddit_enabled
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        Cross-platform process and child process termination.

        Args:
            process: The process to terminate
            simulation_id: Simulation ID (for logging)
            timeout: Timeout in seconds to wait for the process to exit
        """
        if IS_WINDOWS:
            # Windows: use taskkill to terminate the process tree
            # /F = force terminate, /T = terminate process tree (including child processes)
            logger.info(f"Terminating process tree (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # First try graceful termination
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force terminate
                    logger.warning(f"Process did not respond; force terminating: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill failed; falling back to terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: use process group termination.
            # Because start_new_session=True was used, the process group ID equals the main process PID.
            pgid = os.getpgid(process.pid)
            logger.info(f"Terminating process group (Unix): simulation={simulation_id}, pgid={pgid}")

            # First send SIGTERM to the entire process group
            os.killpg(pgid, signal.SIGTERM)

            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # If it has not exited after the timeout, force send SIGKILL
                logger.warning(f"Process group did not respond to SIGTERM; force terminating: {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)
    
    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """Stop a simulation"""
        with cls._finalization_lock(simulation_id):
            state = cls.get_run_state(simulation_id)
            if not state:
                raise ValueError(f"Simulation not found: {simulation_id}")
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
                    f"Simulation is not running: {simulation_id}, status={state.runner_status}"
                )

            state.runner_status = RunnerStatus.STOPPING
            cls._manual_stop_requests.add(simulation_id)
            cls._save_run_state(state)
            cls._sync_simulation_status(simulation_id, RunnerStatus.STOPPING)

            # Terminate the process
            process = cls._processes.get(simulation_id)
            if process and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.error(f"Failed to terminate process group: {simulation_id}, error={e}")
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except Exception:
                        process.kill()

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
                    f"Simulation is still stopping; graph writes did not finish within {wait_timeout:.0f}s"
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
                        state.error = f"Zep graph writes did not fully complete: {error}"
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
            raise RuntimeError(state.error or "Failed to stop simulation")
        if state.runner_status != RunnerStatus.STOPPED:
            raise RuntimeError(
                f"Simulation stop did not reach a terminal state: {simulation_id}, status={state.runner_status}"
            )

        logger.info(f"Simulation stopped: {simulation_id}")
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
        Read actions from a single action file.

        Args:
            file_path: Path to the action log file
            default_platform: Default platform (used when the action record has no platform field)
            platform_filter: Filter by platform
            agent_id: Filter by Agent ID
            round_num: Filter by round number
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
                    
                    # Skip non-action records (e.g. simulation_start, round_start, round_end events)
                    if "event_type" in data:
                        continue

                    # Skip records without agent_id (non-Agent actions)
                    if "agent_id" not in data:
                        continue

                    # Get platform: prefer platform field in the record, otherwise use the default
                    record_platform = data.get("platform") or default_platform or ""

                    # Filter
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
        Get the complete action history for all platforms (no pagination limit).

        Args:
            simulation_id: Simulation ID
            platform: Filter by platform (twitter/reddit)
            agent_id: Filter by Agent
            round_num: Filter by round number

        Returns:
            Complete action list (sorted by timestamp, newest first)
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []
        
        # Read Twitter action file (auto-set platform to "twitter" based on file path)
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",  # auto-fill the platform field
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))

        # Read Reddit action file (auto-set platform to "reddit" based on file path)
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",  # auto-fill the platform field
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))

        # If per-platform files do not exist, try reading the old single-file format
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # old format files should have a platform field
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )

        # Sort by timestamp (newest first)
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
        Get action history (with pagination).

        Args:
            simulation_id: Simulation ID
            limit: Maximum number of results to return
            offset: Offset
            platform: Filter by platform
            agent_id: Filter by Agent
            round_num: Filter by round number

        Returns:
            Action list
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # Paginate
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the simulation timeline (summarized by round).

        Args:
            simulation_id: Simulation ID
            start_round: Starting round
            end_round: Ending round

        Returns:
            Summary information for each round
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
        
        # Convert to list
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
        Get statistics for each Agent.

        Returns:
            List of Agent statistics
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
        
        # Sort by total action count
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Clean up simulation run logs (used to force a fresh restart of the simulation).

        The following files are deleted:
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - twitter_simulation.db (simulation database)
        - reddit_simulation.db (simulation database)
        - env_status.json (environment status)

        Note: Configuration files (simulation_config.json) and profile files are NOT deleted.

        Args:
            simulation_id: Simulation ID

        Returns:
            Cleanup result information
        """
        import shutil
        
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory does not exist; nothing to clean up"}

        cleaned_files = []
        errors = []

        # List of files to delete (including database files)
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter platform database
            "reddit_simulation.db",   # Reddit platform database
            "env_status.json",        # Environment status file
        ]

        # List of directories to clean (containing action logs)
        dirs_to_clean = ["twitter", "reddit"]

        # Delete files
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"Failed to delete {filename}: {str(e)}")

        # Clean up action logs in platform directories
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"Failed to delete {dir_name}/actions.jsonl: {str(e)}")

        # Clean up in-memory run state
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]

        logger.info(f"Simulation log cleanup complete: {simulation_id}, deleted files: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # Flag to prevent duplicate cleanup
    _cleanup_done = False

    @classmethod
    def cleanup_all_simulations(cls):
        """
        Clean up all running simulation processes.

        Called when the server shuts down to ensure all child processes are terminated.
        """
        # Prevent duplicate cleanup
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

        logger.info("Safely finishing all simulation processes and graph writes...")
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
                    "Simulation cleanup failed; keeping state for retry: simulation_id=%s, error=%s",
                    simulation_id,
                    error,
                )

        if cleanup_failed:
            # Retained updaters and FAILED run states continue to block report
            # generation and graph deletion. Permit an explicit retry.
            cls._cleanup_done = False
            logger.error("Some simulations did not finish cleanup safely")
        else:
            logger.info("Simulation process and graph write cleanup complete")
    
    @classmethod
    def register_cleanup(cls):
        """
        Register the cleanup function.

        Called at Flask application startup to ensure all simulation processes are
        terminated when the server shuts down.
        """
        global _cleanup_registered

        if _cleanup_registered:
            return

        # In Flask debug mode, only register cleanup in the reloader child process
        # (the process that actually runs the application).
        # WERKZEUG_RUN_MAIN=true indicates the reloader child process.
        # In non-debug mode this environment variable is absent, but registration is still needed.
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None

        # In debug mode, only register in the reloader child process; always register in non-debug mode.
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # Mark as registered to prevent child processes from trying again
            return

        # Save the existing signal handlers
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP only exists on Unix systems (macOS/Linux); Windows does not have it
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)

        def cleanup_handler(signum=None, frame=None):
            """Signal handler: clean up simulation processes first, then call the original handler"""
            # Only log if there are processes to clean up
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"Signal {signum} received; starting cleanup...")
            cls.cleanup_all_simulations()
            
            # Call the original signal handler so Flask exits normally
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP: sent when the terminal closes
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # Default behavior: normal exit
                    sys.exit(0)
            else:
                # Use default behavior if the original handler is not callable, such as SIG_DFL
                raise KeyboardInterrupt
        
        # Register atexit handler (as a fallback)
        atexit.register(cls.cleanup_all_simulations)

        # Register signal handlers (main thread only)
        try:
            # SIGTERM: default signal sent by the kill command
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: terminal closed (Unix systems only)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # Not in the main thread; can only use atexit
            logger.warning("Cannot register signal handlers (not in main thread); using atexit only")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        Get a list of all currently running simulation IDs.
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Interview functionality ==============

    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        Check whether the simulation environment is alive (able to receive Interview commands).

        Args:
            simulation_id: Simulation ID

        Returns:
            True if the environment is alive, False if it has been shut down
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Get detailed status information for the simulation environment.

        Args:
            simulation_id: Simulation ID

        Returns:
            Status detail dictionary containing status, twitter_available, reddit_available, timestamp
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
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
        Interview a single Agent.

        Args:
            simulation_id: Simulation ID
            agent_id: Agent ID
            prompt: Interview question
            platform: Specify platform (optional)
                - "twitter": Interview only on the Twitter platform
                - "reddit": Interview only on the Reddit platform
                - None: In dual-platform mode, interview both platforms simultaneously and return merged results
            timeout: Timeout in seconds

        Returns:
            Interview result dictionary

        Raises:
            ValueError: Simulation does not exist or environment is not running
            TimeoutError: Timeout waiting for response
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or has been shut down; cannot execute Interview: {simulation_id}")

        logger.info(f"Sending Interview command: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

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
        Batch-interview multiple Agents.

        Args:
            simulation_id: Simulation ID
            interviews: List of interviews; each element contains {"agent_id": int, "prompt": str, "platform": str (optional)}
            platform: Default platform (optional; overridden by each interview item's platform)
                - "twitter": Interview only on the Twitter platform by default
                - "reddit": Interview only on the Reddit platform by default
                - None: In dual-platform mode, each Agent is interviewed on both platforms simultaneously
            timeout: Timeout in seconds

        Returns:
            Batch interview result dictionary

        Raises:
            ValueError: Simulation does not exist or environment is not running
            TimeoutError: Timeout waiting for response
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or has been shut down; cannot execute Interview: {simulation_id}")

        logger.info(f"Sending batch Interview command: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

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
        Interview all agents (global interview)

        Interview all agents in the simulation with the same question

        Args:
            simulation_id: Simulation ID
            prompt: interview question shared by all agents
            platform: specified platform, optional
                - "twitter": interview only Twitter platform
                - "reddit": interview only Reddit platform
                - None: in dual-platform simulation, interview each agent on both platforms
            timeout: timeout in seconds

        Returns:
            global interview result dictionary
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        # Get all agent information from config
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"Simulation config does not exist: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"Simulation config contains no agents: {simulation_id}")

        # Build batch interview list
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"Sending global Interview command: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

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
        Close the simulation environment instead of stopping the process
        
        Send a close-environment command so the simulation exits command-wait mode gracefully
        
        Args:
            simulation_id: Simulation ID
            timeout: timeout in seconds
            
        Returns:
            operation result dictionary
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": "Environment is already closed"
            }
        
        logger.info(f"Sending close-environment command: simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "Environment close command sent",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # Timeout may occur because the environment is closing
            return {
                "success": True,
                "message": "Environment close command sent (response timed out; environment may be closing)"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get Interview history from one database"""
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
            logger.error(f"Failed to read Interview history ({platform_name}): {e}")
        
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
        Get Interview history records from database
        
        Args:
            simulation_id: Simulation ID
            platform: platform type (reddit/twitter/None)
                - "reddit": get only Reddit platform history
                - "twitter": get only Twitter platform history
                - None: get all history from both platforms
            agent_id: specified Agent ID, optional; get only that agent history
            limit: limit returned per platform
            
        Returns:
            Interview history list
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        results = []
        
        # Determine platforms to query
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # Query both platforms when platform is not specified
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
        
        # Sort by descending time
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Limit total count when querying multiple platforms
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results
