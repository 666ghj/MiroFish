"""
OASIS模拟运行器
在后台运行模拟并记录每个Agent的动作，支持实时状态监控
"""

import os
import sys
import importlib.util
import json
import time
import asyncio
import secrets
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
from ..utils.atomic_write import write_json_atomic
from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale
from ..utils.zep import (
    ZEP_HTTP_REQUEST_TIMEOUT_SECONDS,
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
)
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# 标记是否已注册清理函数
_cleanup_registered = False

# 平台检测
IS_WINDOWS = sys.platform == 'win32'

# actions.jsonl 中不属于 Agent 行为的记录：运行开始时播种的关注图（"setup"）
# 和结束时的最终问卷访谈（"poll"）。它们不计入动作数、时间线、Agent 统计，
# 也不会写入 Zep 记忆。定时事件（"injected"）是正常的发帖动作，照常计入。
NON_BEHAVIOR_PHASES = frozenset({"setup", "poll"})

# Health of the model calls is judged on this many of the latest rounds per platform
HEALTH_WINDOW_ROUNDS = 3
HEALTH_RANK = {"ok": 0, "warning": 1, "error": 2}


class RunnerStatus(str, Enum):
    """运行器状态"""
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
    """Agent动作记录"""
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
    """每轮摘要"""
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
    """模拟运行状态（实时）"""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE
    
    # 进度信息
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0
    
    # 各平台独立轮次和模拟时间（用于双平台并行显示）
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0
    
    # 平台状态
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    
    # 平台完成状态（通过检测 actions.jsonl 中的 simulation_end 事件）
    twitter_completed: bool = False
    reddit_completed: bool = False
    
    # 每轮摘要
    rounds: List[RoundSummary] = field(default_factory=list)
    
    # 最近动作（用于前端实时展示）
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50
    
    # 时间戳
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    # 错误信息
    error: Optional[str] = None
    
    # 进程ID（用于停止）
    process_pid: Optional[int] = None

    # 随机种子（让调度可复现：激活、响应延迟、关注图、定时事件；不保证LLM输出一致）
    seed: Optional[int] = None

    # Live view of each platform, from the round_start / agent_error / round_end events:
    # {"twitter": {"round": 12, "woken": 6, "failed": 2, "acted": None, "state": "running" | "done"}}
    activity: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Model-call failures seen so far: {"total", "kinds": {kind: n}, "last": {...}, "recent": {platform: [[woken, failed], ...]}}
    failures: Dict[str, Any] = field(default_factory=dict)
    # Progress of the end-of-run poll (ensemble replicates), from the poll_status events
    poll: Optional[Dict[str, Any]] = None

    # Set when the run was continued from the end of an earlier round ("Resume"): the round it continued
    # after (the smaller of the two platforms'), how many times that happened, and whether the platform
    # databases were restored from an exact end-of-round checkpoint.
    resumed_from_round: Optional[int] = None
    resume_count: int = 0
    resume_exact: Optional[bool] = None

    # Which platforms the run was started with: "parallel" (both), "twitter" or "reddit". Every run, single-platform
    # ones included, uses run_parallel_simulation.py (with --twitter-only / --reddit-only), so every run writes the
    # structured action log that completion detection, the status line and Resume depend on.
    platform: str = "parallel"

    @property
    def platforms(self) -> tuple:
        """The platforms this run covers."""
        return (self.platform,) if self.platform in ("twitter", "reddit") else ("twitter", "reddit")

    # --- activity and failures --------------------------------------------------------------

    def _recent_rounds(self, platform: str) -> List[List[int]]:
        recent = self.failures.setdefault("recent", {})
        return recent.setdefault(platform, [])

    def note_round_start(self, platform: str, round_num: int, woken: Optional[int]):
        self.activity[platform] = {
            "round": round_num, "woken": woken, "failed": 0, "acted": None, "state": "running",
        }
        rounds = self._recent_rounds(platform)
        rounds.append([woken or 0, 0])
        del rounds[:-HEALTH_WINDOW_ROUNDS]

    def note_agent_error(self, platform: str, round_num: int, agent_id: Any, kind: str, message: str, timestamp: Optional[str]):
        current = self.activity.get(platform)
        if current is None or current.get("round") != round_num:
            current = self.activity[platform] = {
                "round": round_num, "woken": None, "failed": 0, "acted": None, "state": "running",
            }
            self._recent_rounds(platform).append([0, 0])
        current["failed"] = current.get("failed", 0) + 1
        rounds = self._recent_rounds(platform)
        if rounds:
            rounds[-1][1] += 1
        self.failures["total"] = self.failures.get("total", 0) + 1
        kinds = self.failures.setdefault("kinds", {})
        kinds[kind] = kinds.get(kind, 0) + 1
        self.failures["last"] = {
            "kind": kind, "message": message, "agent_id": agent_id,
            "round": round_num, "platform": platform, "timestamp": timestamp,
        }

    def note_round_end(self, platform: str, round_num: int, acted: Optional[int], failed: Optional[int]):
        current = self.activity.get(platform)
        if current is None or current.get("round") != round_num:
            current = self.activity[platform] = {
                "round": round_num, "woken": None, "failed": 0, "acted": None, "state": "running",
            }
        current["state"] = "done"
        current["acted"] = acted
        if failed is not None:
            current["failed"] = failed
            rounds = self._recent_rounds(platform)
            if rounds:
                rounds[-1][1] = failed  # the round's own count is the authoritative one

    def note_poll_status(self, event: Dict[str, Any]):
        keys = ("state", "answered", "total", "attempt", "max_attempts", "retry_in", "error_kind", "message", "timestamp")
        self.poll = {key: event.get(key) for key in keys}

    def health(self) -> Dict[str, Any]:
        """Is the model answering? ``level`` is ok / warning / error, judged on the last few rounds (so the
        warning goes away once the provider recovers) and on the end-of-run poll."""
        recent = self.failures.get("recent", {})
        woken = sum(w for rounds in recent.values() for w, _ in rounds)
        failed = sum(f for rounds in recent.values() for _, f in rounds)
        level = "ok"
        if failed >= 3 and failed >= 0.5 * woken:
            level = "error"
        elif failed >= 2 and failed >= 0.2 * woken:
            level = "warning"
        last = self.failures.get("last") or {}
        kind = last.get("kind") if level != "ok" else None
        message = last.get("message") if level != "ok" else None
        source = "rounds" if level != "ok" else None

        # The end-of-run poll counts too: agents that could not answer, and why. It is the later event, so
        # at equal severity it wins.
        poll = self.poll or {}
        if poll.get("error_kind") and (poll.get("total") or 0) > (poll.get("answered") or 0):
            poll_level = "error" if not poll.get("answered") else "warning"
            if HEALTH_RANK[poll_level] >= HEALTH_RANK[level]:
                level = poll_level
                kind, message, source = poll["error_kind"], poll.get("message"), "poll"

        return {
            "level": level,
            "kind": kind,
            "message": message,
            "source": source,
            "recent_woken": woken,
            "recent_failed": failed,
            "total_failed": self.failures.get("total", 0),
        }

    def add_action(self, action: AgentAction):
        """添加动作到最近动作列表"""
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
            # 各平台独立轮次和时间
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
            "seed": self.seed,
            "activity": self.activity,
            "failures": self.failures,
            "poll": self.poll,
            "health": self.health(),
            "resumed_from_round": self.resumed_from_round,
            "resume_count": self.resume_count,
            "resume_exact": self.resume_exact,
            "platform": self.platform,
        }

    def to_detail_dict(self) -> Dict[str, Any]:
        """包含最近动作的详细信息"""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    模拟运行器
    
    负责：
    1. 在后台进程中运行OASIS模拟
    2. 解析运行日志，记录每个Agent的动作
    3. 提供实时状态查询接口
    4. 支持暂停/停止/恢复操作
    """
    
    # 运行状态存储目录
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )
    
    # 脚本目录
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )
    
    # 内存中的运行状态
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # 存储 stdout 文件句柄
    _stderr_files: Dict[str, Any] = {}  # 存储 stderr 文件句柄
    
    # 图谱记忆更新配置
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    _finalization_locks: Dict[str, threading.Lock] = {}
    _finalization_locks_guard = threading.Lock()
    _manual_stop_requests: set[str] = set()
    # simulation_id -> {platform: byte position in actions.jsonl} the monitor starts from after a resume
    _resume_positions: Dict[str, Dict[str, int]] = {}

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
                "同步模拟状态失败: simulation_id=%s, status=%s, error=%s",
                simulation_id,
                runner_status.value,
                sync_error,
            )
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """获取运行状态"""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]
        
        # 尝试从文件加载
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """从文件加载运行状态"""
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
                # 各平台独立轮次和时间
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
                seed=data.get("seed"),
                activity=data.get("activity") or {},
                failures=data.get("failures") or {},
                poll=data.get("poll"),
                resumed_from_round=data.get("resumed_from_round"),
                resume_count=data.get("resume_count") or 0,
                resume_exact=data.get("resume_exact"),
                platform=data.get("platform") or "parallel",
            )

            # 加载最近动作
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
            logger.error(f"加载运行状态失败: {str(e)}")
            return None
    
    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """保存运行状态到文件"""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        # Written in one step: the monitor saves every 2 s, and a reader that opens the file
        # in between must never see it empty or half written.
        try:
            write_json_atomic(state_file, data)
        except OSError as error:
            # Windows refuses the rename while a reader (the UI poll, a script) has the file open at that
            # very moment, and the retries ran out. This save is not worth failing the run for: write in
            # place like before (a reader may then catch it half written once) and carry on.
            logger.warning(f"原子写入 run_state.json 失败，改为直接写入: {error}")
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state

    @classmethod
    def _write_run_block(
        cls,
        config_path: str,
        config: Dict[str, Any],
        seed: int,
        max_rounds: Optional[int],
    ) -> None:
        """Record this run's seed (and round cap) in the config's ``run`` block.

        Other run settings already in the block (``replicate_index``,
        ``ensemble_id``, ``llm_temperature``, ``outcome_questions`` ...) are
        preserved. The file is replaced atomically so readers never see a
        half-written config.
        """
        run = dict(config.get("run") or {})
        run["seed"] = seed
        run.setdefault("replicate_index", None)
        run.setdefault("ensemble_id", None)
        if max_rounds is not None and max_rounds > 0:
            run["max_rounds"] = max_rounds
        else:
            run.pop("max_rounds", None)
        config["run"] = run
        write_json_atomic(config_path, config)

    # --- resume ---------------------------------------------------------------------------------

    RESUME_PLATFORMS = ("twitter", "reddit")  # a parallel run; single-platform runs use state.platforms

    @classmethod
    def _sim_resume(cls):
        """The ``sim_resume`` helper module that lives next to the run scripts (same one the script uses)."""
        module = sys.modules.get("sim_resume")
        if module is None:
            spec = importlib.util.spec_from_file_location("sim_resume", os.path.join(cls.SCRIPTS_DIR, "sim_resume.py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules["sim_resume"] = module
            spec.loader.exec_module(module)
        return module

    @classmethod
    def resume_info(cls, simulation_id: str) -> Dict[str, Any]:
        """Whether a stopped or interrupted run can continue after its last finished round, and from where.

        ``{"resumable", "reason", "round", "rounds": {platform: n}, "total_rounds", "exact"}``. ``round`` is
        the last round every platform finished; ``exact`` is True when each platform database can be put back
        exactly as it was at the end of that round (otherwise the unfinished round's earlier actions stay in
        it). Never raises and never changes anything.
        """
        info: Dict[str, Any] = {
            "resumable": False, "reason": None, "round": None, "rounds": {}, "total_rounds": None, "exact": None,
        }
        state = cls.get_run_state(simulation_id)
        if state is None or state.runner_status == RunnerStatus.IDLE:
            info["reason"] = "this simulation has not been run yet"
            return info
        info["total_rounds"] = state.total_rounds
        if state.runner_status == RunnerStatus.COMPLETED:
            info["reason"] = "the run is already complete"
            return info
        if cls.has_live_process(simulation_id):
            info["reason"] = "the run is still running"
            return info
        if ZepGraphMemoryManager.get_updater(simulation_id) is not None:
            info["reason"] = "the run is still finishing"
            return info
        if state.seed is None:
            info["reason"] = "the run's seed was not recorded, so its scheduling cannot be replayed"
            return info

        helper = cls._sim_resume()
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        plans = {platform: helper.plan_resume(sim_dir, platform) for platform in state.platforms}
        blocked = [plan for plan in plans.values() if not plan.resumable]
        if blocked:
            info["reason"] = "; ".join(f"{plan.platform}: {plan.reason}" for plan in blocked)
            return info

        info["rounds"] = {platform: plan.round for platform, plan in plans.items()}
        info["round"] = min(plan.round for plan in plans.values())
        info["exact"] = all(plan.exact for plan in plans.values())
        info["resumable"] = True
        return info

    @classmethod
    def _prepare_resume(cls, simulation_id: str, state: SimulationRunState) -> Dict[str, int]:
        """Put logs and databases back at the end of the last finished round and load the log into ``state``.

        The caller holds the finalization lock and has verified the run is not active. Returns the byte
        position of each action log so the monitor continues after what was already loaded.
        """
        helper = cls._sim_resume()
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        plans = {platform: helper.plan_resume(sim_dir, platform) for platform in state.platforms}
        for platform, plan in plans.items():
            if not plan.resumable:
                raise ValueError(f"cannot resume {platform}: {plan.reason}")

        positions: Dict[str, int] = {}
        for platform, plan in plans.items():
            log_path = os.path.join(sim_dir, platform, "actions.jsonl")
            helper.truncate_log(log_path, plan.offset)
            if plan.exact:
                helper.restore_checkpoint(os.path.join(sim_dir, f"{platform}_simulation.db"))

        # Rebuild the counters from the kept log. Nothing of it may reach the Zep graph again.
        cls._graph_memory_enabled[simulation_id] = False
        for platform in plans:
            positions[platform] = cls._read_action_log(
                os.path.join(sim_dir, platform, "actions.jsonl"), 0, state, platform
            )

        state.resumed_from_round = min(plan.round for plan in plans.values())
        state.resume_exact = all(plan.exact for plan in plans.values())
        logger.info(
            f"继续模拟: {simulation_id}, 各平台继续位置 { {p: plan.round for p, plan in plans.items()} }, "
            f"exact={state.resume_exact}"
        )
        return positions

    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # 最大模拟轮数（可选，用于截断过长的模拟）
        enable_graph_memory_update: bool = False,  # 是否将活动更新到Zep图谱
        graph_id: str = None,  # Zep图谱ID（启用图谱更新时必需）
        seed: Optional[int] = None,  # 随机种子（缺省时随机生成并持久化）
        wait_for_commands: bool = True,  # False 时传 --no-wait：跑完立即退出，释放资源
        resume: bool = False,  # True：从上次完成的一轮之后继续（保留数据库与日志），而不是重新开始
    ) -> SimulationRunState:
        """
        启动模拟

        Args:
            simulation_id: 模拟ID
            platform: 运行平台 (twitter/reddit/parallel)
            max_rounds: 最大模拟轮数（可选，用于截断过长的模拟）
            enable_graph_memory_update: 是否将Agent活动动态更新到Zep图谱
            graph_id: Zep图谱ID（启用图谱更新时必需）
            seed: 随机种子。让"调度"可复现（谁在何时被激活、响应延迟、初始关注图、
                定时事件），但不保证LLM输出逐字一致。缺省时随机生成，并写入
                run_state.json 与配置文件的 run 块。
            wait_for_commands: 模拟结束后是否保持环境运行以接受 Interview 命令。
                False 时进程跑完即退出（集成测试/集合运行使用）。
            resume: 继续一个已停止/中断的运行：保留平台数据库与动作日志，日志截断到最后完成
                的一轮，从下一轮继续（沿用原来的种子与轮数）。Agent 的对话记忆无法恢复，
                所以结果与不中断的运行不完全相同。见 resume_info()。

        Returns:
            SimulationRunState
        """
        previous = None
        if resume:
            info = cls.resume_info(simulation_id)
            if not info["resumable"]:
                raise ValueError(f"无法继续: {info['reason']}")
            previous = cls.get_run_state(simulation_id)
            platform = previous.platform  # a resumed run covers the platforms it started with
            # The scheduling replay is only valid with the run's own seed and round limit.
            seed = previous.seed
            if previous.total_rounds and previous.total_rounds > 0:
                max_rounds = previous.total_rounds
        if seed is None:
            seed = secrets.randbelow(2 ** 31)
        else:
            seed = int(seed)
        # 加载模拟配置
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            raise ValueError(f"模拟配置不存在，请先调用 /prepare 接口")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 初始化运行状态
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # 如果指定了最大轮数，则截断
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"轮数已截断: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=(previous.started_at if previous and previous.started_at else datetime.now().isoformat()),
            seed=seed,
            platform=platform if platform in ("twitter", "reddit") else "parallel",
        )
        if previous is not None:
            state.resume_count = (previous.resume_count or 0) + 1

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
                (
                    existing and existing.runner_status in active_statuses
                    # A resumed run's old state may still say RUNNING when the process is long gone.
                    and (not resume or cls.has_live_process(simulation_id))
                )
                or ZepGraphMemoryManager.get_updater(simulation_id) is not None
                # A COMPLETED run may still own a live interview environment.
                or cls.has_live_process(simulation_id)
            ):
                raise ValueError(f"模拟已在运行或结束处理中: {simulation_id}")
            resume_positions = cls._prepare_resume(simulation_id, state) if resume else None
            if resume_positions is not None:
                cls._resume_positions[simulation_id] = resume_positions
            cls._save_run_state(state)
            # A previous run's "alive" marker must not make this run look like
            # it is already parked in command-wait mode.
            try:
                os.remove(os.path.join(sim_dir, "env_status.json"))
            except FileNotFoundError:
                pass
            except OSError as error:
                logger.warning(f"清理旧的环境状态文件失败: {simulation_id}, error={error}")

        # 如果启用图谱记忆更新，创建更新器
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("启用图谱记忆更新时必须提供 graph_id")
            
            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"已启用图谱记忆更新: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"创建图谱记忆更新器失败: {e}")
                cls._graph_memory_enabled[simulation_id] = False
                state.runner_status = RunnerStatus.FAILED
                state.error = f"Zep图谱更新器初始化失败: {e}"
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
        
        # 确定运行哪个脚本（脚本位于 backend/scripts/ 目录）
        # Always the parallel script: the standalone run_twitter/run_reddit scripts write no structured
        # action log (no round events, checkpoints, failure tracking, final poll), so a run started with
        # them could never be seen to finish. The parallel script runs one platform with --twitter-only
        # or --reddit-only.
        script_name = "run_parallel_simulation.py"
        state.twitter_running = "twitter" in state.platforms
        state.reddit_running = "reddit" in state.platforms
        
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
            state.error = f"脚本不存在: {script_path}"
            if cleanup_error is not None:
                state.error += f"; Zep图谱写入清理失败: {cleanup_error}"
            with cls._finalization_lock(simulation_id):
                cls._save_run_state(state)
                cls._sync_simulation_status(
                    simulation_id,
                    RunnerStatus.FAILED,
                    state.error,
                )
            raise ValueError(state.error)
        
        # 创建动作队列
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue

        process = None
        main_log_file = None

        # 启动模拟进程
        try:
            # 构建运行命令，使用完整路径
            # 新的日志结构：
            #   twitter/actions.jsonl - Twitter 动作日志
            #   reddit/actions.jsonl  - Reddit 动作日志
            #   simulation.log        - 主进程日志
            
            # 把种子写进配置快照（run 块），脚本也通过 --seed 收到同一个值
            cls._write_run_block(config_path, config, seed, max_rounds)

            cmd = [
                sys.executable,  # Python解释器
                script_path,
                "--config", config_path,  # 使用完整配置文件路径
                "--seed", str(seed),
            ]

            # 如果指定了最大轮数，添加到命令行参数
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])

            # 不等待命令：脚本跑完就退出（监控线程据此发布 COMPLETED）
            if not wait_for_commands:
                cmd.append("--no-wait")

            if state.platform == "twitter":
                cmd.append("--twitter-only")
            elif state.platform == "reddit":
                cmd.append("--reddit-only")

            if resume:
                cmd.append("--resume")
            
            # 创建主日志文件，避免 stdout/stderr 管道缓冲区满导致进程阻塞
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'a' if resume else 'w', encoding='utf-8')
            if resume:
                main_log_file.write(
                    f"\n{'=' * 60}\n继续模拟 {datetime.now().isoformat()}: "
                    f"从第 {state.resumed_from_round} 轮之后继续\n{'=' * 60}\n"
                )
                main_log_file.flush()
            
            # 设置子进程环境变量，确保 Windows 上使用 UTF-8 编码
            # 这可以修复第三方库（如 OASIS）读取文件时未指定编码的问题
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+ 支持，让所有 open() 默认使用 UTF-8
            env['PYTHONIOENCODING'] = 'utf-8'  # 确保 stdout/stderr 使用 UTF-8
            
            # 设置工作目录为模拟目录（数据库等文件会生成在此）
            # 使用 start_new_session=True 创建新的进程组，确保可以通过 os.killpg 终止所有子进程
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # stderr 也写入同一个文件
                text=True,
                encoding='utf-8',  # 显式指定编码
                bufsize=1,
                env=env,  # 传递带有 UTF-8 设置的环境变量
                start_new_session=True,  # 创建新进程组，确保服务器关闭时能终止所有相关进程
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
            
            logger.info(f"模拟启动成功: {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            cleanup_errors = []
            if process is not None and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except Exception as error:
                    cleanup_errors.append(f"子进程终止失败: {error}")
            cls._processes.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._stdout_files.pop(simulation_id, None)
            cls._stderr_files.pop(simulation_id, None)
            if main_log_file is not None:
                try:
                    main_log_file.close()
                except Exception as error:
                    cleanup_errors.append(f"日志关闭失败: {error}")
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    cls._graph_memory_enabled.pop(simulation_id, None)
                except Exception as error:
                    cleanup_errors.append(f"Zep图谱写入清理失败: {error}")
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
        """监控模拟进程，解析动作日志"""
        set_locale(locale)
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        # 新的日志结构：分平台的动作日志
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        resumed_positions = cls._resume_positions.pop(simulation_id, None) or {}
        twitter_position = resumed_positions.get("twitter", 0)
        reddit_position = resumed_positions.get("reddit", 0)
        
        monitor_error: Exception | None = None
        exit_code: int | None = None
        # True once the run was published as COMPLETED while the script was
        # still parked in command-wait mode (kept alive for interviews).
        published_while_idle = False
        try:
            while process.poll() is None:  # 进程仍在运行
                # 读取 Twitter 动作日志
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )

                # 读取 Reddit 动作日志
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )

                # 更新状态
                cls._save_run_state(state)

                # The script deliberately stays alive after the last round so
                # agents can be interviewed. Waiting for it to exit would keep
                # the run RUNNING forever and block the report stage.
                if not published_while_idle and cls._is_idle_in_command_wait(state):
                    published_while_idle = cls._publish_completion_while_idle(
                        simulation_id
                    )
                time.sleep(2)
            
            # 进程结束后，最后读取一次日志
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")
            
            exit_code = process.returncode
            
        except Exception as e:
            logger.error(f"监控线程异常: {simulation_id}, error={str(e)}")
            monitor_error = e
        
        finally:
            # Manual stop and natural completion can observe the same process
            # exit. Serialize terminal state and updater drain so only one path
            # owns the final result.
            with cls._finalization_lock(simulation_id):
                latest_state = cls.get_run_state(simulation_id)
                if latest_state is not None:
                    state = latest_state

                already_published = (
                    published_while_idle
                    and state.runner_status == RunnerStatus.COMPLETED
                )
                if not already_published and state.runner_status not in {
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
                            f"进程退出码: {exit_code}, 错误: {error_info}"
                        )

                    cls._publish_terminal_state(
                        simulation_id, state, desired_status, error_message
                    )
                cls._manual_stop_requests.discard(simulation_id)
            
            # 清理进程资源
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            cls._monitor_threads.pop(simulation_id, None)
            
            # 关闭日志文件句柄
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
    def _publish_terminal_state(
        cls,
        simulation_id: str,
        state: SimulationRunState,
        desired_status: RunnerStatus,
        error_message: Optional[str],
    ) -> None:
        """Drain Zep ingestion, then publish the run's terminal status.

        The caller must hold the simulation's finalization lock.
        """
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
                    "已停止图谱记忆更新: simulation_id=%s",
                    simulation_id,
                )
            except Exception as error:
                logger.error(f"停止图谱记忆更新器失败: {error}")
                desired_status = RunnerStatus.FAILED
                error_message = f"Zep图谱写入未完整完成: {error}"

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
            logger.info(f"模拟完成: {simulation_id}")
        else:
            logger.error(f"模拟失败: {simulation_id}, error={state.error}")

    @classmethod
    def _is_idle_in_command_wait(cls, state: SimulationRunState) -> bool:
        """Whether the script finished every round and is parked waiting for
        interview / close_env commands.

        Nothing more will be produced at that point, but the process will not
        exit on its own, so process exit cannot be the completion signal.
        """
        if state.runner_status != RunnerStatus.RUNNING:
            return False
        if state.twitter_running or state.reddit_running:
            return False
        return (
            cls._check_all_platforms_completed(state)
            and cls.check_env_alive(state.simulation_id)
        )

    @classmethod
    def _publish_completion_while_idle(cls, simulation_id: str) -> bool:
        """Publish the run's result while its environment stays alive.

        The process is deliberately left running so agents can still be
        interviewed (including by the report agent). Returns False when a stop
        request or another finalizer owns the outcome instead.
        """
        with cls._finalization_lock(simulation_id):
            state = cls.get_run_state(simulation_id)
            if (
                state is None
                or state.runner_status != RunnerStatus.RUNNING
                or simulation_id in cls._manual_stop_requests
            ):
                return False
            logger.info(
                f"所有平台已结束，环境进入等待命令模式，发布完成状态: {simulation_id}"
            )
            cls._publish_terminal_state(
                simulation_id, state, RunnerStatus.COMPLETED, None
            )
            return True

    @classmethod
    def has_live_process(cls, simulation_id: str) -> bool:
        """Whether this simulation's script process is still running."""
        process = cls._processes.get(simulation_id)
        return process is not None and process.poll() is None

    @classmethod
    def _read_action_log(
        cls, 
        log_path: str, 
        position: int, 
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        读取动作日志文件
        
        Args:
            log_path: 日志文件路径
            position: 上次读取位置
            state: 运行状态对象
            platform: 平台名称 (twitter/reddit)
            
        Returns:
            新的读取位置
        """
        # 检查是否启用了图谱记忆更新
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = ZepGraphMemoryManager.get_updater(state.simulation_id)
        
        try:
            # Binary mode so the position is an exact byte offset and a line
            # the script is still writing (no newline yet) can be left for the
            # next poll instead of being parsed half-way and lost.
            with open(log_path, 'rb') as f:
                f.seek(position)
                for raw_line in f:
                    if not raw_line.endswith(b"\n"):
                        break
                    position += len(raw_line)
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if line:
                        try:
                            action_data = json.loads(line)
                            
                            # 处理事件类型的条目
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")
                                
                                # 检测 simulation_end 事件，标记平台已完成
                                if event_type == "simulation_end":
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter 模拟已完成: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit 模拟已完成: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    
                                    # 检查是否所有启用的平台都已完成
                                    # 如果只运行了一个平台，只检查那个平台
                                    # 如果运行了两个平台，需要两个都完成
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        # Platform completion is only an input
                                        # signal. The monitor publishes the
                                        # terminal status after the process has
                                        # exited and Zep ingestion has drained.
                                        logger.info(
                                            f"所有平台已结束，等待进程与图谱写入完成: "
                                            f"{state.simulation_id}"
                                        )
                                
                                # 本轮开始：唤醒了多少个Agent
                                elif event_type == "round_start":
                                    active_ids = action_data.get("active_agent_ids")
                                    state.note_round_start(
                                        platform,
                                        action_data.get("round", 0),
                                        len(active_ids) if isinstance(active_ids, list) else None,
                                    )

                                # 某个Agent的模型调用失败（OASIS 会吞掉这类错误）
                                elif event_type == "agent_error":
                                    state.note_agent_error(
                                        platform,
                                        action_data.get("round", 0),
                                        action_data.get("agent_id"),
                                        str(action_data.get("error_kind") or "other"),
                                        str(action_data.get("message") or ""),
                                        action_data.get("timestamp"),
                                    )

                                # 最终问卷进度
                                elif event_type == "poll_status":
                                    state.note_poll_status(action_data)

                                # 更新轮次信息（从 round_end 事件）
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)
                                    state.note_round_end(
                                        platform, round_num,
                                        action_data.get("actions_count"), action_data.get("failed_count"),
                                    )

                                    # 更新各平台独立的轮次和时间
                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours
                                    
                                    # 总体轮次取两个平台的最大值
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    # 总体时间取两个平台的最大值
                                    state.simulated_hours = max(state.twitter_simulated_hours, state.reddit_simulated_hours)
                                
                                continue

                            # 播种的关注图 / 最终问卷不是 Agent 行为
                            if action_data.get("phase") in NON_BEHAVIOR_PHASES:
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
                            
                            # 更新轮次
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num
                            
                            # 如果启用了图谱记忆更新，将活动发送到Zep
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return position
        except Exception as e:
            logger.warning(f"读取动作日志失败: {log_path}, error={e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        检查所有启用的平台是否都已完成模拟
        
        通过检查对应的 actions.jsonl 文件是否存在来判断平台是否被启用
        
        Returns:
            True 如果所有启用的平台都已完成
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        # 检查哪些平台被启用（通过文件是否存在判断）。单平台运行只看它自己的平台：
        # 上一次双平台运行遗留的另一个平台的日志不能让这次运行永远"未完成"。
        twitter_enabled = os.path.exists(twitter_log) and "twitter" in state.platforms
        reddit_enabled = os.path.exists(reddit_log) and "reddit" in state.platforms
        
        # 如果平台被启用但未完成，则返回 False
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False
        
        # 至少有一个平台被启用且已完成
        return twitter_enabled or reddit_enabled
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        跨平台终止进程及其子进程
        
        Args:
            process: 要终止的进程
            simulation_id: 模拟ID（用于日志）
            timeout: 等待进程退出的超时时间（秒）
        """
        if IS_WINDOWS:
            # Windows: 使用 taskkill 命令终止进程树
            # /F = 强制终止, /T = 终止进程树（包括子进程）
            logger.info(f"终止进程树 (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # 先尝试优雅终止
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # 强制终止
                    logger.warning(f"进程未响应，强制终止: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill 失败，尝试 terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: 使用进程组终止
            # 由于使用了 start_new_session=True，进程组 ID 等于主进程 PID
            pgid = os.getpgid(process.pid)
            logger.info(f"终止进程组 (Unix): simulation={simulation_id}, pgid={pgid}")
            
            # 先发送 SIGTERM 给整个进程组
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # 如果超时后还没结束，强制发送 SIGKILL
                logger.warning(f"进程组未响应 SIGTERM，强制终止: {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)
    
    @classmethod
    def _close_idle_environment(
        cls, simulation_id: str
    ) -> Optional[SimulationRunState]:
        """Terminate the interview environment of an already-COMPLETED run.

        The run published its result when the last round finished; only the
        process kept alive for interviews is left. It is closed without
        rewriting that result. Returns the COMPLETED state, or None when this
        is not an idle-environment teardown (the regular stop flow applies).
        """
        with cls._finalization_lock(simulation_id):
            state = cls.get_run_state(simulation_id)
            if (
                state is None
                or state.runner_status != RunnerStatus.COMPLETED
                or ZepGraphMemoryManager.get_updater(simulation_id) is not None
                or not cls.has_live_process(simulation_id)
            ):
                return None

            process = cls._processes[simulation_id]
            try:
                cls._terminate_process(process, simulation_id)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.error(f"终止进程组失败: {simulation_id}, error={e}")
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()

        # The monitor releases this run's process/log resources when it sees
        # the exit. Wait for that so an immediate restart cannot race with it.
        monitor = cls._monitor_threads.get(simulation_id)
        if (
            monitor is not None
            and monitor is not threading.current_thread()
            and monitor.is_alive()
        ):
            monitor.join(timeout=30.0)
            if monitor.is_alive():
                raise SimulationStopPending(
                    f"模拟环境仍在关闭中: {simulation_id}"
                )
        return cls.get_run_state(simulation_id) or state

    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """停止模拟"""
        closed = cls._close_idle_environment(simulation_id)
        if closed is not None:
            return closed

        with cls._finalization_lock(simulation_id):
            state = cls.get_run_state(simulation_id)
            if not state:
                raise ValueError(f"模拟不存在: {simulation_id}")
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
                    f"模拟未在运行: {simulation_id}, status={state.runner_status}"
                )

            state.runner_status = RunnerStatus.STOPPING
            cls._manual_stop_requests.add(simulation_id)
            cls._save_run_state(state)
            cls._sync_simulation_status(simulation_id, RunnerStatus.STOPPING)

            # 终止进程
            process = cls._processes.get(simulation_id)
            if process and process.poll() is None:
                try:
                    cls._terminate_process(process, simulation_id)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.error(f"终止进程组失败: {simulation_id}, error={e}")
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
                    f"模拟仍在停止中，图谱写入未在 {wait_timeout:.0f}s 内完成"
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
                        state.error = f"Zep图谱写入未完整完成: {error}"
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
            raise RuntimeError(state.error or "模拟停止失败")
        if state.runner_status != RunnerStatus.STOPPED:
            raise RuntimeError(
                f"模拟停止未达到终态: {simulation_id}, status={state.runner_status}"
            )

        logger.info(f"模拟已停止: {simulation_id}")
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
        从单个动作文件中读取动作
        
        Args:
            file_path: 动作日志文件路径
            default_platform: 默认平台（当动作记录中没有 platform 字段时使用）
            platform_filter: 过滤平台
            agent_id: 过滤 Agent ID
            round_num: 过滤轮次
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
                    
                    # 跳过非动作记录（如 simulation_start, round_start, round_end 等事件）
                    if "event_type" in data:
                        continue
                    
                    # 跳过没有 agent_id 的记录（非 Agent 动作）
                    if "agent_id" not in data:
                        continue

                    # 跳过播种的关注图 / 最终问卷记录
                    if data.get("phase") in NON_BEHAVIOR_PHASES:
                        continue

                    # 获取平台：优先使用记录中的 platform，否则使用默认平台
                    record_platform = data.get("platform") or default_platform or ""
                    
                    # 过滤
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
        获取所有平台的完整动作历史（无分页限制）
        
        Args:
            simulation_id: 模拟ID
            platform: 过滤平台（twitter/reddit）
            agent_id: 过滤Agent
            round_num: 过滤轮次
            
        Returns:
            完整的动作列表（按时间戳排序，新的在前）
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []
        
        # 读取 Twitter 动作文件（根据文件路径自动设置 platform 为 twitter）
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",  # 自动填充 platform 字段
                platform_filter=platform,
                agent_id=agent_id, 
                round_num=round_num
            ))
        
        # 读取 Reddit 动作文件（根据文件路径自动设置 platform 为 reddit）
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",  # 自动填充 platform 字段
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))
        
        # 如果分平台文件不存在，尝试读取旧的单一文件格式
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # 旧格式文件中应该有 platform 字段
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )
        
        # 按时间戳排序（新的在前）
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
        获取动作历史（带分页）
        
        Args:
            simulation_id: 模拟ID
            limit: 返回数量限制
            offset: 偏移量
            platform: 过滤平台
            agent_id: 过滤Agent
            round_num: 过滤轮次
            
        Returns:
            动作列表
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # 分页
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        获取模拟时间线（按轮次汇总）
        
        Args:
            simulation_id: 模拟ID
            start_round: 起始轮次
            end_round: 结束轮次
            
        Returns:
            每轮的汇总信息
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        # 按轮次分组
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
        
        # 转换为列表
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
        获取每个Agent的统计信息
        
        Returns:
            Agent统计列表
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
        
        # 按总动作数排序
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        清理模拟的运行日志（用于强制重新开始模拟）
        
        会删除以下文件：
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - twitter_simulation.db（模拟数据库）
        - reddit_simulation.db（模拟数据库）
        - env_status.json（环境状态）
        - *_profiles.effective.*（v2 每次运行重新生成的 profile 副本）
        - final_poll.json（最终问卷结果）

        注意：不会删除配置文件（simulation_config.json）和 profile 文件
        
        Args:
            simulation_id: 模拟ID
            
        Returns:
            清理结果信息
        """
        import shutil
        
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "模拟目录不存在，无需清理"}
        
        cleaned_files = []
        errors = []
        
        # 要删除的文件列表（包括数据库文件）
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter 平台数据库
            "reddit_simulation.db",   # Reddit 平台数据库
            "twitter_simulation.db.ckpt",  # 每轮结束时的检查点（继续运行用）
            "reddit_simulation.db.ckpt",
            "env_status.json",        # 环境状态文件
            # 每次运行重新生成的衍生文件
            "twitter_profiles.effective.csv",   # 附加了行为指令的 profile 副本（v2）
            "reddit_profiles.effective.json",
            "final_poll.json",                  # 结束时的最终问卷结果
        ]
        
        # 要删除的目录列表（包含动作日志）
        dirs_to_clean = ["twitter", "reddit"]
        
        # 删除文件
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"删除 {filename} 失败: {str(e)}")
        
        # 清理平台目录中的动作日志
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"删除 {dir_name}/actions.jsonl 失败: {str(e)}")
        
        # 清理内存中的运行状态
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]
        
        logger.info(f"清理模拟日志完成: {simulation_id}, 删除文件: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # 防止重复清理的标志
    _cleanup_done = False
    
    @classmethod
    def cleanup_all_simulations(cls):
        """
        清理所有运行中的模拟进程
        
        在服务器关闭时调用，确保所有子进程被终止
        """
        # 防止重复清理
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

        logger.info("正在安全完成所有模拟进程与图谱写入...")
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
                    "清理模拟失败，保留状态以便重试: simulation_id=%s, error=%s",
                    simulation_id,
                    error,
                )

        if cleanup_failed:
            # Retained updaters and FAILED run states continue to block report
            # generation and graph deletion. Permit an explicit retry.
            cls._cleanup_done = False
            logger.error("部分模拟未安全完成清理")
        else:
            logger.info("模拟进程与图谱写入清理完成")
    
    @classmethod
    def register_cleanup(cls):
        """
        注册清理函数
        
        在 Flask 应用启动时调用，确保服务器关闭时清理所有模拟进程
        """
        global _cleanup_registered
        
        if _cleanup_registered:
            return
        
        # Flask debug 模式下，只在 reloader 子进程中注册清理（实际运行应用的进程）
        # WERKZEUG_RUN_MAIN=true 表示是 reloader 子进程
        # 如果不是 debug 模式，则没有这个环境变量，也需要注册
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        
        # 在 debug 模式下，只在 reloader 子进程中注册；非 debug 模式下始终注册
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # 标记已注册，防止子进程再次尝试
            return
        
        # 保存原有的信号处理器
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP 只在 Unix 系统存在（macOS/Linux），Windows 没有
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)
        
        def cleanup_handler(signum=None, frame=None):
            """信号处理器：先清理模拟进程，再调用原处理器"""
            # 只有在有进程需要清理时才打印日志
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"收到信号 {signum}，开始清理...")
            cls.cleanup_all_simulations()
            
            # 调用原有的信号处理器，让 Flask 正常退出
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP: 终端关闭时发送
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # 默认行为：正常退出
                    sys.exit(0)
            else:
                # 如果原处理器不可调用（如 SIG_DFL），则使用默认行为
                raise KeyboardInterrupt
        
        # 注册 atexit 处理器（作为备用）
        atexit.register(cls.cleanup_all_simulations)
        
        # 注册信号处理器（仅在主线程中）
        try:
            # SIGTERM: kill 命令默认信号
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: 终端关闭（仅 Unix 系统）
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # 不在主线程中，只能使用 atexit
            logger.warning("无法注册信号处理器（不在主线程），仅使用 atexit")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        获取所有正在运行的模拟ID列表
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Interview 功能 ==============
    
    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        检查模拟环境是否存活（可以接收Interview命令）

        Args:
            simulation_id: 模拟ID

        Returns:
            True 表示环境存活，False 表示环境已关闭
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        获取模拟环境的详细状态信息

        Args:
            simulation_id: 模拟ID

        Returns:
            状态详情字典，包含 status, twitter_available, reddit_available, timestamp
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
        采访单个Agent

        Args:
            simulation_id: 模拟ID
            agent_id: Agent ID
            prompt: 采访问题
            platform: 指定平台（可选）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None: 双平台模拟时同时采访两个平台，返回整合结果
            timeout: 超时时间（秒）

        Returns:
            采访结果字典

        Raises:
            ValueError: 模拟不存在或环境未运行
            TimeoutError: 等待响应超时
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"模拟不存在: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"模拟环境未运行或已关闭，无法执行Interview: {simulation_id}")

        logger.info(f"发送Interview命令: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

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
        批量采访多个Agent

        Args:
            simulation_id: 模拟ID
            interviews: 采访列表，每个元素包含 {"agent_id": int, "prompt": str, "platform": str(可选)}
            platform: 默认平台（可选，会被每个采访项的platform覆盖）
                - "twitter": 默认只采访Twitter平台
                - "reddit": 默认只采访Reddit平台
                - None: 双平台模拟时每个Agent同时采访两个平台
            timeout: 超时时间（秒）

        Returns:
            批量采访结果字典

        Raises:
            ValueError: 模拟不存在或环境未运行
            TimeoutError: 等待响应超时
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"模拟不存在: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"模拟环境未运行或已关闭，无法执行Interview: {simulation_id}")

        logger.info(f"发送批量Interview命令: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

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
        采访所有Agent（全局采访）

        使用相同的问题采访模拟中的所有Agent

        Args:
            simulation_id: 模拟ID
            prompt: 采访问题（所有Agent使用相同问题）
            platform: 指定平台（可选）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None: 双平台模拟时每个Agent同时采访两个平台
            timeout: 超时时间（秒）

        Returns:
            全局采访结果字典
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"模拟不存在: {simulation_id}")

        # 从配置文件获取所有Agent信息
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"模拟配置不存在: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"模拟配置中没有Agent: {simulation_id}")

        # 构建批量采访列表
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"发送全局Interview命令: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

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
        关闭模拟环境（而不是停止模拟进程）
        
        向模拟发送关闭环境命令，使其优雅退出等待命令模式
        
        Args:
            simulation_id: 模拟ID
            timeout: 超时时间（秒）
            
        Returns:
            操作结果字典
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": "环境已经关闭"
            }
        
        logger.info(f"发送关闭环境命令: simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "环境关闭命令已发送",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # 超时可能是因为环境正在关闭
            return {
                "success": True,
                "message": "环境关闭命令已发送（等待响应超时，环境可能正在关闭）"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """从单个数据库获取Interview历史"""
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
            logger.error(f"读取Interview历史失败 ({platform_name}): {e}")
        
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
        获取Interview历史记录（从数据库读取）
        
        Args:
            simulation_id: 模拟ID
            platform: 平台类型（reddit/twitter/None）
                - "reddit": 只获取Reddit平台的历史
                - "twitter": 只获取Twitter平台的历史
                - None: 获取两个平台的所有历史
            agent_id: 指定Agent ID（可选，只获取该Agent的历史）
            limit: 每个平台返回数量限制
            
        Returns:
            Interview历史记录列表
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        results = []
        
        # 确定要查询的平台
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # 不指定platform时，查询两个平台
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
        
        # 按时间降序排序
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # 如果查询了多个平台，限制总数
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results
