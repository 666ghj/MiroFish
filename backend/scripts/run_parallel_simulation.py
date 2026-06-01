"""
OASIS Script — Chạy simulation song song hai nền tảng Twitter + Reddit

Vị trí trong pipeline:
─────────────────────────────────────────────────────────────────────────────
  SimulationRunner.start_simulation()   [Flask backend]
      └─ subprocess.Popen(run_parallel_simulation.py --config ...)
              │  (Script này chạy độc lập — không phải Flask process)
              │
              ├── asyncio.gather(run_twitter_simulation, run_reddit_simulation)
              │       └─ Hai platform chạy SONG SONG trong cùng event loop
              │
              └── Sau khi xong: vào chế độ chờ lệnh IPC (Interview)
─────────────────────────────────────────────────────────────────────────────

Luồng dữ liệu vào script:
  simulation_config.json  → thời gian, agent configs, initial posts
  twitter_profiles.csv    → hồ sơ agent Twitter (user_char = system prompt)
  reddit_profiles.json    → hồ sơ agent Reddit

Luồng dữ liệu ra script:
  twitter/actions.jsonl   → mỗi dòng = 1 hành động của agent Twitter
  reddit/actions.jsonl    → mỗi dòng = 1 hành động của agent Reddit
  simulation.log          → stdout của script (được Flask redirect vào đây)
  env_status.json         → trạng thái IPC (alive/stopped)
  twitter_simulation.db   → SQLite database của OASIS Twitter
  reddit_simulation.db    → SQLite database của OASIS Reddit

Cơ chế đọc action từ DB (quan trọng):
  env.step(actions) KHÔNG trả về kết quả hữu ích — OASIS ghi action vào SQLite.
  Script dùng rowid để track bản ghi đã xử lý và đọc action MỚI sau mỗi round.
  Lý do dùng rowid thay vì created_at: Twitter dùng integer timestamp,
  Reddit dùng datetime string — rowid là integer tự tăng, nhất quán trên cả hai.

Hai LLM riêng biệt (tùy chọn):
  Twitter → LLM_API_KEY (general)
  Reddit  → LLM_BOOST_API_KEY (boost, nếu có) → tăng throughput khi chạy song song
  Nếu không có boost config → Reddit fallback về general LLM.

Tính năng:
- Chạy song song hai nền tảng (Twitter + Reddit) qua asyncio.gather
- Sau simulation, KHÔNG đóng environment → vào chế độ chờ lệnh IPC
- Hỗ trợ Interview 1 agent, batch, và toàn bộ agent
- Hỗ trợ lệnh đóng environment từ xa (close_env)
- Tham số --no-wait để đóng ngay sau simulation (dùng khi test)
- Tham số --max-rounds để cắt ngắn số vòng (dùng khi test nhanh)

Cách dùng:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only
    python run_parallel_simulation.py --config simulation_config.json --max-rounds 5

Cấu trúc log:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Log hành động nền tảng Twitter
    ├── reddit/
    │   └── actions.jsonl    # Log hành động nền tảng Reddit
    ├── simulation.log       # Log tiến trình mô phỏng chính (stdout của script)
    └── run_state.json       # Trạng thái chạy (cho API truy vấn từ Flask)
"""

# ============================================================
# Khắc phục vấn đề mã hóa trên Windows — PHẢI đặt trước mọi import
# Mục tiêu: sửa lỗi thư viện OASIS bên thứ ba đọc file không chỉ định encoding,
# gây UnicodeDecodeError khi có nội dung tiếng Việt/Unicode trong profile file.
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # Đặt mã hóa I/O mặc định của Python là UTF-8
    # Thiết lập này ảnh hưởng đến mọi lời gọi open() không chỉ định encoding
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

    # Cấu hình lại stdout/stderr sang UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    # Monkey-patch hàm open() tích hợp để mặc định dùng UTF-8
    # Cần thiết vì PYTHONUTF8 không ảnh hưởng đến code đã chạy trước khi đặt env var.
    # Lưu ý: thiết lập lúc runtime có thể không hiệu quả với một số thư viện, nhưng
    # đây là phương án tốt nhất khi không kiểm soát được source code của OASIS.
    import builtins
    _original_open = builtins.open

    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None,
                   newline=None, closefd=True, opener=None):
        """Wrapper cho hàm open(), mặc định dùng UTF-8 cho chế độ văn bản."""
        if encoding is None and 'b' not in mode:
            encoding = 'utf-8'
        return _original_open(file, mode, buffering, encoding, errors,
                              newline, closefd, opener)

    builtins.open = _utf8_open

import argparse
import asyncio
import json
import logging
import multiprocessing
import random
import signal
import sqlite3
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


# Biến toàn cục cho signal handling và shutdown coordination
_shutdown_event = None   # asyncio.Event — được set khi nhận SIGTERM/SIGINT
_cleanup_done = False    # Cờ chống gọi cleanup nhiều lần

# Thêm thư mục backend vào sys.path để import được các module nội bộ
# (action_logger, llm_cost_patch từ backend/scripts/)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# Tải .env ở thư mục gốc dự án (chứa LLM_API_KEY, LLM_BASE_URL, ...)
# Script chạy độc lập (subprocess) nên không thừa hưởng env từ Flask
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
    print(f"Environment config loaded: {_env_file}")
else:
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"Environment config loaded: {_backend_env}")


# ==============================================================================
# Lọc cảnh báo thừa từ camel-ai về max_tokens
# ==============================================================================
# camel-ai log cảnh báo "Invalid or missing max_tokens" mỗi khi tạo LLM call.
# Đây là cảnh báo không quan trọng (chủ động không set max_tokens để model tự quyết định).
# Filter này ngăn cảnh báo đó làm ô nhiễm simulation.log.
# ==============================================================================

