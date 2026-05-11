"""
Kịch bản mô phỏng song song hai nền tảng OASIS
Chạy đồng thời mô phỏng Twitter và Reddit, đọc cùng một tệp cấu hình

Tính năng:
- Mô phỏng song song hai nền tảng (Twitter + Reddit)
- Không đóng môi trường ngay sau khi hoàn tất mô phỏng, chuyển sang chế độ chờ lệnh
- Hỗ trợ nhận lệnh Interview qua IPC
- Hỗ trợ phỏng vấn một Agent và phỏng vấn hàng loạt
- Hỗ trợ lệnh đóng môi trường từ xa

Cách dùng:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # Đóng ngay sau khi hoàn tất
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

Cấu trúc log:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Log hành động nền tảng Twitter
    ├── reddit/
    │   └── actions.jsonl    # Log hành động nền tảng Reddit
    ├── simulation.log       # Log tiến trình mô phỏng chính
    └── run_state.json       # Trạng thái chạy (cho API truy vấn)
"""

# ============================================================
# Khắc phục vấn đề mã hóa trên Windows: đặt UTF-8 trước mọi import
# Mục tiêu là sửa lỗi thư viện OASIS bên thứ ba đọc file mà không chỉ định encoding
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # Đặt mã hóa I/O mặc định của Python là UTF-8
    # Thiết lập này ảnh hưởng đến mọi lời gọi open() không chỉ định encoding
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    # Cấu hình lại stdout/stderr sang UTF-8 (tránh lỗi hiển thị ký tự tiếng Trung trên console)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # Ép đặt mã hóa mặc định (ảnh hưởng encoding mặc định của open())
    # Lưu ý: tốt nhất cần thiết lập khi Python khởi động, thiết lập lúc runtime có thể không hiệu quả
    # Vì vậy cần monkey-patch thêm hàm open tích hợp
    import builtins
    _original_open = builtins.open
    
    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None, 
                   newline=None, closefd=True, opener=None):
        """
        Wrapper cho hàm open(), mặc định dùng UTF-8 cho chế độ văn bản
        Điều này giúp sửa lỗi thư viện bên thứ ba (như OASIS) đọc file không chỉ định encoding
        """
        # Chỉ đặt encoding mặc định cho chế độ văn bản (không phải binary) khi chưa chỉ định encoding
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


# Biến toàn cục dùng cho xử lý tín hiệu
_shutdown_event = None
_cleanup_done = False

# Thêm thư mục backend vào sys.path
# Script nằm cố định trong thư mục backend/scripts/
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# Tải tệp .env ở thư mục gốc dự án (chứa các cấu hình như LLM_API_KEY)
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
    print(f"Environment config loaded: {_env_file}")
else:
    # Thử tải backend/.env
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"Environment config loaded: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """Lọc cảnh báo max_tokens của camel-ai (chủ động không đặt max_tokens để model tự quyết định)"""
    
    def filter(self, record):
        # Lọc log cảnh báo liên quan đến max_tokens
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# Thêm filter ngay khi module được nạp để bảo đảm có hiệu lực trước khi mã camel chạy
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    Tắt log chi tiết của thư viện OASIS
    Log của OASIS quá dài dòng (ghi từng quan sát và hành động của agent), ở đây dùng action_logger riêng
    """
    # Tắt toàn bộ logger của OASIS
    oasis_loggers = [
        "social.agent",
        "social.twitter", 
        "social.rec",
        "oasis.env",
        "table",
    ]
    
    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # Chỉ ghi lỗi nghiêm trọng
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """
    Khởi tạo cấu hình log cho mô phỏng
    
    Args:
        simulation_dir: Đường dẫn thư mục mô phỏng
    """
    # Tắt log chi tiết của OASIS
    disable_oasis_logging()
    
    # Dọn thư mục log cũ (nếu tồn tại)
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger
from llm_cost_patch import install_openai_cost_patch

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
        generate_reddit_agent_graph
    )
except ImportError as e:
    print(f"Error: Missing dependency {e}")
    print("Please install first: pip install oasis-ai camel-ai")
    sys.exit(1)


# Action khả dụng trên Twitter (không gồm INTERVIEW; INTERVIEW chỉ kích hoạt thủ công qua ManualAction)
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

