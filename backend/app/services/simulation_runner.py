"""
Trình chạy và giám sát Simulation OASIS

Vị trí trong pipeline:
─────────────────────────────────────────────────────────────────────────────
  simulation_manager.py  →  SimulationRunner.start_simulation()
      └─ subprocess.Popen(run_parallel_simulation.py --config ...)
              │  (OASIS chạy ngầm, ghi log ra actions.jsonl)
              │
      └─ Thread(_monitor_simulation)   [daemon thread, chạy song song với Flask]
              └─ _read_action_log()    [đọc actions.jsonl mỗi 2 giây]
              └─ _save_run_state()     [cập nhật run_state.json liên tục]
─────────────────────────────────────────────────────────────────────────────

Hai file state riêng biệt (KHÔNG phải một):
  state.json     — lifecycle state, quản lý bởi SimulationManager
                   (CREATED → PREPARING → READY → RUNNING → COMPLETED/FAILED)
  run_state.json — runtime progress, quản lý bởi SimulationRunner
                   (round hiện tại, action count, PID, ...)
                   Cập nhật mỗi 2 giây trong khi OASIS đang chạy.

Giao tiếp Flask ↔ OASIS subprocess:
  File-based:  Flask đọc actions.jsonl để biết tiến độ
  IPC:         Flask ghi lệnh vào ipc_commands/, OASIS trả lời vào ipc_responses/
               (dùng cho tính năng Interview agent đang chạy)
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
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# Cờ đánh dấu đã đăng ký hàm dọn dẹp (atexit) hay chưa — tránh đăng ký nhiều lần
_cleanup_registered = False

# Kiểm tra hệ điều hành — dùng để chọn cách kill process (killpg vs taskkill)
IS_WINDOWS = sys.platform == 'win32'


# ==============================================================================
# ENUM: RunnerStatus — Trạng thái của bộ chạy tiến trình (khác với SimulationStatus)
# ==============================================================================
# RunnerStatus theo dõi trạng thái của OASIS subprocess, không phải lifecycle tổng thể.
# Được lưu trong run_state.json — SimulationManager đọc file này để cập nhật state.json.
#
# Luồng trạng thái:
#   IDLE → STARTING → RUNNING → COMPLETED
#                  └──────────→ FAILED       (subprocess crash)
#   RUNNING → STOPPING → STOPPED             (người dùng stop)
# ==============================================================================

class RunnerStatus(str, Enum):
    """Trạng thái của bộ chạy tiến trình mô phỏng"""
    IDLE = "idle"           # Rảnh rỗi, chưa chạy
    STARTING = "starting"   # Đang khởi động subprocess
    RUNNING = "running"     # Subprocess đang chạy, agents đang hành động
    PAUSED = "paused"       # Đã tạm dừng (tính năng tương lai)
    STOPPING = "stopping"   # Đang gửi SIGTERM / taskkill
    STOPPED = "stopped"     # Đã dừng theo yêu cầu người dùng
    COMPLETED = "completed" # OASIS chạy hết số vòng và thoát thành công (exit_code=0)
    FAILED = "failed"       # Subprocess crash (exit_code != 0) hoặc exception không xử lý được


# ==============================================================================
# DATACLASS: AgentAction — Bản ghi một hành động đơn lẻ từ actions.jsonl
# ==============================================================================
# Mỗi dòng trong actions.jsonl tương ứng với 1 AgentAction.
# _read_action_log() parse từng dòng JSON thành AgentAction và lưu vào SimulationRunState.
#
# Ví dụ 1 dòng trong twitter/actions.jsonl:
#   {"round": 15, "agent_id": 3, "agent_name": "tran_van_an_492",
#    "action_type": "CREATE_POST", "action_args": {"content": "..."}, "success": true}
# ==============================================================================

@dataclass
class AgentAction:
    """Bản ghi hành động của Agent"""
    round_num: int        # Số thứ tự vòng (round) mô phỏng
    timestamp: str        # Dấu thời gian
    platform: str         # Nền tảng: "twitter" hoặc "reddit"
    agent_id: int         # ID của agent (khớp với user_id trong profile file)
    agent_name: str       # Tên tài khoản (ví dụ: "tran_van_an_492")
    action_type: str      # Loại hành động: CREATE_POST, LIKE_POST, REPOST, FOLLOW, DO_NOTHING...
    action_args: Dict[str, Any] = field(default_factory=dict)  # Tham số của hành động
    result: Optional[str] = None  # Kết quả thực thi (ví dụ: "Post created with id 142")
    success: bool = True  # Hành động có thành công hay không

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


# ==============================================================================
# DATACLASS: RoundSummary — Tóm tắt một vòng (round) mô phỏng
# ==============================================================================
# Được tổng hợp từ các AgentAction trong cùng round_num.
# Lưu vào SimulationRunState.rounds để hiển thị timeline trên frontend.
# ==============================================================================

@dataclass
class RoundSummary:
    """Tóm tắt thông tin của mỗi vòng (round)"""
    round_num: int                   # Số thứ tự vòng
    start_time: str                  # Thời gian bắt đầu vòng
    end_time: Optional[str] = None   # Thời gian kết thúc vòng
    simulated_hour: int = 0          # Giờ mô phỏng tương ứng (0–71 nếu total_hours=72)
    twitter_actions: int = 0         # Số hành động trên Twitter trong vòng này
    reddit_actions: int = 0          # Số hành động trên Reddit trong vòng này
    active_agents: List[int] = field(default_factory=list)   # Danh sách agent_id đã hành động
    actions: List[AgentAction] = field(default_factory=list) # Chi tiết các hành động

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


# ==============================================================================
# DATACLASS: SimulationRunState — Trạng thái runtime của OASIS subprocess
# ==============================================================================
# Đây là object lưu trạng thái "đang chạy" — được cập nhật mỗi 2 giây bởi monitor thread.
# Được ghi ra run_state.json để Frontend có thể poll API và hiển thị tiến độ.
#
# Phân biệt với SimulationState (state.json):
#   SimulationState  = lifecycle tổng thể (CREATED→READY→RUNNING→COMPLETED)
#   SimulationRunState = tiến độ chi tiết (round hiện tại, action count, PID, ...)
#
# recent_actions: chỉ giữ 50 hành động gần nhất (max_recent_actions)
# → Không lưu toàn bộ actions vào RAM để tránh tốn bộ nhớ với simulation dài.
# ==============================================================================

@dataclass
class SimulationRunState:
    """Trạng thái đang thực thi của tiến trình mô phỏng (cập nhật theo thời gian thực)"""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE

    # --- Tiến độ chung ---
    current_round: int = 0           # Vòng hiện tại (số lớn nhất của 2 platform)
    total_rounds: int = 0            # Tổng số vòng cần chạy
    simulated_hours: int = 0         # Số giờ đã mô phỏng
    total_simulation_hours: int = 0  # Tổng số giờ cần mô phỏng

    # --- Tiến độ riêng từng platform ---
    # Hai platform chạy song song asyncio → hoàn thành không đồng bộ
    # Frontend hiển thị 2 progress bar riêng dựa trên các field này
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0

    # --- Trạng thái nền tảng ---
    twitter_running: bool = False    # True khi OASIS Twitter đang chạy
    reddit_running: bool = False     # True khi OASIS Reddit đang chạy
    twitter_actions_count: int = 0   # Tổng hành động Twitter đã ghi được
    reddit_actions_count: int = 0    # Tổng hành động Reddit đã ghi được

    # Phát hiện qua event_type="simulation_end" trong actions.jsonl
    # (KHÔNG dựa vào exit_code của subprocess — vì exit_code chỉ biết khi process kết thúc)
    twitter_completed: bool = False
    reddit_completed: bool = False

    # --- Lịch sử vòng ---
    rounds: List[RoundSummary] = field(default_factory=list)

    # --- Hành động gần nhất (tối đa 50) ---
    # insert(0, ...) → luôn giữ mới nhất ở đầu list
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50

    # --- Timestamps ---
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None

    # --- Lỗi ---
    error: Optional[str] = None

    # --- Process ID ---
    # Lưu lại để có thể kill process khi cần dừng
    process_pid: Optional[int] = None

    def add_action(self, action: AgentAction):
        """Thêm hành động vào đầu recent_actions, giữ tối đa max_recent_actions."""
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > self.max_recent_actions:
            self.recent_actions = self.recent_actions[:self.max_recent_actions]

        if action.platform == "twitter":
            self.twitter_actions_count += 1
        else:
            self.reddit_actions_count += 1

        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize ra dict gọn — dùng cho API response và ghi run_state.json."""
        return {
            "simulation_id": self.simulation_id,
            "runner_status": self.runner_status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "simulated_hours": self.simulated_hours,
            "total_simulation_hours": self.total_simulation_hours,
            # Phần trăm hoàn thành: tránh ZeroDivisionError khi total_rounds=0
            "progress_percent": round(self.current_round / max(self.total_rounds, 1) * 100, 1),
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
        """Serialize đầy đủ bao gồm recent_actions — dùng để ghi run_state.json."""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


# ==============================================================================
# CLASS: SimulationRunner — Trình chạy và giám sát OASIS subprocess
# ==============================================================================
# SimulationRunner là class-only (tất cả methods đều là @classmethod) — dùng như singleton.
# Không cần khởi tạo instance, gọi trực tiếp: SimulationRunner.start_simulation(...)
#
# Tại sao class-level dict thay vì instance dict?
#   Flask chạy nhiều request đồng thời → nhiều thread cùng truy cập runner state.
#   Class-level dict được chia sẻ giữa tất cả thread trong cùng Flask process.
#   → Không cần singleton pattern phức tạp, class dict là đủ.
#
# _processes:       simulation_id → subprocess.Popen (để kill khi cần)
# _run_states:      simulation_id → SimulationRunState (RAM cache của run_state.json)
# _monitor_threads: simulation_id → Thread (daemon thread đọc actions.jsonl)
# _stdout_files:    simulation_id → file handle (để đóng khi process kết thúc)
# ==============================================================================

class SimulationRunner:
    """
    Trình chạy mô phỏng

    Quy trách nhiệm:
    1. Chạy mô phỏng OASIS trong tiến trình nền (background process)
    2. Phân tích nhật ký chạy (log), ghi lại hành động của mỗi Agent
    3. Cung cấp API truy vấn trạng thái thời gian thực
    4. Hỗ trợ thao tác tạm dừng (pause)/dừng (stop)/tiếp tục (resume)
    """

    # Thư mục lưu trữ trạng thái chạy (mỗi simulation có subfolder riêng)
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )

    # Thư mục chứa các OASIS script (run_parallel_simulation.py, ...)
    # Scripts không được copy vào thư mục simulation — gọi thẳng từ đây
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )

    # --- Class-level state (chia sẻ giữa tất cả request threads) ---
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # Lưu file handle để đóng khi process kết thúc
    _stderr_files: Dict[str, Any] = {}  # Không dùng riêng (stderr merge vào stdout)

    # Cấu hình Graph Memory Update (tính năng tùy chọn: ghi hành động agent vào Zep)
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id → True/False

    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """
        Lấy trạng thái runtime hiện tại — cache-aside (RAM trước, disk fallback).
        Trả về None nếu simulation chưa được start.
        """
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]

        # Không có trong RAM → thử load từ run_state.json
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state

    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """
        Load SimulationRunState từ run_state.json trên disk.

        Được gọi khi:
        1. Server restart → RAM cache trống → cần load lại từ disk
        2. Lần đầu gọi get_run_state() sau khi start_simulation()

        Lưu ý: nếu run_state.json có status="running" sau server restart,
        đó là "false positive" — process đã chết cùng server. Phải gọi
        cleanup_simulation_logs() trước khi start lại.
        """
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

            # Restore 50 hành động gần nhất (để hiển thị lại sau restart)
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
        """
        Ghi SimulationRunState ra run_state.json VÀ cập nhật RAM cache.

        Được gọi:
        1. Sau mỗi lần đọc actions.jsonl trong monitor thread (mỗi 2 giây)
        2. Khi trạng thái thay đổi (STARTING → RUNNING → COMPLETED/FAILED)
        3. Khi process kết thúc (cleanup trong finally block)
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")

        # to_detail_dict() bao gồm recent_actions — đầy đủ hơn to_dict()
        data = state.to_detail_dict()

        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        cls._run_states[state.simulation_id] = state

    # --------------------------------------------------------------------------
    # PUBLIC: start_simulation — Khởi động OASIS subprocess + monitor thread
    # --------------------------------------------------------------------------

    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # "twitter" / "reddit" / "parallel"
        max_rounds: int = None,       # Giới hạn số vòng tối đa (None = không giới hạn)
        enable_graph_memory_update: bool = False,  # Ghi hành động agent vào Zep Graph
        graph_id: str = None          # Bắt buộc nếu enable_graph_memory_update=True
    ) -> SimulationRunState:
        """
        Khởi động simulation:
        1. Đọc simulation_config.json → tính total_rounds
        2. subprocess.Popen(run_parallel_simulation.py --config ...) → OASIS chạy ngầm
        3. Thread(_monitor_simulation) → daemon thread đọc actions.jsonl mỗi 2 giây

        Sau khi hàm này return, OASIS đang chạy trong background.
        Flask vẫn nhận request bình thường — không bị block.

        start_new_session=True: tạo process group mới → có thể kill toàn bộ cây process
        bằng os.killpg() (thay vì chỉ kill process cha).

        Args:
            simulation_id: ID của simulation đã qua prepare (status=READY)
            platform: Nền tảng chạy ("twitter"/"reddit"/"parallel")
            max_rounds: Cắt ngắn số vòng nếu chỉ muốn chạy thử
            enable_graph_memory_update: Ghi lại hành động agent vào Zep Graph theo real-time
            graph_id: Zep Graph ID (bắt buộc khi enable_graph_memory_update=True)

        Returns:
            SimulationRunState với runner_status=RUNNING
        """
        # Kiểm tra không cho start khi đã đang chạy
        existing = cls.get_run_state(simulation_id)
        if existing and existing.runner_status in [RunnerStatus.RUNNING, RunnerStatus.STARTING]:
            raise ValueError(f"Simulation is already running: {simulation_id}")

        # Đọc simulation_config.json để tính total_rounds
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")

        if not os.path.exists(config_path):
            raise ValueError(f"Simulation configuration not found, please call the /prepare API first")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Tính total_rounds từ time_config
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        # Ví dụ: 72h × 60min / 60min/round = 72 rounds

        # Áp dụng giới hạn max_rounds nếu có (dùng để test chạy nhanh)
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

        # Khởi tạo run state ban đầu với status=STARTING
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=datetime.now().isoformat(),
        )

        cls._save_run_state(state)

        # Khởi tạo Graph Memory Updater nếu được bật
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("graph_id is required to enable graph memory updates")

            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"Graph memory update enabled: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"Failed to create graph memory updater: {e}")
                cls._graph_memory_enabled[simulation_id] = False
        else:
            cls._graph_memory_enabled[simulation_id] = False

        # Chọn script OASIS phù hợp với platform
        if platform == "twitter":
            script_name = "run_twitter_simulation.py"
            state.twitter_running = True
        elif platform == "reddit":
            script_name = "run_reddit_simulation.py"
            state.reddit_running = True
        else:
            # "parallel" — chạy cả hai platform đồng thời (asyncio bên trong script)
            script_name = "run_parallel_simulation.py"
            state.twitter_running = True
            state.reddit_running = True

        script_path = os.path.join(cls.SCRIPTS_DIR, script_name)

        if not os.path.exists(script_path):
            raise ValueError(f"Script no longer exists: {script_path}")

        # Tạo action queue (hiện chưa dùng nhưng giữ lại cho tương lai)
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue

        # Khởi động OASIS subprocess
        try:
            cmd = [
                sys.executable,   # Python interpreter hiện tại
                script_path,
                "--config", config_path,
            ]

            # Truyền max_rounds vào script nếu có
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])

            # stdout/stderr → simulation.log (tránh pipe buffer đầy gây block)
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')

            # Đảm bảo UTF-8 trên mọi OS (đặc biệt Windows mặc định CP1252)
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'           # Python 3.7+: buộc mọi open() dùng UTF-8
            env['PYTHONIOENCODING'] = 'utf-8' # stdout/stderr cũng UTF-8

            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,              # Working dir = thư mục simulation (script đọc file tương đối từ đây)
                stdout=main_log_file,
                stderr=subprocess.STDOUT, # Merge stderr vào stdout → 1 file log duy nhất
                text=True,
                encoding='utf-8',
                bufsize=1,
                env=env,
                start_new_session=True,   # Tạo process group mới → os.killpg() kill được toàn cây
            )

            cls._stdout_files[simulation_id] = main_log_file
            cls._stderr_files[simulation_id] = None  # Không cần file riêng cho stderr

            state.process_pid = process.pid
            state.runner_status = RunnerStatus.RUNNING
            cls._processes[simulation_id] = process
            cls._save_run_state(state)

            # Khởi động daemon monitor thread — chạy song song với Flask
            # daemon=True → thread tự chết khi main process kết thúc
            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id,),
                daemon=True
            )
            monitor_thread.start()
            cls._monitor_threads[simulation_id] = monitor_thread

            logger.info(f"Simulation started successfully: {simulation_id}, pid={process.pid}, platform={platform}")

        except Exception as e:
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
            raise

        return state

    # --------------------------------------------------------------------------
    # PRIVATE: _monitor_simulation — Daemon thread theo dõi tiến độ real-time
    # --------------------------------------------------------------------------

    @classmethod
    def _monitor_simulation(cls, simulation_id: str):
        """
        Daemon thread chạy liên tục, đọc actions.jsonl và cập nhật run_state.json.

        Cấu trúc log (mới — tách theo platform):
          uploads/simulations/<sim_id>/twitter/actions.jsonl
          uploads/simulations/<sim_id>/reddit/actions.jsonl

        Cơ chế file seek:
          Mỗi lần đọc, hàm _read_action_log() trả về vị trí cuối file (f.tell()).
          Lần tiếp theo, seek đến vị trí đó → chỉ đọc các dòng MỚI thêm vào.
          → Tránh parse lại toàn bộ file mỗi 2 giây.

        Vòng lặp kết thúc khi process.poll() != None (process đã thoát).
        Sau đó: đọc log lần cuối → xử lý exit_code → cleanup resources.
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)

        # Cấu trúc log mới: tách log hành động theo từng nền tảng
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")

        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)

        if not process or not state:
            return

        # Vị trí đọc cuối cùng trong mỗi file (file seek position)
        twitter_position = 0
        reddit_position = 0

        try:
            # Vòng lặp chính: chạy cho đến khi process kết thúc
            while process.poll() is None:
                # Đọc log Twitter (chỉ đọc phần mới từ twitter_position)
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )

                # Đọc log Reddit (chỉ đọc phần mới từ reddit_position)
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )

                # Lưu trạng thái → Frontend có thể poll API để lấy tiến độ
                cls._save_run_state(state)
                time.sleep(2)  # Poll mỗi 2 giây

            # Process đã kết thúc — đọc log lần cuối để không bỏ sót action cuối
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")

            # Xử lý kết quả dựa trên exit_code
            exit_code = process.returncode

            if exit_code == 0:
                state.runner_status = RunnerStatus.COMPLETED
                state.completed_at = datetime.now().isoformat()
                logger.info(f"Simulation completed: {simulation_id}")
            else:
                state.runner_status = RunnerStatus.FAILED
                # Đọc 2000 ký tự cuối của simulation.log làm error message
                main_log_path = os.path.join(sim_dir, "simulation.log")
                error_info = ""
                try:
                    if os.path.exists(main_log_path):
                        with open(main_log_path, 'r', encoding='utf-8') as f:
                            error_info = f.read()[-2000:]
                except Exception:
                    pass
                state.error = f"Process exit code: {exit_code}, error: {error_info}"
                logger.error(f"Simulation failed: {simulation_id}, error={state.error}")

            state.twitter_running = False
            state.reddit_running = False
            cls._save_run_state(state)

        except Exception as e:
            logger.error(f"Monitor thread exception: {simulation_id}, error={str(e)}")
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)

        finally:
            # Dừng Graph Memory Updater nếu đang chạy
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    logger.info(f"Graph memory update stopped: simulation_id={simulation_id}")
                except Exception as e:
                    logger.error(f"Failed to stop graph memory updater: {e}")
                cls._graph_memory_enabled.pop(simulation_id, None)

            # Dọn dẹp tài nguyên process
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)

            # Đóng file handle log (stdout)
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

    # --------------------------------------------------------------------------
    # PRIVATE: _read_action_log — Parse actions.jsonl từ vị trí đã đọc
    # --------------------------------------------------------------------------

    @classmethod
    def _read_action_log(
        cls,
        log_path: str,
        position: int,
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        Đọc các dòng mới trong actions.jsonl từ vị trí `position`.

        Cơ chế file seek:
          f.seek(position) → bỏ qua phần đã đọc trước
          f.tell() → trả về vị trí hiện tại sau khi đọc → dùng cho lần tiếp theo

        Hai loại dòng JSON trong actions.jsonl:

        1. Sự kiện hệ thống (có field "event_type"):
           {"event_type": "round_end",   "round": 15, "simulated_hours": 15}
           {"event_type": "simulation_end", "total_rounds": 72, "total_actions": 3420}
           → Cập nhật round_num, simulated_hours, completed flag

        2. Hành động agent (không có "event_type", có "agent_id"):
           {"round": 15, "agent_id": 3, "action_type": "CREATE_POST", ...}
           → Tạo AgentAction object, thêm vào state.recent_actions

        Args:
            log_path: Đường dẫn file actions.jsonl
            position: Vị trí byte đã đọc tới lần trước
            state: SimulationRunState cần cập nhật
            platform: "twitter" hoặc "reddit"

        Returns:
            Vị trí byte mới (dùng cho lần gọi tiếp theo)
        """
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = ZepGraphMemoryManager.get_updater(state.simulation_id)

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(position)  # Nhảy đến vị trí đã đọc lần trước
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            action_data = json.loads(line)

                            # Xử lý sự kiện hệ thống (event_type)
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")

                                if event_type == "simulation_end":
                                    # OASIS báo hiệu đã chạy hết số vòng → đánh dấu platform completed
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")

                                    # Kiểm tra nếu tất cả platform đã xong → đánh dấu COMPLETED
                                    # Logic: platform nào bật (có actions.jsonl) thì phải xong; phải có ít nhất 1 xong
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        state.runner_status = RunnerStatus.COMPLETED
                                        state.completed_at = datetime.now().isoformat()
                                        logger.info(f"Simulation completed for all platforms: {state.simulation_id}")

                                elif event_type == "round_end":
                                    # Cập nhật số vòng và giờ đã mô phỏng (độc lập cho từng platform)
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)

                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours

                                    # Vòng chung = max của 2 platform (platform nhanh hơn làm mốc)
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    state.simulated_hours = max(state.twitter_simulated_hours, state.reddit_simulated_hours)

                                continue  # Không tạo AgentAction cho sự kiện hệ thống

                            # Xử lý hành động agent (có agent_id)
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

                            # Cập nhật current_round từ action nếu cần
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num

                            # Ghi hành động vào Zep Graph nếu tính năng được bật
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)

                        except json.JSONDecodeError:
                            pass  # Dòng không phải JSON hợp lệ → bỏ qua

                return f.tell()  # Trả về vị trí cuối để lần sau tiếp tục từ đây
        except Exception as e:
            logger.warning(f"Failed to read action logs: {log_path}, error={e}")
            return position  # Giữ nguyên position nếu đọc lỗi

    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        Kiểm tra xem tất cả platform đã hoàn thành chưa.

        Cách xác định platform có được bật:
        Kiểm tra file actions.jsonl có tồn tại không (không dùng enable_twitter/enable_reddit flag,
        vì flag đó chỉ có trong SimulationState — không truyền sang đây).

        Logic:
          Nếu twitter/actions.jsonl tồn tại → twitter được bật → phải twitter_completed=True
          Nếu reddit/actions.jsonl tồn tại  → reddit được bật  → phải reddit_completed=True
          Phải có ít nhất 1 platform xong (tránh trả True khi cả 2 chưa tạo file)

        Returns:
            True nếu tất cả platform đã bật đều đã completed
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")

        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)

        # Platform nào được bật mà chưa xong → False
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False

        # Phải có ít nhất 1 platform chạy xong
        return twitter_enabled or reddit_enabled

    # --------------------------------------------------------------------------
    # PRIVATE: _terminate_process — Kill process + toàn bộ process group
    # --------------------------------------------------------------------------

    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        Dừng process và toàn bộ process group (bao gồm child processes).

        Tại sao phải kill cả process group?
        OASIS script có thể spawn thêm asyncio workers hoặc subprocess con.
        Kill chỉ process cha sẽ để lại các zombie child processes.

        Unix: os.killpg(pgid, SIGTERM) → chờ 10s → os.killpg(pgid, SIGKILL) nếu không thoát
        Windows: taskkill /T /PID → chờ → taskkill /F /T /PID nếu không thoát

        start_new_session=True (trong Popen) đảm bảo pgid == pid của process cha.

        Args:
            process: Subprocess.Popen object
            simulation_id: Chỉ dùng để log
            timeout: Giây chờ trước khi SIGKILL (mặc định 10s)
        """
        if IS_WINDOWS:
            logger.info(f"Terminating process (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # Bước 1: Dừng nhẹ nhàng (/T = kill cả tree)
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Bước 2: Kill cưỡng bức (/F = force)
                    logger.warning(f"Process unresponsive, force terminating: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill failed, attempting terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: dùng process group để kill toàn bộ cây
            pgid = os.getpgid(process.pid)
            logger.info(f"Terminating process group (Unix): simulation={simulation_id}, pgid={pgid}")

            # Bước 1: SIGTERM — tín hiệu nhẹ nhàng, cho phép process dọn dẹp
            os.killpg(pgid, signal.SIGTERM)

            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Bước 2: SIGKILL — kill cưỡng bức, không thể bị bắt hay bỏ qua
                logger.warning(f"Process group unresponsive to SIGTERM, force terminating: {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)

    # --------------------------------------------------------------------------
    # PUBLIC: stop_simulation — Dừng simulation theo yêu cầu người dùng
    # --------------------------------------------------------------------------

    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """
        Dừng OASIS subprocess → state = STOPPED.

        Thứ tự:
        1. Chuyển state sang STOPPING (để frontend biết đang xử lý)
        2. _terminate_process() — kill process group
        3. Chuyển state sang STOPPED
        4. Dừng Graph Memory Updater nếu đang chạy

        Khác với FAILED: STOPPED là do người dùng chủ động, FAILED là do crash.
        """
        state = cls.get_run_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation not found: {simulation_id}")

        if state.runner_status not in [RunnerStatus.RUNNING, RunnerStatus.PAUSED]:
            raise ValueError(f"Simulation is not running: {simulation_id}, status={state.runner_status}")

        state.runner_status = RunnerStatus.STOPPING
        cls._save_run_state(state)

        # Kill OASIS subprocess (và toàn bộ process group)
        process = cls._processes.get(simulation_id)
        if process and process.poll() is None:
            try:
                cls._terminate_process(process, simulation_id)
            except ProcessLookupError:
                # Process đã tự thoát trước khi kịp kill — OK
                pass
            except Exception as e:
                logger.error(f"Failed to terminate process group: {simulation_id}, error={e}")
                # Fallback: try terminate() rồi kill()
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()

        state.runner_status = RunnerStatus.STOPPED
        state.twitter_running = False
        state.reddit_running = False
        state.completed_at = datetime.now().isoformat()
        cls._save_run_state(state)

        # Dừng Graph Memory Updater
        if cls._graph_memory_enabled.get(simulation_id, False):
            try:
                ZepGraphMemoryManager.stop_updater(simulation_id)
                logger.info(f"Graph memory update stopped: simulation_id={simulation_id}")
            except Exception as e:
                logger.error(f"Failed to stop graph memory updater: {e}")
            cls._graph_memory_enabled.pop(simulation_id, None)

        logger.info(f"Simulation stopped: {simulation_id}")
        return state

    # --------------------------------------------------------------------------
    # PUBLIC: Đọc lịch sử hành động (dùng sau khi simulation kết thúc)
    # --------------------------------------------------------------------------

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
        Đọc toàn bộ actions từ 1 file actions.jsonl với các bộ lọc tùy chọn.

        Bỏ qua:
        - Dòng có "event_type" (sự kiện hệ thống: round_end, simulation_end)
        - Dòng không có "agent_id" (không phải hành động của agent)

        Args:
            file_path: Đường dẫn file actions.jsonl
            default_platform: Điền tự động nếu record không có field "platform"
            platform_filter: Chỉ lấy record của platform này
            agent_id: Chỉ lấy record của agent này
            round_num: Chỉ lấy record của vòng này
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

                    # Bỏ qua sự kiện hệ thống
                    if "event_type" in data:
                        continue

                    # Bỏ qua record không có agent_id
                    if "agent_id" not in data:
                        continue

                    record_platform = data.get("platform") or default_platform or ""

                    # Áp dụng bộ lọc
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
        Lấy toàn bộ lịch sử hành động — đọc từ file (không giới hạn phân trang).

        Thứ tự ưu tiên đọc file:
        1. twitter/actions.jsonl  (cấu trúc mới — tách theo platform)
        2. reddit/actions.jsonl
        3. actions.jsonl          (cấu trúc cũ — fallback tương thích ngược)

        Kết quả được sort theo timestamp giảm dần (mới nhất lên đầu).
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []

        # Đọc Twitter actions
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))

        # Đọc Reddit actions
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))

        # Fallback: đọc file actions.jsonl cũ nếu không có thư mục twitter/reddit
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # File cũ đã có field platform trong record
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )

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
        Lấy lịch sử hành động có phân trang (offset + limit).

        Gọi get_all_actions() rồi cắt — không tối ưu cho file lớn nhưng đơn giản.
        Nếu hiệu năng là vấn đề, cần cải thiện bằng cách chỉ đọc đến offset+limit.
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )

        return actions[offset:offset + limit]

    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Lấy timeline mô phỏng — tóm tắt theo từng vòng.

        Nhóm tất cả actions theo round_num, tính:
        - Số action twitter/reddit trong vòng
        - Danh sách agent_id đã hoạt động
        - Phân phối action_type (CREATE_POST, LIKE_POST, ...)

        Dùng để hiển thị biểu đồ hoạt động theo thời gian trên frontend.
        """
        actions = cls.get_actions(simulation_id, limit=10000)

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

        # Chuyển set → list để JSON serializable, sort theo round_num tăng dần
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
        Thống kê hoạt động của từng agent — sort theo tổng số hành động giảm dần.

        Dùng để hiển thị bảng xếp hạng "agent nào hoạt động nhiều nhất".
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

        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)

        return result

    # --------------------------------------------------------------------------
    # PUBLIC: cleanup — Dọn dẹp file log để cho phép chạy lại
    # --------------------------------------------------------------------------

    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Xóa các file runtime để buộc simulation được khởi động lại từ đầu.

        CÁC FILE BỊ XÓA (runtime logs):
          run_state.json, simulation.log, stdout.log, stderr.log,
          twitter_simulation.db, reddit_simulation.db, env_status.json,
          twitter/actions.jsonl, reddit/actions.jsonl

        CÁC FILE GIỮ LẠI (config + profiles — không xóa):
          simulation_config.json, reddit_profiles.json, twitter_profiles.csv, state.json

        Khi nào cần gọi:
          Sau server restart nếu run_state.json vẫn hiển thị status="running"
          (process đã chết cùng server → không thể tiếp tục, phải cleanup rồi start lại)

        Returns:
            {"success": bool, "cleaned_files": [...], "errors": [...]}
        """
        import shutil

        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)

        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory does not exist, no need to clean."}

        cleaned_files = []
        errors = []

        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",
            "reddit_simulation.db",
            "env_status.json",
        ]

        dirs_to_clean = ["twitter", "reddit"]

        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"Failed to delete {filename}: {str(e)}")

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

        # Xóa RAM cache cho simulation này
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]

        logger.info(f"Clean up complete for simulation: {simulation_id}, Deleted files: {cleaned_files}")

        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }

    # Cờ chống gọi cleanup nhiều lần (atexit có thể gọi nhiều lần trong một số trường hợp)
    _cleanup_done = False

    @classmethod
    def cleanup_all_simulations(cls):
        """
        Dọn dẹp tất cả simulation đang chạy — gọi khi server tắt.

        Được đăng ký bởi:
          atexit.register(cls.cleanup_all_simulations)   → khi Python interpreter kết thúc
          signal.signal(SIGTERM, cleanup_handler)        → khi nhận SIGTERM (kill server)
          signal.signal(SIGINT, cleanup_handler)         → khi Ctrl+C

        Thực hiện:
        1. Dừng tất cả Graph Memory Updaters
        2. Kill toàn bộ OASIS subprocess đang chạy
        3. Cập nhật state.json → status="stopped" (để frontend không hiển thị "running" sau khi restart)
        4. Cập nhật run_state.json → runner_status="stopped"
        5. Đóng tất cả file handle
        6. Clear RAM cache
        """
        if cls._cleanup_done:
            return
        cls._cleanup_done = True

        has_processes = bool(cls._processes)
        has_updaters = bool(cls._graph_memory_enabled)

        if not has_processes and not has_updaters:
            return  # Không có gì để dọn

        logger.info("Cleaning up all simulation processes...")

        # Dừng tất cả Graph Memory Updaters
        try:
            ZepGraphMemoryManager.stop_all()
        except Exception as e:
            logger.error(f"Failed to stop Zep Graph update daemon: {e}")
        cls._graph_memory_enabled.clear()

        # Tạo bản sao để tránh RuntimeError khi dict thay đổi trong khi lặp
        processes = list(cls._processes.items())

        for simulation_id, process in processes:
            try:
                if process.poll() is None:  # Process vẫn đang chạy
                    logger.info(f"Terminating simulation process: {simulation_id}, pid={process.pid}")

                    try:
                        cls._terminate_process(process, simulation_id, timeout=5)
                    except (ProcessLookupError, OSError):
                        # Process đã biến mất → fallback terminate/kill
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except Exception:
                            process.kill()

                    # Cập nhật run_state.json → status=stopped
                    state = cls.get_run_state(simulation_id)
                    if state:
                        state.runner_status = RunnerStatus.STOPPED
                        state.twitter_running = False
                        state.reddit_running = False
                        state.completed_at = datetime.now().isoformat()
                        state.error = "Server shut down, simulation terminated."
                        cls._save_run_state(state)

                    # Cập nhật state.json → status="stopped" (SimulationManager's file)
                    # Lý do: SimulationManager không tự biết server đang tắt → phải cập nhật thủ công
                    try:
                        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
                        state_file = os.path.join(sim_dir, "state.json")
                        logger.info(f"Attempting to update state.json: {state_file}")
                        if os.path.exists(state_file):
                            with open(state_file, 'r', encoding='utf-8') as f:
                                state_data = json.load(f)
                            state_data['status'] = 'stopped'
                            state_data['updated_at'] = datetime.now().isoformat()
                            with open(state_file, 'w', encoding='utf-8') as f:
                                json.dump(state_data, f, indent=2, ensure_ascii=False)
                            logger.info(f"Updated state.json status to 'stopped': {simulation_id}")
                        else:
                            logger.warning(f"state.json not found: {state_file}")
                    except Exception as state_err:
                        logger.warning(f"Failed to update state.json: {simulation_id}, error={state_err}")

            except Exception as e:
                logger.error(f"Failed to clean up process: {simulation_id}, error={e}")

        # Đóng tất cả file handle log
        for simulation_id, file_handle in list(cls._stdout_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stdout_files.clear()

        for simulation_id, file_handle in list(cls._stderr_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stderr_files.clear()

        # Clear RAM cache
        cls._processes.clear()
        cls._action_queues.clear()

        logger.info("Simulation process clean up completed.")

    @classmethod
    def register_cleanup(cls):
        """
        Đăng ký hàm dọn dẹp khi server tắt.

        Gọi 1 lần duy nhất trong app initialization (Flask app factory).
        Đăng ký 3 signal handlers + atexit fallback:
          SIGTERM: kill server lệnh (Linux/Mac: systemd stop, Docker stop)
          SIGINT:  Ctrl+C từ terminal
          SIGHUP:  Terminal bị đóng (Unix only)
          atexit:  Fallback khi signal handling không khả dụng

        Lưu ý Flask debug mode:
        Werkzeug reload spawns 2 processes — chỉ đăng ký trong reloader child process
        (WERKZEUG_RUN_MAIN=true). Production luôn đăng ký.
        """
        global _cleanup_registered

        if _cleanup_registered:
            return

        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None

        # Debug mode: chỉ đăng ký trong child process của Werkzeug reloader
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True
            return

        # Lưu signal handlers gốc để gọi lại sau khi cleanup
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)

        def cleanup_handler(signum=None, frame=None):
            """Cleanup toàn bộ simulation rồi forward signal về handler gốc."""
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"Received signal {signum}, starting clean up...")
            cls.cleanup_all_simulations()

            # Forward signal về Flask/Werkzeug handler gốc
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    sys.exit(0)
            else:
                raise KeyboardInterrupt

        # Đăng ký atexit làm fallback (nếu signal handler không chạy được)
        atexit.register(cls.cleanup_all_simulations)

        # Đăng ký signal handlers — chỉ hoạt động trong main thread
        try:
            signal.signal(signal.SIGTERM, cleanup_handler)
            signal.signal(signal.SIGINT, cleanup_handler)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # Không ở main thread → chỉ dùng atexit fallback
            logger.warning("Failed to register signal handlers (not in main thread). Falling back to atexit.")

        _cleanup_registered = True

    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """Lấy danh sách simulation_id đang có process chạy (process.poll() is None)."""
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running

    # --------------------------------------------------------------------------
    # PUBLIC: Interview — Phỏng vấn agent đang chạy qua IPC
    # --------------------------------------------------------------------------

    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        Kiểm tra xem OASIS environment có còn nhận lệnh IPC không.

        Đọc env_status.json → status == "alive".
        Phải kiểm tra trước khi gửi bất kỳ lệnh Interview nào.
        Nếu False → raise ValueError ngay, không gửi IPC để tránh timeout.
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Lấy thông tin chi tiết trạng thái IPC environment.

        Returns dict:
          status:            "alive" hoặc "stopped"
          twitter_available: True nếu Twitter environment đang active
          reddit_available:  True nếu Reddit environment đang active
          timestamp:         Thời điểm cập nhật env_status.json cuối cùng
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
        Phỏng vấn 1 agent đang chạy qua IPC.

        Flow:
        1. check_env_alive() → nếu False → raise ValueError ngay
        2. SimulationIPCClient.send_interview() → ghi file ipc_commands/{uuid}.json
        3. Poll ipc_responses/{uuid}.json mỗi 0.5s, timeout 60s
        4. OASIS script phát hiện command → chạy ManualAction INTERVIEW → ghi response
        5. Trả về response về caller

        Args:
            agent_id: ID của agent (khớp với user_id trong profile file)
            prompt: Câu hỏi phỏng vấn
            platform: "twitter"/"reddit"/None (None = phỏng vấn trên platform đang active)
            timeout: Timeout tính bằng giây
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or closed, cannot perform Interview: {simulation_id}")

        logger.info(f"Sending Interview Command: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

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
        Phỏng vấn nhiều agent cùng lúc — gửi 1 batch command duy nhất.

        Hiệu quả hơn gọi interview_agent() N lần vì chỉ cần 1 round-trip IPC.
        OASIS xử lý tất cả interviews trong batch rồi trả về kết quả gộp.

        Args:
            interviews: List[{"agent_id": int, "prompt": str, "platform": str (optional)}]
            platform: Platform mặc định cho tất cả (nếu không chỉ định riêng từng phần tử)
            timeout: Timeout tổng cho toàn bộ batch
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or closed, cannot perform Interview: {simulation_id}")

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
        Phỏng vấn TẤT CẢ agent với cùng 1 câu hỏi.

        Đọc danh sách agent từ simulation_config.json → build interviews list →
        gọi interview_agents_batch().

        Dùng khi muốn biết toàn bộ quan điểm của cộng đồng về 1 chủ đề.
        Timeout mặc định 180s vì số lượng agent nhiều.
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation does not exist: {simulation_id}")

        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"Simulation config not found: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"No Agent defined under simulation configs: {simulation_id}")

        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"Sending GLOBAL Interview command: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

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
        Gửi lệnh đóng environment qua IPC (không kill process ngay).

        Khác với stop_simulation():
          stop_simulation() → SIGTERM ngay lập tức (brutal)
          close_simulation_env() → gửi lệnh IPC để OASIS tự dọn dẹp rồi thoát (graceful)

        Dùng khi muốn kết thúc simulation sớm nhưng để OASIS lưu trạng thái trước.
        Nếu timeout → trả về success=True vì environment có thể đang trong quá trình đóng.
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

        logger.info(f"Sending command to close Environment: simulation_id={simulation_id}")

        try:
            response = ipc_client.send_close_env(timeout=timeout)

            return {
                "success": response.status.value == "completed",
                "message": "Environment close command sent",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # Timeout thường xảy ra khi environment đang trong quá trình đóng → OK
            return {
                "success": True,
                "message": "Environment close command sent (timeout waiting for response, env might be closing)"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to send close env command: {str(e)}"
            }

    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Đọc lịch sử phỏng vấn từ SQLite database của OASIS.

        OASIS lưu kết quả interview vào bảng `trace` trong database
        (twitter_simulation.db hoặc reddit_simulation.db).
        Truy vấn WHERE action='interview' để lọc ra các record phỏng vấn.
        """
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
            logger.error(f"Failed to load Interview history ({platform_name}): {e}")

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
        Lấy lịch sử phỏng vấn từ database — dùng sau khi simulation đã chạy.

        Đọc từ:
          twitter_simulation.db (nếu platform="twitter" hoặc None)
          reddit_simulation.db  (nếu platform="reddit" hoặc None)

        Kết quả sort theo timestamp giảm dần, giới hạn `limit` record.
        Khi query kết hợp cả 2 platform, giới hạn tổng = limit (không phải limit×2).

        Args:
            platform: "twitter"/"reddit"/None (None = cả hai)
            agent_id: Lọc theo agent cụ thể
            limit: Số record tối đa trả về
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)

        results = []

        platforms = [platform] if platform in ("reddit", "twitter") else ["twitter", "reddit"]

        for p in platforms:
            db_path = os.path.join(sim_dir, f"{p}_simulation.db")
            platform_results = cls._get_interview_history_from_db(
                db_path=db_path,
                platform_name=p,
                agent_id=agent_id,
                limit=limit
            )
            results.extend(platform_results)

        # Sort tổng hợp theo timestamp mới nhất
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Cắt về đúng limit khi query kết hợp nhiều platform
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]

        return results