class MaxTokensWarningFilter(logging.Filter):
    """Lọc cảnh báo max_tokens của camel-ai."""

    def filter(self, record):
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# Thêm filter ngay khi module được nạp — phải trước khi camel-ai chạy
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    Tắt log chi tiết của thư viện OASIS.

    OASIS ghi log cực kỳ dài dòng (từng quan sát + action của mỗi agent mỗi round).
    MiroFish dùng action_logger riêng (ghi ra actions.jsonl) nên không cần OASIS log.
    Chỉ để CRITICAL — chỉ ghi lỗi nghiêm trọng không thể bỏ qua.
    """
    oasis_loggers = [
        "social.agent",
        "social.twitter",
        "social.rec",
        "oasis.env",
        "table",
    ]

    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """
    Khởi tạo cấu hình log cho mô phỏng.

    Dọn thư mục log/ cũ nếu còn từ lần chạy trước (cấu trúc log cũ đã deprecated).
    Cấu trúc log hiện tại dùng twitter/actions.jsonl và reddit/actions.jsonl.
    """
    disable_oasis_logging()

    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger
from llm_cost_patch import install_openai_cost_patch

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    from camel.memories import ChatHistoryMemory, ScoreBasedContextCreator
    from camel.utils import OpenAITokenCounter
    from camel.types import ModelType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
        generate_reddit_agent_graph
    )
    from oasis.social_platform import Platform
    from oasis.social_platform.channel import Channel
except ImportError as e:
    print(f"Error: Missing dependency {e}")
    print("Please install first: pip install oasis-ai camel-ai")
    sys.exit(1)


# ==============================================================================
# Action types khả dụng trên mỗi platform
# ==============================================================================
# INTERVIEW không có trong danh sách — nó chỉ được kích hoạt thủ công qua
# ManualAction (IPC command), không phải LLMAction trong vòng lặp simulation.
# ==============================================================================

TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

REDDIT_ACTIONS = [
    ActionType.LIKE_POST,
    ActionType.DISLIKE_POST,
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_COMMENT,
    ActionType.DISLIKE_COMMENT,
    ActionType.SEARCH_POSTS,
    ActionType.SEARCH_USER,
    ActionType.TREND,
    ActionType.REFRESH,
    ActionType.DO_NOTHING,
    ActionType.FOLLOW,
    ActionType.MUTE,
]


# Tên file/folder cho cơ chế IPC
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"


class CommandType:
    """Hằng số loại lệnh IPC"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


# ==============================================================================
# CLASS: ParallelIPCHandler — Xử lý lệnh IPC trong khi environment còn sống
# ==============================================================================
# Sau khi simulation loop kết thúc, OASIS environment KHÔNG bị đóng.
# Script vào chế độ chờ — ParallelIPCHandler poll ipc_commands/ mỗi 0.5 giây.
#
# Cơ chế IPC (file-based):
#   Flask ghi: ipc_commands/{uuid}.json
#       {"command_id": "abc", "command_type": "interview", "args": {...}}
#   Script phát hiện → xử lý → ghi: ipc_responses/{uuid}.json
#       {"command_id": "abc", "status": "completed", "result": {...}}
#   Flask poll ipc_responses/{uuid}.json cho đến khi có kết quả.
#   Script xóa file command sau khi đã xử lý xong.
#
# Tại sao dùng file thay vì socket/queue?
#   Subprocess và Flask process không chia sẻ memory.
#   File là cách đơn giản nhất để giao tiếp cross-process mà không cần thêm dependency.
# ==============================================================================