# Action khả dụng trên Reddit (không gồm INTERVIEW; INTERVIEW chỉ kích hoạt thủ công qua ManualAction)
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


# Hằng số liên quan đến IPC
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """Hằng số loại lệnh"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """
    Bộ xử lý lệnh IPC cho hai nền tảng
    
    Quản lý môi trường của cả hai nền tảng và xử lý lệnh Interview
    """
    
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
        
        # Đảm bảo thư mục tồn tại
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """Cập nhật trạng thái môi trường"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "twitter_available": self.twitter_env is not None,
                "reddit_available": self.reddit_env is not None,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """Poll để lấy lệnh đang chờ xử lý"""
        if not os.path.exists(self.commands_dir):
            return None
        
        # Lấy tệp lệnh (sắp xếp theo thời gian)
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))
        
        command_files.sort(key=lambda x: x[1])
        
        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
        
        return None
    
    def send_response(self, command_id: str, status: str, result: Dict = None, error: str = None):
        """Gửi phản hồi"""
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
        
        # Xóa tệp lệnh
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def _get_env_and_graph(self, platform: str):
        """
        Lấy env và agent_graph của nền tảng được chỉ định
        
        Args:
            platform: Tên nền tảng ("twitter" hoặc "reddit")
            
        Returns:
            (env, agent_graph, platform_name) hoặc (None, None, None)
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        Thực thi Interview trên một nền tảng
        
        Returns:
            Dictionary chứa kết quả hoặc lỗi
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
            await env.step(actions)
            
            result = self._get_interview_result(agent_id, actual_platform)
            result["platform"] = actual_platform
            return result
            
        except Exception as e:
            return {"platform": platform, "error": str(e)}
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str, platform: str = None) -> bool:
        """
        Xử lý lệnh phỏng vấn một Agent
        
        Args:
            command_id: ID lệnh
            agent_id: Agent ID
            prompt: Câu hỏi phỏng vấn
            platform: Nền tảng chỉ định (tùy chọn)
                - "twitter": Chỉ phỏng vấn trên Twitter
                - "reddit": Chỉ phỏng vấn trên Reddit
                - None/không chỉ định: Phỏng vấn đồng thời cả hai nền tảng, trả kết quả gộp
            
        Returns:
            True là thành công, False là thất bại
        """
        # Nếu có chỉ định nền tảng, chỉ phỏng vấn trên nền tảng đó
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
        
        # Không chỉ định nền tảng: phỏng vấn đồng thời hai nền tảng
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="No simulation environment available")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # Phỏng vấn song song hai nền tảng
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # Chạy song song
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
        Xử lý lệnh phỏng vấn hàng loạt
        
        Args:
            command_id: ID lệnh
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: Nền tảng mặc định (có thể bị ghi đè ở từng mục interview)
                - "twitter": Chỉ phỏng vấn Twitter
                - "reddit": Chỉ phỏng vấn Reddit
                - None/không chỉ định: Mỗi Agent được phỏng vấn trên cả hai nền tảng
        """
        # Nhóm theo nền tảng
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # Cần phỏng vấn đồng thời hai nền tảng
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # Không chỉ định nền tảng: phỏng vấn cả hai nền tảng
                both_platforms_interviews.append(interview)
        
        # Tách both_platforms_interviews vào hai nền tảng
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # Xử lý phỏng vấn trên nền tảng Twitter
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
        
        # Xử lý phỏng vấn trên nền tảng Reddit
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
        """Lấy kết quả Interview mới nhất từ cơ sở dữ liệu"""
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
            
            # Truy vấn bản ghi Interview mới nhất
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
        Xử lý tất cả lệnh đang chờ
        
        Returns:
            True để tiếp tục chạy, False để thoát
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
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"Unknown command type: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """Tải tệp cấu hình"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# Các loại action không cốt lõi cần lọc (giá trị phân tích thấp)
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# Bảng ánh xạ loại action (tên trong DB -> tên chuẩn)
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
    Lấy ánh xạ agent_id -> entity_name từ simulation_config
    
    Mục tiêu là hiển thị tên thực thể thật trong actions.jsonl thay vì mã như "Agent_0"
    
    Args:
        config: Nội dung của simulation_config.json
        
    Returns:
        Dictionary ánh xạ agent_id -> entity_name
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
    Lấy bản ghi action mới từ DB và bổ sung ngữ cảnh đầy đủ
    
    Args:
        db_path: Đường dẫn tệp cơ sở dữ liệu
        last_rowid: Giá trị rowid lớn nhất đã đọc trước đó (dùng rowid thay vì created_at vì định dạng created_at khác nhau giữa nền tảng)
        agent_names: Ánh xạ agent_id -> agent_name
        
    Returns:
        (actions_list, new_last_rowid)
        - actions_list: Danh sách action, mỗi phần tử gồm agent_id, agent_name, action_type, action_args (có ngữ cảnh)
        - new_last_rowid: Giá trị rowid lớn nhất mới
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Dùng rowid để theo dõi bản ghi đã xử lý (rowid là trường tự tăng tích hợp của SQLite)
        # Cách này tránh vấn đề khác biệt định dạng created_at (Twitter dùng số nguyên, Reddit dùng chuỗi datetime)
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # Cập nhật rowid lớn nhất
            new_last_rowid = rowid
            
            # Lọc action không cốt lõi
            if action in FILTERED_ACTIONS:
                continue
            
            # Parse tham số action
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # Tinh gọn action_args, chỉ giữ trường quan trọng (giữ nguyên nội dung, không cắt)
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
            
            # Chuyển tên loại action
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # Bổ sung ngữ cảnh (nội dung bài viết, tên người dùng...)
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
    Bổ sung ngữ cảnh cho action (nội dung bài viết, tên người dùng...)
    
    Args:
        cursor: DB cursor
        action_type: Loại action
        action_args: Tham số action (sẽ bị cập nhật)
        agent_names: Ánh xạ agent_id -> agent_name
    """
    try:
        # Like/dislike bài viết: bổ sung nội dung bài và tác giả
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # Repost: bổ sung nội dung và tác giả bài gốc
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # original_post_id của bài repost trỏ đến bài gốc
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
        
        # Quote post: bổ sung nội dung bài gốc, tác giả và phần quote
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # Lấy nội dung quote của bài trích dẫn (quote_content)
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # Follow user: bổ sung tên người dùng được follow
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # Lấy followee_id từ bảng follow
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # Mute user: bổ sung tên người dùng bị mute
        elif action_type == 'MUTE':
            # Lấy user_id hoặc target_id từ action_args
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # Like/dislike comment: bổ sung nội dung comment và tác giả
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # Create comment: bổ sung thông tin bài viết được bình luận
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # Bổ sung ngữ cảnh thất bại không ảnh hưởng luồng chính
        print(f"Failed to enrich action context: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    Lấy thông tin bài viết
    
    Args:
        cursor: DB cursor
        post_id: Post ID
        agent_names: Ánh xạ agent_id -> agent_name
        
    Returns:
        Dictionary chứa content và author_name, hoặc None
    """
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
            
            # Ưu tiên dùng tên từ agent_names
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Lấy tên từ bảng user
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
    """
    Lấy tên người dùng
    
    Args:
        cursor: DB cursor
        user_id: User ID
        agent_names: Ánh xạ agent_id -> agent_name
        
    Returns:
        Tên người dùng, hoặc None
    """
    try:
        cursor.execute("""
            SELECT agent_id, name, user_name FROM user WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            agent_id = row[0]
            name = row[1]
            user_name = row[2]
            
            # Ưu tiên dùng tên từ agent_names
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
    """
    Lấy thông tin bình luận
    
    Args:
        cursor: DB cursor
        comment_id: Comment ID
        agent_names: Ánh xạ agent_id -> agent_name
        
    Returns:
        Dictionary chứa content và author_name, hoặc None
    """
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
            
            # Ưu tiên dùng tên từ agent_names
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Lấy tên từ bảng user
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
    Tạo mô hình LLM
    
    Hỗ trợ cấu hình hai LLM để tăng tốc khi mô phỏng song song:
    - Cấu hình chung: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
    - Cấu hình tăng tốc (tùy chọn): LLM_BOOST_API_KEY, LLM_BOOST_BASE_URL, LLM_BOOST_MODEL_NAME
    
    Nếu có cấu hình LLM tăng tốc, mỗi nền tảng có thể dùng nhà cung cấp API khác nhau để tăng khả năng song song.
    
    Args:
        config: Dictionary cấu hình mô phỏng
        use_boost: Có dùng cấu hình LLM tăng tốc hay không (nếu khả dụng)
    """
    def _is_placeholder(value: str) -> bool:
        v = (value or "").strip().lower()
        return v in {"your_api_key_here", "your_base_url_here", "your_model_name_here"}

    def _is_http_url(value: str) -> bool:
        v = (value or "").strip().lower()
        return v.startswith("http://") or v.startswith("https://")

    # Kiểm tra có cấu hình tăng tốc hợp lệ không
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
    
    # Chọn LLM theo tham số và trạng thái cấu hình
    if use_boost and has_boost_config:
        # Dùng cấu hình tăng tốc
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[Boost LLM]"
    else:
        # Dùng cấu hình chung
        if use_boost and not has_boost_config:
            print("[Boost LLM] Invalid or placeholder boost config, fallback to [General LLM].")
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[General LLM]"
    
    # Nếu .env không có model name, dùng config làm phương án dự phòng
    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")
    
    # Thiết lập biến môi trường cần thiết cho camel-ai
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


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int
) -> List:
    """Quyết định Agent nào được kích hoạt trong round hiện tại dựa trên thời gian và cấu hình"""
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
    
    candidates = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        activity_level = cfg.get("activity_level", 0.5)
        
        if current_hour not in active_hours:
            continue
        
        if random.random() < activity_level:
            candidates.append(agent_id)
    
    selected_ids = random.sample(
        candidates, 
        min(target_count, len(candidates))
    ) if candidates else []
    
    active_agents = []
    for agent_id in selected_ids:
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass
    
    return active_agents


class PlatformSimulation:
    """Container kết quả mô phỏng theo nền tảng"""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0


async def run_twitter_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """Chạy mô phỏng Twitter
    
    Args:
        config: Cấu hình mô phỏng
        simulation_dir: Thư mục mô phỏng
        action_logger: Logger hành động
        main_logger: Trình quản lý log chính
        max_rounds: Số round tối đa (tùy chọn, dùng để cắt ngắn mô phỏng quá dài)
        
    Returns:
        PlatformSimulation: Đối tượng kết quả chứa env và agent_graph
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")
    
    log_info("Initializing...")
    
    # Twitter dùng cấu hình LLM chung
    model = create_model(config, use_boost=False)
    
    # OASIS Twitter dùng định dạng CSV
    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"Error: Profile file not found: {profile_path}")
        return result
    
    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )
    
    # Lấy ánh xạ tên thật của Agent từ config (dùng entity_name thay vì Agent_X mặc định)
    agent_names = get_agent_names_from_config(config)
    # Nếu config không có Agent nào đó thì dùng tên mặc định của OASIS
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')
    
    db_path = os.path.join(simulation_dir, "twitter_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.TWITTER,
        database_path=db_path,
        semaphore=3,  # Giới hạn số request LLM đồng thời để tránh quá tải API
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # Theo dõi row đã xử lý cuối cùng trong DB (dùng rowid để tránh khác biệt định dạng created_at)
    
    # Thực thi sự kiện khởi tạo
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Ghi log bắt đầu round 0 (giai đoạn sự kiện khởi tạo)
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
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
    
    # Ghi log kết thúc round 0
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Vòng lặp mô phỏng chính
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # Nếu chỉ định max rounds thì cắt ngắn
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # Kiểm tra có nhận tín hiệu thoát không
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
        
        # Dù có Agent hoạt động hay không, vẫn ghi log bắt đầu round
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # Không có Agent hoạt động thì vẫn ghi log kết thúc round (actions_count=0)
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # Lấy action thực tế đã chạy từ DB và ghi log
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
    
    # Lưu ý: Không đóng environment, giữ lại để dùng cho Interview
    
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
    """Chạy mô phỏng Reddit
    
    Args:
        config: Cấu hình mô phỏng
        simulation_dir: Thư mục mô phỏng
        action_logger: Logger hành động
        main_logger: Trình quản lý log chính
        max_rounds: Số round tối đa (tùy chọn, dùng để cắt ngắn mô phỏng quá dài)
        
    Returns:
        PlatformSimulation: Đối tượng kết quả chứa env và agent_graph
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")
    
    log_info("Initializing...")
    
    # Reddit dùng cấu hình LLM tăng tốc (nếu có, nếu không thì fallback về cấu hình chung)
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
    
    # Lấy ánh xạ tên thật của Agent từ config (dùng entity_name thay vì Agent_X mặc định)
    agent_names = get_agent_names_from_config(config)
    # Nếu config không có Agent nào đó thì dùng tên mặc định của OASIS
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
        semaphore=3,  # Giới hạn số request LLM đồng thời để tránh quá tải API
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # Theo dõi row đã xử lý cuối cùng trong DB (dùng rowid để tránh khác biệt định dạng created_at)
    
    # Thực thi sự kiện khởi tạo
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Ghi log bắt đầu round 0 (giai đoạn sự kiện khởi tạo)
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
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
    
    # Ghi log kết thúc round 0
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Vòng lặp mô phỏng chính
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # Nếu chỉ định max rounds thì cắt ngắn
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # Kiểm tra có nhận tín hiệu thoát không
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
        
        # Dù có Agent hoạt động hay không, vẫn ghi log bắt đầu round
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # Không có Agent hoạt động thì vẫn ghi log kết thúc round (actions_count=0)
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # Lấy action thực tế đã chạy từ DB và ghi log
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
    
    # Lưu ý: Không đóng environment, giữ lại để dùng cho Interview
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! Elapsed: {elapsed:.1f}s, total actions: {total_actions}")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description='OASIS dual-platform parallel simulation')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='Path to config file (simulation_config.json)'
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='Run Twitter simulation only'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='Run Reddit simulation only'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='Maximum simulation rounds (optional, used to truncate long simulations)'
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='Close environment immediately after simulation, do not enter command wait mode'
    )
    
    args = parser.parse_args()
    
    # Tạo shutdown event khi vào main để toàn bộ chương trình có thể phản hồi tín hiệu thoát
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)
    
    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    wait_for_commands = not args.no_wait

    install_openai_cost_patch(
        simulation_id=config.get("simulation_id"),
        project_id=config.get("project_id"),
        platform="parallel",
        component="scripts.run_parallel_simulation",
        phase="simulation_run",
    )
    
    # Khởi tạo cấu hình log (tắt log OASIS, dọn file cũ)
    init_logging_for_simulation(simulation_dir)
    
    # Tạo trình quản lý log
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
    
    # Lưu kết quả mô phỏng của hai nền tảng
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds)
    else:
        # Chạy song song (mỗi nền tảng dùng logger riêng)
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds),
        )
        twitter_result, reddit_result = results
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"Simulation loop completed! Total elapsed: {total_elapsed:.1f}s")
    
    # Có vào chế độ chờ lệnh hay không
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("Entering command wait mode - environment stays running")
        log_manager.info("Supported commands: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # Tạo bộ xử lý IPC
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")
        
        # Vòng lặp chờ lệnh (dùng _shutdown_event toàn cục)
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # Dùng wait_for thay cho sleep để có thể phản hồi shutdown_event
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # Đã nhận tín hiệu thoát
                except asyncio.TimeoutError:
                    pass  # Timeout thì tiếp tục vòng lặp
        except KeyboardInterrupt:
            print("\nInterrupt signal received")
        except asyncio.CancelledError:
            print("\nTask cancelled")
        except Exception as e:
            print(f"\nCommand processing error: {e}")
        
        log_manager.info("\nClosing environment...")
        ipc_handler.update_status("stopped")
    
    # Đóng environment
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
    Thiết lập signal handler để thoát đúng cách khi nhận SIGTERM/SIGINT
    
    Kịch bản mô phỏng bền vững: không thoát ngay sau khi mô phỏng xong, tiếp tục chờ lệnh interview
    Khi nhận tín hiệu dừng, cần:
    1. Thông báo vòng lặp asyncio thoát khỏi trạng thái chờ
    2. Cho chương trình cơ hội dọn tài nguyên đúng cách (đóng DB, environment...)
    3. Sau đó mới thoát
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\nReceived {sig_name}, shutting down...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # Set event để thông báo vòng lặp asyncio thoát (để kịp dọn tài nguyên)
            if _shutdown_event:
                _shutdown_event.set()
        
        # Không gọi sys.exit() ngay, để asyncio thoát tự nhiên và dọn tài nguyên
        # Nếu nhận tín hiệu lặp lại thì mới ép thoát
        else:
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
        # Dọn resource tracker của multiprocessing (tránh cảnh báo khi thoát)
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("Simulation process exited")