class ParallelIPCHandler:
    """Bộ xử lý lệnh IPC cho hai nền tảng."""

    def __init__(
        self,
        simulation_dir: str,
        twitter_env=None,
        twitter_agent_graph=None,
        reddit_env=None,
        reddit_agent_graph=None
    ):
        self.simulation_dir = simulation_dir
        self.twitter_env = twitter_env
        self.twitter_agent_graph = twitter_agent_graph
        self.reddit_env = reddit_env
        self.reddit_agent_graph = reddit_agent_graph

        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)

        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

    def update_status(self, status: str):
        """
        Ghi env_status.json — Flask đọc file này để biết environment còn sống không.

        Được gọi tại 2 thời điểm:
        1. Khi vào chế độ chờ: update_status("alive")
        2. Khi thoát chế độ chờ: update_status("stopped")

        Flask's check_env_alive() đọc file này trước khi gửi bất kỳ IPC command nào.
        """
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "twitter_available": self.twitter_env is not None,
                "reddit_available": self.reddit_env is not None,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)

    def poll_command(self) -> Optional[Dict[str, Any]]:
        """
        Kiểm tra xem có lệnh nào đang chờ xử lý không.

        Đọc file JSON cũ nhất trong ipc_commands/ (sort theo mtime).
        Trả về None nếu không có lệnh nào, hoặc nếu file không hợp lệ.

        Flask đảm bảo chỉ ghi 1 command tại 1 thời điểm — không cần lock.
        """
        if not os.path.exists(self.commands_dir):
            return None

        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))

        command_files.sort(key=lambda x: x[1])  # Xử lý lệnh cũ nhất trước (FIFO)

        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

        return None

    def send_response(self, command_id: str, status: str, result: Dict = None, error: str = None):
        """
        Ghi kết quả vào ipc_responses/{command_id}.json và xóa file lệnh.

        Flask poll file này (mỗi 0.5s, timeout 60s) để lấy kết quả interview.
        Sau khi ghi response, xóa file command để tránh xử lý lại.
        """
        response = {
            "command_id": command_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }

        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)

        # Xóa file command sau khi đã xử lý xong
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass

    def _get_env_and_graph(self, platform: str):
        """Lấy (env, agent_graph) của platform được chỉ định. Trả về (None, None, None) nếu không có."""
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None

    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        Thực thi Interview trên 1 platform bằng ManualAction.

        ManualAction(INTERVIEW) là cách inject hành động thủ công vào OASIS —
        thay vì để LLM quyết định action, ép agent trả lời câu hỏi cụ thể.

        OASIS ghi kết quả vào bảng `trace` trong SQLite database.
        _get_interview_result() đọc bản ghi mới nhất từ đó.
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)

        if not env or not agent_graph:
            return {"platform": platform, "error": f"{platform} platform is unavailable"}

        try:
            agent = agent_graph.get_agent(agent_id)
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            actions = {agent: interview_action}
            await env.step(actions)  # OASIS chạy action → ghi vào DB

            result = self._get_interview_result(agent_id, actual_platform)
            result["platform"] = actual_platform
            return result

        except Exception as e:
            return {"platform": platform, "error": str(e)}

    async def handle_interview(self, command_id: str, agent_id: int, prompt: str, platform: str = None) -> bool:
        """
        Xử lý lệnh phỏng vấn 1 agent.

        Nếu platform được chỉ định: phỏng vấn trên platform đó thôi.
        Nếu platform=None: phỏng vấn song song cả 2 platform (asyncio.gather),
        trả về kết quả gộp — hữu ích khi muốn so sánh phản ứng của agent
        trên Twitter vs Reddit.

        Returns:
            True nếu ít nhất 1 platform thành công, False nếu tất cả fail.
        """
        if platform in ("twitter", "reddit"):
            result = await self._interview_single_platform(agent_id, prompt, platform)

            if "error" in result:
                self.send_response(command_id, "failed", error=result["error"])
                print(f"  Interview failed: agent_id={agent_id}, platform={platform}, error={result['error']}")
                return False
            else:
                self.send_response(command_id, "completed", result=result)
                print(f"  Interview completed: agent_id={agent_id}, platform={platform}")
                return True

        # Không chỉ định platform → phỏng vấn cả 2 song song
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="No simulation environment available")
            return False

        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0

        tasks = []
        platforms_to_interview = []

        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")

        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")

        # Chạy song song — asyncio.gather không block nhau
        platform_results = await asyncio.gather(*tasks)

        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1

        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interview completed: agent_id={agent_id}, successful platforms={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', 'Unknown error')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interview failed: agent_id={agent_id}, all platforms failed")
            return False

    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """
        Xử lý lệnh phỏng vấn hàng loạt (batch) — hiệu quả hơn gọi N lần.

        Chiến lược tối ưu: nhóm tất cả agent cùng platform thành 1 env.step() call,
        thay vì gọi env.step() riêng lẻ cho từng agent.
        → Giảm số lần call asyncio, tăng throughput.

        Phân nhóm:
        - platform="twitter" → twitter_interviews
        - platform="reddit"  → reddit_interviews
        - platform=None      → both_platforms_interviews → mở rộng vào cả 2 danh sách

        Mỗi nhóm được thực thi trong 1 env.step() call với dict {agent: ManualAction}.
        """
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []

        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                both_platforms_interviews.append(interview)

        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)

        results = {}

        # Xử lý Twitter batch — 1 env.step() cho tất cả agent Twitter
        if twitter_interviews and self.twitter_env:
            try:
                twitter_actions = {}
                for interview in twitter_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.twitter_agent_graph.get_agent(agent_id)
                        twitter_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  Warning: Cannot get Twitter Agent {agent_id}: {e}")

                if twitter_actions:
                    await self.twitter_env.step(twitter_actions)

                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "twitter")
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitter batch interview failed: {e}")

        # Xử lý Reddit batch — tương tự
        if reddit_interviews and self.reddit_env:
            try:
                reddit_actions = {}
                for interview in reddit_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.reddit_agent_graph.get_agent(agent_id)
                        reddit_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  Warning: Cannot get Reddit Agent {agent_id}: {e}")

                if reddit_actions:
                    await self.reddit_env.step(reddit_actions)

                    for interview in reddit_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "reddit")
                        result["platform"] = "reddit"
                        results[f"reddit_{agent_id}"] = result
            except Exception as e:
                print(f"  Reddit batch interview failed: {e}")

        if results:
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  Batch interview completed: {len(results)} agents")
            return True
        else:
            self.send_response(command_id, "failed", error="No successful interviews")
            return False

    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """
        Đọc kết quả interview mới nhất từ bảng `trace` trong SQLite.

        OASIS ghi kết quả ManualAction(INTERVIEW) vào bảng trace với action='interview'.
        Truy vấn ORDER BY created_at DESC LIMIT 1 → lấy bản ghi mới nhất.
        """
        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")

        result = {
            "agent_id": agent_id,
            "response": None,
            "timestamp": None
        }

        if not os.path.exists(db_path):
            return result

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT user_id, info, created_at
                FROM trace
                WHERE action = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (ActionType.INTERVIEW.value, agent_id))

            row = cursor.fetchone()
            if row:
                user_id, info_json, created_at = row
                try:
                    info = json.loads(info_json) if info_json else {}
                    result["response"] = info.get("response", info)
                    result["timestamp"] = created_at
                except json.JSONDecodeError:
                    result["response"] = info_json

            conn.close()

        except Exception as e:
            print(f"  Failed to read interview result: {e}")

        return result

    async def process_commands(self) -> bool:
        """
        Xử lý 1 lệnh đang chờ (nếu có).

        Được gọi trong vòng lặp chờ mỗi 0.5 giây.
        Dispatch theo command_type:
          "interview"       → handle_interview()
          "batch_interview" → handle_batch_interview()
          "close_env"       → ghi response → trả về False (thoát vòng lặp)

        Returns:
            True để tiếp tục vòng lặp, False để thoát (close_env hoặc unknown)
        """
        command = self.poll_command()
        if not command:
            return True

        command_id = command.get("command_id")
        command_type = command.get("command_type")
        args = command.get("args", {})

        print(f"\nReceived IPC command: {command_type}, id={command_id}")

        if command_type == CommandType.INTERVIEW:
            await self.handle_interview(
                command_id,
                args.get("agent_id", 0),
                args.get("prompt", ""),
                args.get("platform")
            )
            return True

        elif command_type == CommandType.BATCH_INTERVIEW:
            await self.handle_batch_interview(
                command_id,
                args.get("interviews", []),
                args.get("platform")
            )
            return True

        elif command_type == CommandType.CLOSE_ENV:
            print("Received close environment command")
            self.send_response(command_id, "completed", result={"message": "Environment will close soon"})
            return False  # Thoát vòng lặp chờ

        else:
            self.send_response(command_id, "failed", error=f"Unknown command type: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """Đọc simulation_config.json từ đường dẫn đã chỉ định."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==============================================================================
# Lọc action và ánh xạ tên
# ==============================================================================
# FILTERED_ACTIONS: các loại action không có giá trị phân tích — bỏ qua khi ghi log.
# refresh = agent "tải lại" feed (không tạo nội dung mới)
# sign_up = đăng ký tài khoản (chỉ xảy ra 1 lần lúc khởi tạo)
# ==============================================================================

FILTERED_ACTIONS = {'refresh', 'sign_up'}

# ACTION_TYPE_MAP: ánh xạ từ tên trong SQLite database của OASIS
# sang tên chuẩn viết hoa dùng trong actions.jsonl.
# OASIS lưu dạng lowercase trong DB (ví dụ: 'create_post'),
# nhưng actions.jsonl dùng UPPER_SNAKE_CASE ('CREATE_POST') để nhất quán.
ACTION_TYPE_MAP = {
    'create_post': 'CREATE_POST',
    'like_post': 'LIKE_POST',
    'dislike_post': 'DISLIKE_POST',
    'repost': 'REPOST',
    'quote_post': 'QUOTE_POST',
    'follow': 'FOLLOW',
    'mute': 'MUTE',
    'create_comment': 'CREATE_COMMENT',
    'like_comment': 'LIKE_COMMENT',
    'dislike_comment': 'DISLIKE_COMMENT',
    'search_posts': 'SEARCH_POSTS',
    'search_user': 'SEARCH_USER',
    'trend': 'TREND',
    'do_nothing': 'DO_NOTHING',
    'interview': 'INTERVIEW',
}


def get_agent_names_from_config(config: Dict[str, Any]) -> Dict[int, str]:
    """
    Lấy ánh xạ agent_id → entity_name từ simulation_config.json.

    OASIS mặc định dùng tên "Agent_0", "Agent_1", ... trong DB.
    Hàm này map agent_id sang tên thực thể (ví dụ: "Trần Văn An")
    để actions.jsonl hiển thị tên thật thay vì "Agent_0".

    Nếu config không có entry cho agent nào, phần code gọi hàm này
    sẽ fallback về tên OASIS mặc định của agent đó.
    """
    agent_names = {}
    agent_configs = config.get("agent_configs", [])

    for agent_config in agent_configs:
        agent_id = agent_config.get("agent_id")
        entity_name = agent_config.get("entity_name", f"Agent_{agent_id}")
        if agent_id is not None:
            agent_names[agent_id] = entity_name

    return agent_names


def fetch_new_actions_from_db(
    db_path: str,
    last_rowid: int,
    agent_names: Dict[int, str]
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Đọc các action MỚI từ SQLite database kể từ last_rowid.

    Tại sao dùng rowid thay vì created_at?
    Twitter lưu created_at dạng integer timestamp (Unix epoch).
    Reddit lưu created_at dạng ISO 8601 string.
    → So sánh/sort theo created_at không nhất quán giữa hai platform.
    rowid là integer auto-increment của SQLite — đơn giản và nhất quán.

    Chiến lược:
    1. SELECT WHERE rowid > last_rowid → chỉ lấy bản ghi MỚI
    2. Cập nhật last_rowid = rowid lớn nhất trong batch này
    3. Lần tiếp theo gọi lại với last_rowid mới → không đọc lại bản ghi cũ

    Mỗi action được enrich thêm context (nội dung bài viết, tên tác giả)
    bằng _enrich_action_context() để actions.jsonl có đủ thông tin.

    Args:
        db_path: Đường dẫn tệp SQLite
        last_rowid: rowid lớn nhất đã đọc lần trước (0 = lần đầu, đọc tất cả)
        agent_names: Ánh xạ agent_id → tên thật

    Returns:
        (actions_list, new_last_rowid)
    """
    actions = []
    new_last_rowid = last_rowid

    if not os.path.exists(db_path):
        return actions, new_last_rowid

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))

        for rowid, user_id, action, info_json in cursor.fetchall():
            new_last_rowid = rowid  # Cập nhật cursor cho lần tiếp theo

            # Bỏ qua action không có giá trị phân tích
            if action in FILTERED_ACTIONS:
                continue

            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}

            # Chỉ giữ các field quan trọng của action_args
            # (bỏ các field nội bộ của OASIS không cần thiết cho phân tích)
            simplified_args = {}
            if 'content' in action_args:
                simplified_args['content'] = action_args['content']
            if 'post_id' in action_args:
                simplified_args['post_id'] = action_args['post_id']
            if 'comment_id' in action_args:
                simplified_args['comment_id'] = action_args['comment_id']
            if 'quoted_id' in action_args:
                simplified_args['quoted_id'] = action_args['quoted_id']
            if 'new_post_id' in action_args:
                simplified_args['new_post_id'] = action_args['new_post_id']
            if 'follow_id' in action_args:
                simplified_args['follow_id'] = action_args['follow_id']
            if 'query' in action_args:
                simplified_args['query'] = action_args['query']
            if 'like_id' in action_args:
                simplified_args['like_id'] = action_args['like_id']
            if 'dislike_id' in action_args:
                simplified_args['dislike_id'] = action_args['dislike_id']

            action_type = ACTION_TYPE_MAP.get(action, action.upper())

            # Bổ sung context (nội dung bài/comment, tên tác giả) để log có nghĩa hơn
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)

            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })

        conn.close()
    except Exception as e:
        print(f"Failed to read actions from database: {e}")

    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """
    Bổ sung context vào action_args bằng cách join thêm thông tin từ DB.

    Tại sao cần enrich?
    OASIS ghi action_args dạng thô: {"post_id": 42} — không có nội dung bài.
    Khi đọc actions.jsonl để phân tích, cần biết agent đã like BÀI NÀO, ai viết.
    Enrich thêm post_content và post_author_name để log có ý nghĩa.

    Các loại được enrich:
    - LIKE/DISLIKE_POST → thêm nội dung bài + tên tác giả
    - REPOST → thêm nội dung + tác giả bài gốc
    - QUOTE_POST → thêm nội dung bài gốc + phần quote của agent
    - FOLLOW/MUTE → thêm tên người dùng được follow/mute
    - LIKE/DISLIKE_COMMENT → thêm nội dung comment + tên tác giả
    - CREATE_COMMENT → thêm nội dung bài được comment vào

    Lỗi trong enrich KHÔNG ngăn luồng chính — silently pass.
    """
    try:
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')

        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                cursor.execute("""
                    SELECT original_post_id FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    original_post_id = row[0]
                    original_info = _get_post_info(cursor, original_post_id, agent_names)
                    if original_info:
                        action_args['original_content'] = original_info.get('content', '')
                        action_args['original_author_name'] = original_info.get('author_name', '')

        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')

            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')

            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]

        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name

        elif action_type == 'MUTE':
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name

        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')

        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')

    except Exception as e:
        pass  # Enrich thất bại không ảnh hưởng luồng chính


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """Lấy {content, author_name} của một bài viết từ DB."""
    try:
        cursor.execute("""
            SELECT p.content, p.user_id, u.agent_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            WHERE p.post_id = ?
        """, (post_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]

            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''

            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def _get_user_name(
    cursor,
    user_id: int,
    agent_names: Dict[int, str]
) -> Optional[str]:
    """Lấy tên hiển thị của một user từ DB. Ưu tiên entity_name từ agent_names."""
    try:
        cursor.execute("""
            SELECT agent_id, name, user_name FROM user WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            agent_id = row[0]
            name = row[1]
            user_name = row[2]

            if agent_id is not None and agent_id in agent_names:
                return agent_names[agent_id]
            return name or user_name or ''
    except Exception:
        pass
    return None


def _get_comment_info(
    cursor,
    comment_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """Lấy {content, author_name} của một comment từ DB."""
    try:
        cursor.execute("""
            SELECT c.content, c.user_id, u.agent_id
            FROM comment c
            LEFT JOIN user u ON c.user_id = u.user_id
            WHERE c.comment_id = ?
        """, (comment_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]

            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''

            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def create_model(config: Dict[str, Any], use_boost: bool = False):
    """
    Tạo LLM model cho OASIS agent.

    Hỗ trợ 2 cấu hình LLM để tối ưu throughput khi chạy song song:
    - General LLM:  LLM_API_KEY + LLM_BASE_URL + LLM_MODEL_NAME
    - Boost LLM:    LLM_BOOST_API_KEY + LLM_BOOST_BASE_URL + LLM_BOOST_MODEL_NAME

    Twitter dùng General LLM (use_boost=False).
    Reddit dùng Boost LLM nếu có (use_boost=True), fallback về General nếu không.

    Lý do tách hai LLM: khi Twitter và Reddit chạy asyncio.gather song song,
    nếu cùng dùng 1 API key sẽ bị rate limit. Dùng 2 API key khác nhau (hoặc
    2 provider khác nhau) giúp tăng throughput gấp đôi.

    Validation:
    - API key không được là placeholder ("your_api_key_here")
    - Base URL phải bắt đầu bằng http:// hoặc https://
    - Nếu boost config không hợp lệ → in cảnh báo → fallback về general
    """
    def _is_placeholder(value: str) -> bool:
        v = (value or "").strip().lower()
        return v in {"your_api_key_here", "your_base_url_here", "your_model_name_here"}

    def _is_http_url(value: str) -> bool:
        v = (value or "").strip().lower()
        return v.startswith("http://") or v.startswith("https://")

    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = (
        bool(boost_api_key.strip())
        and bool(boost_model.strip())
        and bool(boost_base_url.strip())
        and not _is_placeholder(boost_api_key)
        and not _is_placeholder(boost_base_url)
        and not _is_placeholder(boost_model)
        and _is_http_url(boost_base_url)
    )

    if use_boost and has_boost_config:
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[Boost LLM]"
    else:
        if use_boost and not has_boost_config:
            print("[Boost LLM] Invalid or placeholder boost config, fallback to [General LLM].")
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[General LLM]"

    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")

    if llm_api_key:
        os.environ["OPENAI_API_KEY"] = llm_api_key

    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Missing API key config. Please set LLM_API_KEY in the project root .env file")

    if llm_base_url:
        if not _is_http_url(llm_base_url):
            raise ValueError(
                f"Invalid LLM base URL: {llm_base_url}. It must start with http:// or https://"
            )
        os.environ["OPENAI_API_BASE_URL"] = llm_base_url

    print(f"{config_label} model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else 'default'}...")

    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=llm_model,
        timeout=1000
    )


def configure_agent_memory_limits(agent_graph, token_limit=150000, message_window_size=25):
    """
    Cấu hình giới hạn memory cho tất cả agent trong agent_graph.

    OASIS tạo SocialAgent không truyền message_window_size hay token_limit
    cho ChatAgent (CAMEL), khiến conversation history tăng vô hạn qua các round.
    Khi context vượt quá giới hạn model (131072 tokens cho Qwen3.6-27B-FP8),
    LLM API trả về BadRequestError và agent bị bỏ qua round đó.

    Hàm này thay thế memory của mỗi agent bằng ChatHistoryMemory có:
    - token_limit: giới hạn token context (ScoreBasedContextCreator sẽ cắt bớt
      message cũ khi vượt, ưu tiên giữ message mới và system message)
    - message_window_size: giới hạn số message giữ lại (tầng bảo vệ thứ hai)

    ChatAgent.memory setter tự động gọi init_messages() để giữ system message.
    """
    configured_count = 0
    for agent_id, agent in agent_graph.get_agents():
        token_counter = OpenAITokenCounter(ModelType.GPT_4O_MINI)
        context_creator = ScoreBasedContextCreator(token_counter, token_limit=token_limit)
        new_memory = ChatHistoryMemory(context_creator, window_size=message_window_size)
        agent.memory = new_memory
        configured_count += 1

    return configured_count


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int
) -> List:
    """
    Quyết định agent nào được kích hoạt trong round hiện tại.

    Thuật toán 3 bước:

    Bước 1 — Tính số lượng agent cần kích hoạt:
      target_count = random(base_min, base_max) × activity_multiplier
      Trong đó:
        peak_hours     → multiplier = 1.5   (đông nhất, ví dụ 19-22h)
        off_peak_hours → multiplier = 0.05  (vắng nhất, ví dụ 0-5h)
        giờ khác       → multiplier = 1.0

    Bước 2 — Lọc agent ứng cử viên:
      Với mỗi agent trong agent_configs:
        - current_hour ∈ active_hours? → agent có thể hoạt động giờ này
        - random() < activity_level?   → agent "thức dậy" trong round này
      → Chỉ agent thỏa mãn CẢ HAI điều kiện mới vào candidates

    Bước 3 — Chọn ngẫu nhiên:
      random.sample(candidates, min(target_count, len(candidates)))
      → Đảm bảo không chọn nhiều hơn số candidates thực tế

    Kết quả: List[(agent_id, agent_object)] — agent_object để truyền vào env.step()
    """
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])

    base_min = time_config.get("agents_per_hour_min", 5)
    base_max = time_config.get("agents_per_hour_max", 20)

    peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])

    if current_hour in peak_hours:
        multiplier = time_config.get("peak_activity_multiplier", 1.5)
    elif current_hour in off_peak_hours:
        multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
    else:
        multiplier = 1.0

    target_count = int(random.uniform(base_min, base_max) * multiplier)

    # Lọc ứng cử viên: đúng giờ + random activity_level
    candidates = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        activity_level = cfg.get("activity_level", 0.5)

        if current_hour not in active_hours:
            continue

        if random.random() < activity_level:
            candidates.append(agent_id)

    # Chọn ngẫu nhiên từ danh sách ứng cử viên
    selected_ids = random.sample(
        candidates,
        min(target_count, len(candidates))
    ) if candidates else []

    # Lấy agent object từ env (để truyền vào env.step() sau đó)
    active_agents = []
    for agent_id in selected_ids:
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass

    return active_agents


class PlatformSimulation:
    """
    Container kết quả của một platform simulation.

    Được trả về bởi run_twitter_simulation() và run_reddit_simulation().
    env và agent_graph được giữ lại sau khi vòng lặp kết thúc
    để ParallelIPCHandler có thể dùng cho Interview.
    """
    def __init__(self):
        self.env = None             # OASIS environment object
        self.agent_graph = None     # Agent graph (dùng để get_agent(id))
        self.total_actions = 0      # Tổng số action đã ghi được


async def run_twitter_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """
    Khởi tạo và chạy simulation Twitter.

    Luồng chính:
    1. Tạo LLM model (General LLM)
    2. generate_twitter_agent_graph() — tải agent từ twitter_profiles.csv
    3. oasis.make() — tạo Twitter environment + SQLite DB
    4. env.reset() — khởi tạo environment
    5. Round 0: đăng initial_posts (ManualAction)
    6. Vòng lặp Round 1..N:
       a. get_active_agents_for_round() — chọn agent dựa trên giờ + activity_level
       b. env.step({agent: LLMAction()}) — OASIS cho agent LLM chọn action
       c. fetch_new_actions_from_db() — đọc action thực tế từ DB
       d. action_logger.log_action() — ghi vào twitter/actions.jsonl
    7. KHÔNG đóng env → env được giữ cho Interview

    Cơ chế đọc action từ DB (thay vì từ return value của env.step()):
    env.step() không trả về action_args đủ chi tiết.
    Sau mỗi round, đọc từ DB với last_rowid để lấy action MỚI.
    last_rowid được cập nhật sau mỗi lần đọc → không đọc lại bản ghi cũ.

    semaphore=3 trong oasis.make(): giới hạn số LLM call đồng thời trong 1 round
    → tránh bị rate limit API khi nhiều agent cùng gọi LLM.

    Args:
        config: Nội dung simulation_config.json
        simulation_dir: Thư mục chứa profile files và sẽ chứa output
        action_logger: Logger ghi ra twitter/actions.jsonl
        main_logger: Logger ghi ra simulation.log
        max_rounds: Giới hạn số round (None = chạy đủ theo config)

    Returns:
        PlatformSimulation với env và agent_graph còn sống
    """
    result = PlatformSimulation()

    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")

    log_info("Initializing...")

    # Twitter dùng General LLM (không dùng boost)
    model = create_model(config, use_boost=False)

    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"Error: Profile file not found: {profile_path}")
        return result

    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )

    # Cấu hình giới hạn memory để tránh context overflow (131072 token limit)
    mem_count = configure_agent_memory_limits(result.agent_graph)
    log_info(f"Configured memory limits for {mem_count} agents")

    # Xây dựng agent_names map — dùng cho log và enrich context
    agent_names = get_agent_names_from_config(config)
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')

    # Xóa DB cũ nếu còn từ lần chạy trước (cleanup_simulation_logs() nên đã xóa rồi,
    # nhưng xóa lần nữa ở đây để chắc chắn)
    db_path = os.path.join(simulation_dir, "twitter_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    twitter_channel = Channel()
    twitter_platform = Platform(
        db_path=db_path,
        channel=twitter_channel,
        recsys_type="reddit",       # score-based, không load model embedding → nhanh hơn twhin-bert
        refresh_rec_post_count=2,
        max_rec_post_len=2,
        following_post_count=3,
    )
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=twitter_platform,
        semaphore=20,
    )

    await result.env.reset()
    log_info("Environment started")

    if action_logger:
        action_logger.log_simulation_start(config)

    total_actions = 0
    last_rowid = 0  # Theo dõi rowid đã đọc → chỉ đọc bản ghi MỚI mỗi round

    # ── Round 0: Đăng initial_posts ───────────────────────────────────────────
    # Round 0 là round đặc biệt — không phải LLMAction mà là ManualAction.
    # Các bài đăng này tạo ra "tin nóng đầu tiên" để agent phản ứng từ round 1.
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])

    if action_logger:
        action_logger.log_round_start(0, 0)

    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                initial_actions[agent] = ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content}
                )

                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass

        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"Published {len(initial_actions)} initial posts")

    if action_logger:
        action_logger.log_round_end(0, initial_action_count)

    # ── Vòng lặp Round 1..N ───────────────────────────────────────────────────
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round

    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

    start_time = datetime.now()

    for round_num in range(total_rounds):
        # Kiểm tra tín hiệu thoát (SIGTERM/SIGINT) — thoát gracefully
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received shutdown signal, stop simulation at round {round_num + 1}")
            break

        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24   # 0-23 (giờ trong ngày)
        simulated_day = simulated_minutes // (60 * 24) + 1

        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )

        # Log round_start dù không có agent (giúp monitor thread track round đúng)
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)

        if not active_agents:
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue

        # Cho các agent chọn action (LLMAction = OASIS tự quyết định qua LLM)
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)

        # Đọc action thực tế từ DB (KHÔNG dùng return value của env.step())
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )

        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1

        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")

    # KHÔNG đóng env ở đây — giữ lại cho Interview IPC

    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)

    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! Elapsed: {elapsed:.1f}s, total actions: {total_actions}")

    return result


async def run_reddit_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """
    Khởi tạo và chạy simulation Reddit.

    Tương tự run_twitter_simulation() với 2 điểm khác biệt:

    1. Dùng Boost LLM (use_boost=True):
       Reddit và Twitter chạy asyncio.gather song song.
       Dùng API key khác nhau giúp tránh rate limit và tăng throughput.

    2. Xử lý initial_posts phức tạp hơn:
       OASIS Reddit cho phép 1 agent đăng nhiều bài trong initial_posts.
       Nếu cùng agent được assign nhiều initial_posts, initial_actions[agent]
       trở thành List[ManualAction] thay vì ManualAction đơn lẻ.
       (Twitter không hỗ trợ điều này — chỉ 1 action/agent/step)
    """
    result = PlatformSimulation()

    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")

    log_info("Initializing...")

    # Reddit dùng Boost LLM (fallback về General nếu không có config boost)
    model = create_model(config, use_boost=True)

    profile_path = os.path.join(simulation_dir, "reddit_profiles.json")
    if not os.path.exists(profile_path):
        log_info(f"Error: Profile file not found: {profile_path}")
        return result

    result.agent_graph = await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=REDDIT_ACTIONS,
    )

    # Cấu hình giới hạn memory để tránh context overflow (131072 token limit)
    mem_count = configure_agent_memory_limits(result.agent_graph)
    log_info(f"Configured memory limits for {mem_count} agents")

    agent_names = get_agent_names_from_config(config)
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')

    db_path = os.path.join(simulation_dir, "reddit_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
        semaphore=20,
    )

    await result.env.reset()
    log_info("Environment started")

    if action_logger:
        action_logger.log_simulation_start(config)

    total_actions = 0
    last_rowid = 0

    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])

    if action_logger:
        action_logger.log_round_start(0, 0)

    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                # Reddit cho phép nhiều ManualAction/agent → dùng List nếu cần
                if agent in initial_actions:
                    if not isinstance(initial_actions[agent], list):
                        initial_actions[agent] = [initial_actions[agent]]
                    initial_actions[agent].append(ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    ))
                else:
                    initial_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )

                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass

        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"Published {len(initial_actions)} initial posts")

    if action_logger:
        action_logger.log_round_end(0, initial_action_count)

    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round

    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

    start_time = datetime.now()

    for round_num in range(total_rounds):
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received shutdown signal, stop simulation at round {round_num + 1}")
            break

        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1

        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )

        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)

        if not active_agents:
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue

        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)

        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )

        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1

        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")

    # KHÔNG đóng env — giữ lại cho Interview

    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)

    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! Elapsed: {elapsed:.1f}s, total actions: {total_actions}")

    return result


async def main():
    parser = argparse.ArgumentParser(description='OASIS dual-platform parallel simulation')
    parser.add_argument('--config', type=str, required=True,
                        help='Path to config file (simulation_config.json)')
    parser.add_argument('--twitter-only', action='store_true',
                        help='Run Twitter simulation only')
    parser.add_argument('--reddit-only', action='store_true',
                        help='Run Reddit simulation only')
    parser.add_argument('--max-rounds', type=int, default=None,
                        help='Maximum simulation rounds (optional, used to truncate long simulations)')
    parser.add_argument('--no-wait', action='store_true', default=False,
                        help='Close environment immediately after simulation, do not enter command wait mode')

    args = parser.parse_args()

    # Khởi tạo shutdown event — dùng để phối hợp graceful shutdown
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    # wait_for_commands=True: sau simulation, vào chế độ chờ lệnh IPC (Interview)
    # wait_for_commands=False (--no-wait): đóng ngay — dùng khi test hoặc không cần Interview
    wait_for_commands = not args.no_wait

    install_openai_cost_patch(
        simulation_id=config.get("simulation_id"),
        project_id=config.get("project_id"),
        platform="parallel",
        component="scripts.run_parallel_simulation",
        phase="simulation_run",
    )

    init_logging_for_simulation(simulation_dir)

    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()

    log_manager.info("=" * 60)
    log_manager.info("OASIS dual-platform parallel simulation")
    log_manager.info(f"Config file: {args.config}")
    log_manager.info(f"Simulation ID: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"Command wait mode: {'enabled' if wait_for_commands else 'disabled'}")
    log_manager.info("=" * 60)

    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 30)
    config_total_rounds = (total_hours * 60) // minutes_per_round

    log_manager.info(f"Simulation parameters:")
    log_manager.info(f"  - Total simulation duration: {total_hours} hours")
    log_manager.info(f"  - Minutes per round: {minutes_per_round}")
    log_manager.info(f"  - Total configured rounds: {config_total_rounds}")
    if args.max_rounds:
        log_manager.info(f"  - Max rounds limit: {args.max_rounds}")
        if args.max_rounds < config_total_rounds:
            log_manager.info(f"  - Actual executed rounds: {args.max_rounds} (truncated)")
    log_manager.info(f"  - Agent count: {len(config.get('agent_configs', []))}")

    log_manager.info("Log structure:")
    log_manager.info(f"  - Main log: simulation.log")
    log_manager.info(f"  - Twitter actions: twitter/actions.jsonl")
    log_manager.info(f"  - Reddit actions: reddit/actions.jsonl")
    log_manager.info("=" * 60)

    start_time = datetime.now()

    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None

    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds)
    else:
        # Chạy song song — asyncio.gather chạy cả 2 coroutine trong cùng event loop
        # Twitter dùng General LLM, Reddit dùng Boost LLM → hai API key khác nhau
        # → không tranh nhau rate limit, throughput tăng đôi
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds),
        )
        twitter_result, reddit_result = results

    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"Simulation loop completed! Total elapsed: {total_elapsed:.1f}s")

    # ── Chế độ chờ lệnh IPC ───────────────────────────────────────────────────
    # Sau khi simulation xong, environment vẫn còn sống.
    # Vào vòng lặp poll ipc_commands/ mỗi 0.5 giây.
    # Thoát khi: nhận close_env command, SIGTERM/SIGINT, hoặc exception.
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("Entering command wait mode - environment stays running")
        log_manager.info("Supported commands: interview, batch_interview, close_env")
        log_manager.info("=" * 60)

        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        # Ghi env_status.json → Flask biết có thể gửi IPC command
        ipc_handler.update_status("alive")

        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # asyncio.wait_for thay vì sleep — có thể interrupt ngay khi nhận signal
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # Nhận signal → thoát
                except asyncio.TimeoutError:
                    pass  # Timeout thì tiếp tục poll
        except KeyboardInterrupt:
            print("\nInterrupt signal received")
        except asyncio.CancelledError:
            print("\nTask cancelled")
        except Exception as e:
            print(f"\nCommand processing error: {e}")

        log_manager.info("\nClosing environment...")
        ipc_handler.update_status("stopped")  # Flask biết environment đã đóng

    # Đóng environment sau khi thoát chế độ chờ (hoặc --no-wait)
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] Environment closed")

    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] Environment closed")

    log_manager.info("=" * 60)
    log_manager.info(f"All done!")
    log_manager.info(f"Log files:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """
    Thiết lập signal handler cho SIGTERM và SIGINT.

    Chiến lược 2 bước (thay vì sys.exit() ngay):
      Lần nhận signal đầu tiên:
        _shutdown_event.set() → thông báo vòng lặp asyncio thoát
        Cho chương trình cơ hội dọn tài nguyên (đóng DB, env...)
        Không gọi sys.exit() ngay

      Lần nhận signal thứ hai (người dùng ép thoát):
        sys.exit(1) → force quit ngay lập tức

    Tại sao không gọi sys.exit() ngay lần đầu?
    asyncio event loop cần được thông báo gracefully để:
    1. Hoàn thành các coroutine đang chạy
    2. Đóng SQLite connections đúng cách
    3. Ghi simulation_end event vào actions.jsonl
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\nReceived {sig_name}, shutting down...")

        if not _cleanup_done:
            _cleanup_done = True
            # Thông báo asyncio event loop thoát gracefully
            if _shutdown_event:
                _shutdown_event.set()
        else:
            # Nhận signal lần 2 → force exit
            print("Force exit...")
            sys.exit(1)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted")
    except SystemExit:
        pass
    finally:
        # Dọn resource tracker của multiprocessing — tránh warning khi thoát
        # trên một số hệ thống Python/OS kết hợp nhất định
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("Simulation process exited")
