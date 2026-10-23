"""
OASIS 双平台并行模拟预设脚本
同时运行Twitter和Reddit模拟，读取相同的配置文件

功能特性:
- 双平台（Twitter + Reddit）并行模拟
- 完成模拟后不立即关闭环境，进入等待命令模式
- 支持通过IPC接收Interview命令
- 支持单个Agent采访和批量采访
- 支持远程关闭环境命令

使用方式:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # 完成后立即关闭
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

日志结构:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter 平台动作日志
    ├── reddit/
    │   └── actions.jsonl    # Reddit 平台动作日志
    ├── simulation.log       # 主模拟进程日志
    └── run_state.json       # 运行状态（API 查询用）
"""

# ============================================================
# 解决 Windows 编码问题：在所有 import 之前设置 UTF-8 编码
# 这是为了修复 OASIS 第三方库读取文件时未指定编码的问题
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # 设置 Python 默认 I/O 编码为 UTF-8
    # 这会影响所有未指定编码的 open() 调用
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    # 重新配置标准输出流为 UTF-8（解决控制台中文乱码）
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # 强制设置默认编码（影响 open() 函数的默认编码）
    # 注意：这需要在 Python 启动时就设置，运行时设置可能不生效
    # 所以我们还需要 monkey-patch 内置的 open 函数
    import builtins
    _original_open = builtins.open
    
    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None, 
                   newline=None, closefd=True, opener=None):
        """
        包装 open() 函数，对于文本模式默认使用 UTF-8 编码
        这可以修复第三方库（如 OASIS）读取文件时未指定编码的问题
        """
        # 只对文本模式（非二进制）且未指定编码的情况设置默认编码
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
import secrets
import signal
import sqlite3
import time
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


# 全局变量：用于信号处理
_shutdown_event = None
_cleanup_done = False

# 添加 backend 目录到路径
# 脚本固定位于 backend/scripts/ 目录
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# 加载项目根目录的 .env 文件（包含 LLM_API_KEY 等配置）
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
    print(f"已加载环境配置: {_env_file}")
else:
    # 尝试加载 backend/.env
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"已加载环境配置: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """过滤掉 camel-ai 关于 max_tokens 的警告（我们故意不设置 max_tokens，让模型自行决定）"""
    
    def filter(self, record):
        # 过滤掉包含 max_tokens 警告的日志
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# 在模块加载时立即添加过滤器，确保在 camel 代码执行前生效
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    禁用 OASIS 库的详细日志输出
    OASIS 的日志太冗余（记录每个 agent 的观察和动作），我们使用自己的 action_logger
    """
    # 禁用 OASIS 的所有日志器
    oasis_loggers = [
        "social.agent",
        "social.twitter", 
        "social.rec",
        "oasis.env",
        "table",
    ]
    
    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # 只记录严重错误
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """
    初始化模拟的日志配置
    
    Args:
        simulation_dir: 模拟目录路径
    """
    # 禁用 OASIS 的详细日志
    disable_oasis_logging()
    
    # 清理旧的 log 目录（如果存在）
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger
import sim_behavior
import sim_resume
import sim_runtime

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
    from oasis.social_agent.agent import SocialAgent
except ImportError as e:
    print(f"错误: 缺少依赖 {e}")
    print("请先安装: pip install oasis-ai camel-ai")
    sys.exit(1)

# OASIS swallows a failed model call (it logs it and returns the exception), so the round loop would only
# see an agent that did nothing. Track those failures so the UI can tell the user why nothing happens.
sim_runtime.install_failure_tracking(SocialAgent)


# Twitter可用动作（不包含INTERVIEW，INTERVIEW只能通过ManualAction手动触发）
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

# Reddit可用动作（不包含INTERVIEW，INTERVIEW只能通过ManualAction手动触发）
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


# IPC相关常量
MAX_CONSECUTIVE_STEP_FAILURES = 5  # env.step errors in a row before a platform gives up

IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """命令类型常量"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """
    双平台IPC命令处理器
    
    管理两个平台的环境，处理Interview命令
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
        
        # 确保目录存在
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """更新环境状态"""
        payload = {
            "status": status,
            "twitter_available": self.twitter_env is not None,
            "reddit_available": self.reddit_env is not None,
            "timestamp": datetime.now().isoformat()
        }
        # write-then-rename so the backend never reads a half-written file
        temp_file = self.status_file + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        for attempt in range(5):
            try:
                os.replace(temp_file, self.status_file)
                break
            except PermissionError:  # Windows: the reader has the file open for a moment
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """轮询获取待处理命令"""
        if not os.path.exists(self.commands_dir):
            return None
        
        # 获取命令文件（按时间排序）
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
        """发送响应"""
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
        
        # 删除命令文件
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def _get_env_and_graph(self, platform: str):
        """
        获取指定平台的环境和agent_graph
        
        Args:
            platform: 平台名称 ("twitter" 或 "reddit")
            
        Returns:
            (env, agent_graph, platform_name) 或 (None, None, None)
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        在单个平台上执行Interview
        
        Returns:
            包含结果的字典，或包含error的字典
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)
        
        if not env or not agent_graph:
            return {"platform": platform, "error": f"{platform}平台不可用"}
        
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
        处理单个Agent采访命令
        
        Args:
            command_id: 命令ID
            agent_id: Agent ID
            prompt: 采访问题
            platform: 指定平台（可选）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None/不指定: 同时采访两个平台，返回整合结果
            
        Returns:
            True 表示成功，False 表示失败
        """
        # 如果指定了平台，只采访该平台
        if platform in ("twitter", "reddit"):
            result = await self._interview_single_platform(agent_id, prompt, platform)
            
            if "error" in result:
                self.send_response(command_id, "failed", error=result["error"])
                print(f"  Interview失败: agent_id={agent_id}, platform={platform}, error={result['error']}")
                return False
            else:
                self.send_response(command_id, "completed", result=result)
                print(f"  Interview完成: agent_id={agent_id}, platform={platform}")
                return True
        
        # 未指定平台：同时采访两个平台
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="没有可用的模拟环境")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # 并行采访两个平台
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # 并行执行
        platform_results = await asyncio.gather(*tasks)
        
        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1
        
        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interview完成: agent_id={agent_id}, 成功平台数={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', '未知错误')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interview失败: agent_id={agent_id}, 所有平台都失败")
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """
        处理批量采访命令
        
        Args:
            command_id: 命令ID
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: 默认平台（可被每个interview项覆盖）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None/不指定: 每个Agent同时采访两个平台
        """
        # 按平台分组
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # 需要同时采访两个平台的
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # 未指定平台：两个平台都采访
                both_platforms_interviews.append(interview)
        
        # 把 both_platforms_interviews 拆分到两个平台
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # 处理Twitter平台的采访
        if twitter_interviews and self.twitter_env:
            try:
                prompts = {
                    interview.get("agent_id"): interview.get("prompt", "")
                    for interview in twitter_interviews
                }
                batch = await sim_runtime.batch_interview(
                    self.twitter_env,
                    self.twitter_agent_graph,
                    os.path.join(self.simulation_dir, "twitter_simulation.db"),
                    prompts,
                )
                # 没有任何有效 Agent 时不产出结果（与之前的行为一致）
                if any(not item.get("unknown_agent") for item in batch.values()):
                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = dict(batch[agent_id])
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitter批量Interview失败: {e}")

        # 处理Reddit平台的采访
        if reddit_interviews and self.reddit_env:
            try:
                prompts = {
                    interview.get("agent_id"): interview.get("prompt", "")
                    for interview in reddit_interviews
                }
                batch = await sim_runtime.batch_interview(
                    self.reddit_env,
                    self.reddit_agent_graph,
                    os.path.join(self.simulation_dir, "reddit_simulation.db"),
                    prompts,
                )
                # 没有任何有效 Agent 时不产出结果（与之前的行为一致）
                if any(not item.get("unknown_agent") for item in batch.values()):
                    for interview in reddit_interviews:
                        agent_id = interview.get("agent_id")
                        result = dict(batch[agent_id])
                        result["platform"] = "reddit"
                        results[f"reddit_{agent_id}"] = result
            except Exception as e:
                print(f"  Reddit批量Interview失败: {e}")

        if results:
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  批量Interview完成: {len(results)} 个Agent")
            return True
        else:
            self.send_response(command_id, "failed", error="没有成功的采访")
            return False
    
    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """从数据库获取最新的Interview结果"""
        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")
        return sim_runtime.read_interview_result(db_path, agent_id)

    async def process_commands(self) -> bool:
        """
        处理所有待处理命令
        
        Returns:
            True 表示继续运行，False 表示应该退出
        """
        command = self.poll_command()
        if not command:
            return True
        
        command_id = command.get("command_id")
        command_type = command.get("command_type")
        args = command.get("args", {})
        
        print(f"\n收到IPC命令: {command_type}, id={command_id}")
        
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
            print("收到关闭环境命令")
            self.send_response(command_id, "completed", result={"message": "环境即将关闭"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"未知命令类型: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# 需要过滤掉的非核心动作类型（这些动作对分析价值较低）
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# 动作类型映射表（数据库中的名称 -> 标准名称）
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
    从 simulation_config 中获取 agent_id -> entity_name 的映射
    
    这样可以在 actions.jsonl 中显示真实的实体名称，而不是 "Agent_0" 这样的代号
    
    Args:
        config: simulation_config.json 的内容
        
    Returns:
        agent_id -> entity_name 的映射字典
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
    从数据库中获取新的动作记录，并补充完整的上下文信息
    
    Args:
        db_path: 数据库文件路径
        last_rowid: 上次读取的最大 rowid 值（使用 rowid 而不是 created_at，因为不同平台的 created_at 格式不同）
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        (actions_list, new_last_rowid)
        - actions_list: 动作列表，每个元素包含 agent_id, agent_name, action_type, action_args（含上下文信息）
        - new_last_rowid: 新的最大 rowid 值
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 使用 rowid 来追踪已处理的记录（rowid 是 SQLite 的内置自增字段）
        # 这样可以避免 created_at 格式差异问题（Twitter 用整数，Reddit 用日期时间字符串）
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # 更新最大 rowid
            new_last_rowid = rowid
            
            # 过滤非核心动作
            if action in FILTERED_ACTIONS:
                continue
            
            # 解析动作参数
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # 精简 action_args，只保留关键字段（保留完整内容，不截断）
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
            
            # 转换动作类型名称
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # 补充上下文信息（帖子内容、用户名等）
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)
            
            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })
        
        conn.close()
    except Exception as e:
        print(f"读取数据库动作失败: {e}")
    
    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """
    为动作补充上下文信息（帖子内容、用户名等）
    
    Args:
        cursor: 数据库游标
        action_type: 动作类型
        action_args: 动作参数（会被修改）
        agent_names: agent_id -> agent_name 映射
    """
    try:
        # 点赞/踩帖子：补充帖子内容和作者
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # 转发帖子：补充原帖内容和作者
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # 转发帖子的 original_post_id 指向原帖
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
        
        # 引用帖子：补充原帖内容、作者和引用评论
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # 获取引用帖子的评论内容（quote_content）
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # 关注用户：补充被关注用户的名称
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # 从 follow 表获取 followee_id
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # 屏蔽用户：补充被屏蔽用户的名称
        elif action_type == 'MUTE':
            # 从 action_args 中获取 user_id 或 target_id
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # 点赞/踩评论：补充评论内容和作者
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # 发表评论：补充所评论的帖子信息
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # 补充上下文失败不影响主流程
        print(f"补充动作上下文失败: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    获取帖子信息
    
    Args:
        cursor: 数据库游标
        post_id: 帖子ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        包含 content 和 author_name 的字典，或 None
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
            
            # 优先使用 agent_names 中的名称
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # 从 user 表获取名称
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
    获取用户名称
    
    Args:
        cursor: 数据库游标
        user_id: 用户ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        用户名称，或 None
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
            
            # 优先使用 agent_names 中的名称
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
    获取评论信息
    
    Args:
        cursor: 数据库游标
        comment_id: 评论ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        包含 content 和 author_name 的字典，或 None
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
            
            # 优先使用 agent_names 中的名称
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # 从 user 表获取名称
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


_fallback_notices = {"count": 0}
_fallback_pacers: Dict[float, "sim_runtime.Pacer"] = {}


def _fallback_pacer() -> Optional["sim_runtime.Pacer"]:
    """One pacer for the backup model of both platforms (LLM_FALLBACK_MIN_INTERVAL seconds, default off)."""
    try:
        interval = float(os.environ.get("LLM_FALLBACK_MIN_INTERVAL") or 0)
    except ValueError:
        interval = 0.0
    if interval <= 0:
        return None
    return _fallback_pacers.setdefault(interval, sim_runtime.Pacer(interval))


def create_model(
    config: Dict[str, Any],
    use_boost: bool = False,
    run_settings: Optional[Dict[str, Any]] = None,
    seed: Optional[int] = None,
):
    """The platform's model, backed up by a second one.

    A call the platform's model cannot serve (quota, request too large, outage, rejected key) is retried
    once on the backup: the dedicated LLM_FALLBACK_* model when it is set (needs KEY and MODEL), else,
    when a boost model is configured, the other of main/boost. LLM_FALLBACK=false turns this off.
    """
    primary = sim_runtime.install_call_recording(
        _make_model(config, use_boost, run_settings, seed), "boost" if use_boost else "main"
    )
    enabled = os.environ.get("LLM_FALLBACK", "true").strip().lower() not in ("false", "0", "no", "off")
    has_dedicated = bool(os.environ.get("LLM_FALLBACK_API_KEY") and os.environ.get("LLM_FALLBACK_MODEL_NAME"))
    has_boost = bool(os.environ.get("LLM_BOOST_API_KEY"))
    if not enabled or not (has_dedicated or has_boost):
        return primary

    if has_dedicated:
        other = sim_runtime.install_call_recording(
            _make_model(config, use_boost, run_settings, seed, use_fallback=True), "fallback"
        )
        backup_label = "专用备用"
    else:
        other = sim_runtime.install_call_recording(
            _make_model(config, not use_boost, run_settings, seed), "main" if use_boost else "boost"
        )
        backup_label = "通用" if use_boost else "加速"

    def note(error: BaseException) -> None:
        _fallback_notices["count"] += 1
        if _fallback_notices["count"] in (1, 10) or _fallback_notices["count"] % 50 == 0:
            kind, message = sim_runtime.classify_error(error)
            print(
                f"[备用模型] 第 {_fallback_notices['count']} 次改用{backup_label}LLM重试 "
                f"({kind}: {message[:100]})"
            )

    return sim_runtime.install_model_fallback(primary, other, note, pacer=_fallback_pacer())


def _make_model(
    config: Dict[str, Any],
    use_boost: bool = False,
    run_settings: Optional[Dict[str, Any]] = None,
    seed: Optional[int] = None,
    use_fallback: bool = False,
):
    """
    创建LLM模型

    支持双 LLM 配置，用于并行模拟时提速：
    - 通用配置：LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
    - 加速配置（可选）：LLM_BOOST_API_KEY, LLM_BOOST_BASE_URL, LLM_BOOST_MODEL_NAME

    如果配置了加速 LLM，并行模拟时可以让不同平台使用不同的 API 服务商，提高并发能力。

    Args:
        config: 模拟配置字典
        use_boost: 是否使用加速 LLM 配置（如果可用）
        run_settings: 运行设置（config["run"] 与命令行合并后的结果），
            其中的 llm_temperature 会作为采样温度传给模型
        seed: 运行种子（仅在 run.llm_pass_seed 为真时才会尝试传给模型）
    """
    # 检查是否有加速配置
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = bool(boost_api_key)

    # 根据参数和配置情况选择使用哪个 LLM
    if use_fallback:
        # 专用备用模型 (LLM_FALLBACK_*)；base url 缺省时沿用通用配置
        llm_api_key = os.environ.get("LLM_FALLBACK_API_KEY", "")
        llm_base_url = os.environ.get("LLM_FALLBACK_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_FALLBACK_MODEL_NAME", "")
        config_label = "[备用LLM]"
    elif use_boost and has_boost_config:
        # 使用加速配置
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[加速LLM]"
    else:
        # 使用通用配置
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[通用LLM]"

    # 如果 .env 中没有模型名，则使用 config 作为备用
    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")

    # 设置 camel-ai 所需的环境变量
    if llm_api_key:
        os.environ["OPENAI_API_KEY"] = llm_api_key

    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("缺少 API Key 配置，请在项目根目录 .env 文件中设置 LLM_API_KEY")

    if llm_base_url:
        os.environ["OPENAI_API_BASE_URL"] = llm_base_url

    print(f"{config_label} model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else '默认'}...")

    client_options = sim_runtime.model_client_options(os.environ)
    if client_options:
        print(f"{config_label} 请求超时/重试: {client_options}")

    model_config = sim_behavior.llm_model_config(run_settings, seed)
    if "temperature" in model_config:
        print(f"{config_label} temperature={model_config['temperature']}")
    try:
        return sim_runtime.apply_model_client_options(ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type=llm_model,
            model_config_dict=dict(model_config) if model_config else None,
            **client_options,
        ), client_options)
    except Exception as error:
        if "seed" not in model_config:
            raise
        # camel-ai's OpenAI config has no `seed` field (0.2.78); retry without it.
        print(f"{config_label} 模型配置不接受 seed 参数，已忽略: {error}")
        model_config = {k: v for k, v in model_config.items() if k != "seed"}
        return sim_runtime.apply_model_client_options(ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type=llm_model,
            model_config_dict=model_config or None,
            **client_options,
        ), client_options)


def _agent_exists(env, agent_id) -> bool:
    try:
        env.agent_graph.get_agent(agent_id)
        return True
    except Exception:
        return False


def _write_checkpoint(env, platform: str, db_path: str, round_num: int, log_info) -> None:
    """Save a copy of the platform database as of the end of ``round_num`` (see sim_resume.py)."""
    try:
        memories = sim_runtime.collect_agent_memories(env.agent_graph)
    except Exception as error:
        memories = {}
        log_info(f"警告: 无法保存第 {round_num} 轮的Agent对话记忆（该检查点只含数据库）: {error}")
    try:
        sim_resume.write_checkpoint(
            db_path, round_num, sim_resume.clock_snapshot(platform, env.platform), memories=memories
        )
    except Exception as error:
        # Never break the run for this: without it a resume falls back to the previous checkpoint.
        log_info(f"警告: 写入第 {round_num} 轮检查点失败: {error}")


def get_active_agents_for_round(
    env,
    behavior: "sim_behavior.PlatformBehavior",
    current_hour: int,
    round_num: int
) -> List:
    """Resolve the agents the shared behaviour module wakes this round."""
    active_agents = []
    for agent_id in behavior.select_active(round_num, current_hour):
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass

    return active_agents


class PlatformSimulation:
    """平台模拟结果容器"""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0


# 两个平台之间的差异都集中在这张表里；其余逻辑完全共用
PLATFORM_SPECS = {
    "twitter": {
        "label": "Twitter",
        "use_boost": False,  # Twitter 使用通用 LLM 配置
        "profile_file": "twitter_profiles.csv",  # OASIS Twitter 使用 CSV 格式
        "effective_profile_file": "twitter_profiles.effective.csv",
        "db_file": "twitter_simulation.db",
        "actions": TWITTER_ACTIONS,
        "generate_graph": generate_twitter_agent_graph,
        "platform_type": oasis.DefaultPlatformType.TWITTER,
    },
    "reddit": {
        "label": "Reddit",
        "use_boost": True,  # Reddit 使用加速 LLM 配置（如果有的话，否则回退到通用配置）
        "profile_file": "reddit_profiles.json",
        "effective_profile_file": "reddit_profiles.effective.json",
        "db_file": "reddit_simulation.db",
        "actions": REDDIT_ACTIONS,
        "generate_graph": generate_reddit_agent_graph,
        "platform_type": oasis.DefaultPlatformType.REDDIT,
    },
}


async def _run_platform_simulation(
    platform: str,
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None,
    seed: Optional[int] = None,
    run_settings: Optional[Dict[str, Any]] = None,
) -> PlatformSimulation:
    """运行单个平台的模拟（Twitter / Reddit 共用）

    行为版本 v1（旧版）与之前完全一致，只是随机数改为由 seed 派生的、每个平台
    独立的 RNG。v2 额外启用：附加了行为指令的 profile、播种的关注图、定时事件、
    响应延迟（见 sim_behavior.py）。
    """
    spec = PLATFORM_SPECS[platform]
    label = spec["label"]
    result = PlatformSimulation()

    def log_info(msg):
        if main_logger:
            main_logger.info(f"[{label}] {msg}")
        print(f"[{label}] {msg}")

    log_info("初始化...")

    if seed is None:
        seed = secrets.randbelow(2 ** 31)
    behavior = sim_behavior.PlatformBehavior(config, platform, seed)

    model = create_model(
        config, use_boost=spec["use_boost"], run_settings=run_settings, seed=seed
    )

    profile_path = os.path.join(simulation_dir, spec["profile_file"])
    if behavior.v2:
        # v2 reads the per-run copy with the behaviour directive appended; the
        # original profile file (shown in the UI) is never modified.
        effective_path = os.path.join(simulation_dir, spec["effective_profile_file"])
        if os.path.exists(effective_path):
            profile_path = effective_path
        else:
            log_info("警告: 未找到附加了行为指令的 profile 副本，改用原始 profile")
    if not os.path.exists(profile_path):
        log_info(f"错误: Profile文件不存在: {profile_path}")
        return result

    result.agent_graph = await spec["generate_graph"](
        profile_path=profile_path,
        model=model,
        available_actions=spec["actions"],
    )

    # 从配置文件获取 Agent 真实名称映射（使用 entity_name 而非默认的 Agent_X）
    agent_names = get_agent_names_from_config(config)
    # 如果配置中没有某个 agent，则使用 OASIS 的默认名称
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')

    db_path = os.path.join(simulation_dir, spec["db_file"])
    resume = ((run_settings or {}).get("resume") or {}).get(platform)
    if os.path.exists(db_path) and not resume:
        os.remove(db_path)

    concurrency = sim_runtime.platform_llm_concurrency(platform, run_settings, os.environ)
    log_info(f"模型并发上限: {concurrency}")
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=spec["platform_type"],
        database_path=db_path,
        # 限制最大并发 LLM 请求数，防止 API 过载（并发运行多个副本时每个副本分到的额度更小）
        semaphore=concurrency,
    )

    await result.env.reset()
    log_info("环境已启动")

    total_actions = 0
    last_rowid = 0  # 跟踪数据库中最后处理的行号（使用 rowid 避免 created_at 格式差异）

    # 执行初始事件
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])

    start_round = 0
    if resume:
        # Continue a stopped run: the database and the log were put back at the end of round
        # ``resume["round"]`` before this process started. Nothing of the setup is redone.
        start_round = int(resume["round"])
        total_actions = int(resume.get("total_actions", 0))
        last_rowid = sim_runtime.max_trace_rowid(db_path)
        clock_note = sim_resume.restore_clock(platform, result.env.platform, db_path, resume.get("clock"))
        # The checkpoint's chat memory, as restored into the live database along with it. Only memory written at
        # exactly this round counts; the database is only read (the platform's own connection may hold a lock).
        saved_memories = sim_resume.read_memories(db_path, expect_round=start_round) if resume.get("exact") else {}
        memory_restored = 0
        if saved_memories:
            memory_restored, memory_failed = sim_runtime.restore_agent_memories(result.env.agent_graph, saved_memories)
            if memory_failed:
                log_info(f"警告: {len(memory_failed)} 个Agent的对话记忆无法恢复: {memory_failed[:10]}")
        initial_posted = any(
            _agent_exists(result.env, post.get("poster_agent_id", 0)) for post in initial_posts
        )
        try:
            sim_resume.replay_schedule(
                behavior,
                start_round,
                agent_exists=lambda agent_id: _agent_exists(result.env, agent_id),
                initial_posted=initial_posted,
                logged_ids=resume.get("logged_ids") or {},
            )
        except sim_resume.ScheduleMismatch as error:
            log_info(f"无法继续: {error}")
            raise
        log_info(
            f"从第 {start_round} 轮之后继续 "
            f"({'数据库已恢复到该轮结束时的检查点' if resume.get('exact') else '没有检查点：未完成那一轮已写入的内容无法撤销'}"
            f"; 时钟 {clock_note or '未知'}; 调度已重放 {start_round} 轮)"
        )
        if memory_restored:
            log_info(f"已恢复 {memory_restored} 个Agent的对话记忆")
        else:
            log_info("没有保存的Agent对话记忆（旧检查点或没有检查点）：Agent 以全新的对话继续")
        if action_logger:
            action_logger.log_resume(start_round, bool(resume.get("exact")), memory=bool(memory_restored))
    else:
        if action_logger:
            action_logger.log_simulation_start(config)

        # 记录 round 0 开始（初始事件阶段）
        if action_logger:
            action_logger.log_round_start(0, 0, active_agent_ids=[])  # round 0, simulated_hour 0

        # v2: seed the follow graph before anything is posted. These are setup, not
        # agent behaviour: logged as phase "setup" and skipped by the round-1 DB
        # fetch so they never count as actions.
        if behavior.v2:
            seeded_follows = await sim_runtime.apply_seed_follows(
                result.env, behavior.planned_follows()
            )
            if seeded_follows:
                last_rowid = sim_runtime.max_trace_rowid(db_path)
                if action_logger:
                    for follower_id, followee_id in seeded_follows:
                        action_logger.log_action(
                            round_num=0,
                            agent_id=follower_id,
                            agent_name=agent_names.get(follower_id, f"Agent_{follower_id}"),
                            action_type="FOLLOW",
                            action_args={
                                "followee_id": followee_id,
                                "target_user_name": agent_names.get(followee_id, f"Agent_{followee_id}"),
                            },
                            phase="setup",
                        )
                log_info(f"已播种 {len(seeded_follows)} 条初始关注关系")

        initial_action_count = 0
        if initial_posts:
            initial_actions = {}
            # Reddit always allowed several initial posts per agent. Twitter used to
            # keep only the last one (while logging all of them); v2 fixes that.
            several_posts_per_agent = platform == "reddit" or behavior.v2
            for post in initial_posts:
                agent_id = post.get("poster_agent_id", 0)
                content = post.get("content", "")
                try:
                    agent = result.env.agent_graph.get_agent(agent_id)
                    post_action = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )
                    if several_posts_per_agent and agent in initial_actions:
                        if not isinstance(initial_actions[agent], list):
                            initial_actions[agent] = [initial_actions[agent]]
                        initial_actions[agent].append(post_action)
                    else:
                        initial_actions[agent] = post_action

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
                log_info(f"已发布 {len(initial_actions)} 条初始帖子")
                if behavior.v2:
                    # They were logged explicitly above; don't log their DB rows
                    # again as round-1 actions, and start reaction delays.
                    last_rowid = sim_runtime.max_trace_rowid(db_path)
                    behavior.initial_posts_published()

        # 记录 round 0 结束
        if action_logger:
            action_logger.log_round_end(0, initial_action_count)
        _write_checkpoint(result.env, platform, db_path, 0, log_info)

    # 主模拟循环
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round

    # 如果指定了最大轮数，则截断
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"轮数已截断: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

    start_time = datetime.now()
    failure_tracker = sim_runtime.FailureTracker()
    consecutive_step_failures = 0

    interrupted = False
    for round_num in range(start_round, total_rounds):
        # 检查是否收到退出信号
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"收到退出信号，在第 {round_num + 1} 轮停止模拟")
            interrupted = True
            break

        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1

        # v2: scheduled events fire at the start of their round (before agents
        # are chosen, so their reaction delays apply to this very round).
        due_events = behavior.events_due(round_num) if behavior.v2 else []

        active_agents = get_active_agents_for_round(
            result.env, behavior, simulated_hour, round_num
        )
        active_agent_ids = [agent_id for agent_id, _ in active_agents]
        if resume and round_num == start_round and resume.get("unfinished_ids") not in (None, active_agent_ids):
            log_info(
                f"提示: 第 {round_num + 1} 轮重做时唤醒的Agent与中断前记录的不同 "
                f"(原: {resume['unfinished_ids']}, 现: {active_agent_ids})"
            )

        # 无论是否有活跃agent，都记录round开始（包含本轮激活的Agent ID列表，保证调度复现性可直接比对）
        if action_logger:
            action_logger.log_round_start(
                round_num + 1, simulated_hour, active_agent_ids=active_agent_ids
            )

        injected_count = 0
        if due_events:
            posted_events = await sim_runtime.inject_scheduled_events(
                result.env,
                due_events,
                log_round=round_num + 1,
                agent_names=agent_names,
                action_logger=action_logger,
                log=log_info,
            )
            last_rowid = sim_runtime.max_trace_rowid(db_path)
            injected_count = len(posted_events)
            total_actions += injected_count
            log_info(f"第 {round_num + 1} 轮注入 {injected_count} 个定时事件")

        if not active_agents:
            # 没有活跃agent时也记录round结束（actions_count 仅含注入的事件）
            if action_logger:
                action_logger.log_round_end(round_num + 1, injected_count, failed_count=0)
            _write_checkpoint(result.env, platform, db_path, round_num + 1, log_info)
            continue

        actions = {agent: LLMAction() for _, agent in active_agents}
        failure_tracker.begin_round(
            active_agents,
            on_failure=(
                lambda failure, _round=round_num + 1: action_logger.log_agent_error(
                    _round, failure["agent_id"], failure["kind"], failure["message"]
                )
            ) if action_logger else None,
        )
        step_error: Optional[Exception] = None
        try:
            await result.env.step(actions)
            consecutive_step_failures = 0
        except Exception as error:
            # One bad round (e.g. a locked database) must not end the run and
            # throw away the rounds already played. Give up only when the
            # environment keeps failing.
            step_error = error
            consecutive_step_failures += 1
            log_info(f"第 {round_num + 1} 轮 env.step 失败 ({consecutive_step_failures}/{MAX_CONSECUTIVE_STEP_FAILURES}): {error}")
            if consecutive_step_failures >= MAX_CONSECUTIVE_STEP_FAILURES:
                try:
                    await result.env.close()  # the platform is giving up; release its database
                except Exception:
                    pass
                raise
        finally:
            round_failures = failure_tracker.end_round()
        if step_error is not None:
            # The whole step failed, so every woken agent that did not already
            # report its own failure counts once (never more than were woken).
            kind, message = sim_runtime.classify_error(step_error)
            already_failed = {failure["agent_id"] for failure in round_failures}
            for agent_id in active_agent_ids:
                if agent_id in already_failed:
                    continue
                if action_logger:
                    action_logger.log_agent_error(round_num + 1, agent_id, kind, message)
                round_failures.append({"agent_id": agent_id, "kind": kind, "message": message})
        if round_failures:
            log_info(
                f"第 {round_num + 1} 轮: {len(round_failures)}/{len(active_agents)} 个Agent的模型调用失败 "
                f"({round_failures[0]['kind']}: {round_failures[0]['message'][:120]})"
            )

        # 从数据库获取实际执行的动作并记录
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )

        round_action_count = injected_count
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
            action_logger.log_round_end(round_num + 1, round_action_count, failed_count=len(round_failures))
        _write_checkpoint(result.env, platform, db_path, round_num + 1, log_info)

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")

    # 注意：不关闭环境，保留给Interview使用

    # A loop cut short by a stop signal is not a finished simulation: no simulation_end, so the run
    # is neither reported as completed nor impossible to resume.
    if action_logger and not interrupted:
        action_logger.log_simulation_end(total_rounds, total_actions)

    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"模拟循环完成! 耗时: {elapsed:.1f}秒, 总动作: {total_actions}")

    return result


async def run_twitter_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None,
    seed: Optional[int] = None,
    run_settings: Optional[Dict[str, Any]] = None,
) -> PlatformSimulation:
    """运行Twitter模拟

    Args:
        config: 模拟配置
        simulation_dir: 模拟目录
        action_logger: 动作日志记录器
        main_logger: 主日志管理器
        max_rounds: 最大模拟轮数（可选，用于截断过长的模拟）
        seed: 运行种子（用于派生本平台独立的随机数发生器）
        run_settings: 运行设置（config["run"] 与命令行合并后的结果）

    Returns:
        PlatformSimulation: 包含env和agent_graph的结果对象
    """
    return await _run_platform_simulation(
        "twitter", config, simulation_dir, action_logger, main_logger,
        max_rounds, seed, run_settings,
    )


async def run_reddit_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None,
    seed: Optional[int] = None,
    run_settings: Optional[Dict[str, Any]] = None,
) -> PlatformSimulation:
    """运行Reddit模拟

    Args:
        config: 模拟配置
        simulation_dir: 模拟目录
        action_logger: 动作日志记录器
        main_logger: 主日志管理器
        max_rounds: 最大模拟轮数（可选，用于截断过长的模拟）
        seed: 运行种子（用于派生本平台独立的随机数发生器）
        run_settings: 运行设置（config["run"] 与命令行合并后的结果）

    Returns:
        PlatformSimulation: 包含env和agent_graph的结果对象
    """
    return await _run_platform_simulation(
        "reddit", config, simulation_dir, action_logger, main_logger,
        max_rounds, seed, run_settings,
    )


async def main():
    parser = argparse.ArgumentParser(description='OASIS双平台并行模拟')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='配置文件路径 (simulation_config.json)'
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='只运行Twitter模拟'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='只运行Reddit模拟'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='最大模拟轮数（可选，用于截断过长的模拟）'
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='模拟完成后立即关闭环境，不进入等待命令模式'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=None,
        help='运行种子（覆盖配置文件 run.seed）。只保证调度可复现，不保证LLM输出一致'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        default=False,
        help='从上次完成的一轮之后继续（数据库与日志已由后端恢复到那一轮的结尾）'
    )

    args = parser.parse_args()

    # 在 main 函数开始时创建 shutdown 事件，确保整个程序都能响应退出信号
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    wait_for_commands = not args.no_wait

    # Run settings: config["run"] merged with the command line (CLI wins).
    run_settings = sim_behavior.resolve_run_settings(config, args.seed, args.max_rounds)
    seed = run_settings["seed"]
    if seed is None:
        seed = secrets.randbelow(2 ** 31)
    max_rounds = run_settings["max_rounds"]
    if args.resume:
        run_settings["resume"] = {}
        for resumed_platform in ("twitter", "reddit"):
            if (args.twitter_only and resumed_platform != "twitter") or (args.reddit_only and resumed_platform != "reddit"):
                continue
            plan = sim_resume.plan_resume(simulation_dir, resumed_platform)
            if not plan.resumable:
                print(f"错误: 无法继续 {resumed_platform}: {plan.reason}")
                sys.exit(1)
            scan = sim_resume.scan_log(os.path.join(simulation_dir, resumed_platform, "actions.jsonl"))
            marker = sim_resume.read_checkpoint_info(os.path.join(simulation_dir, f"{resumed_platform}_simulation.db"))
            run_settings["resume"][resumed_platform] = {
                "round": plan.round,
                "exact": plan.exact,
                "total_actions": plan.total_actions,
                "unfinished_ids": plan.unfinished_ids,
                "logged_ids": {n: ids for n, ids in scan.started.items() if n <= plan.round},
                "clock": (marker or {}).get("clock") if marker and marker["round"] == plan.round else {},
            }
    # Best effort for randomness inside OASIS itself. MiroFish's own decisions
    # use per-platform RNGs derived from the seed and never touch this one.
    random.seed(seed)
    behavior_v2 = sim_behavior.is_behavior_v2(config)
    
    # 初始化日志配置（禁用 OASIS 日志，清理旧文件）
    init_logging_for_simulation(simulation_dir)
    
    # 创建日志管理器
    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()
    
    log_manager.info("=" * 60)
    log_manager.info("OASIS 双平台并行模拟")
    log_manager.info(f"配置文件: {args.config}")
    log_manager.info(f"模拟ID: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"等待命令模式: {'启用' if wait_for_commands else '禁用'}")
    log_manager.info(f"随机种子: {seed}（只保证调度可复现，不保证LLM输出一致）")
    log_manager.info(f"行为版本: {'v2' if behavior_v2 else 'v1（旧版）'}")
    log_manager.info("=" * 60)

    if behavior_v2:
        # Per-run copies of the profiles with each agent's starting disposition
        # appended. The originals stay untouched.
        written = sim_behavior.write_effective_profiles(simulation_dir, config)
        log_manager.info(f"已生成附加行为指令的 profile 副本: {sorted(written)}")
    
    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 30)
    config_total_rounds = (total_hours * 60) // minutes_per_round
    
    log_manager.info(f"模拟参数:")
    log_manager.info(f"  - 总模拟时长: {total_hours}小时")
    log_manager.info(f"  - 每轮时间: {minutes_per_round}分钟")
    log_manager.info(f"  - 配置总轮数: {config_total_rounds}")
    if max_rounds:
        log_manager.info(f"  - 最大轮数限制: {max_rounds}")
        if max_rounds < config_total_rounds:
            log_manager.info(f"  - 实际执行轮数: {max_rounds} (已截断)")
    log_manager.info(f"  - Agent数量: {len(config.get('agent_configs', []))}")
    
    log_manager.info("日志结构:")
    log_manager.info(f"  - 主日志: simulation.log")
    log_manager.info(f"  - Twitter动作: twitter/actions.jsonl")
    log_manager.info(f"  - Reddit动作: reddit/actions.jsonl")
    log_manager.info("=" * 60)
    
    start_time = datetime.now()
    
    # 存储两个平台的模拟结果
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(
            config, simulation_dir, twitter_logger, log_manager, max_rounds, seed, run_settings)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(
            config, simulation_dir, reddit_logger, log_manager, max_rounds, seed, run_settings)
    else:
        # 并行运行（每个平台使用独立的日志记录器和独立的、由种子派生的随机数发生器）
        # return_exceptions: when one platform dies, the other still finishes
        # its own loop, and both environments are closed before the error is
        # raised (so no database stays locked and no task is left behind).
        results = await asyncio.gather(
            run_twitter_simulation(
                config, simulation_dir, twitter_logger, log_manager, max_rounds, seed, run_settings),
            run_reddit_simulation(
                config, simulation_dir, reddit_logger, log_manager, max_rounds, seed, run_settings),
            return_exceptions=True,
        )
        platform_errors = [r for r in results if isinstance(r, BaseException)]
        if platform_errors:
            for finished in results:
                env = getattr(finished, "env", None)
                if env is not None and not isinstance(finished, BaseException):
                    try:
                        await env.close()
                    except Exception:
                        pass
            raise platform_errors[0]
        twitter_result, reddit_result = results
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"模拟循环完成! 总耗时: {total_elapsed:.1f}秒")

    # End-of-run outcome poll (ensemble replicates): every agent answers the
    # outcome questions once. It runs before the environment is parked for
    # interviews, so the run is only published as finished after the poll.
    poll_questions = run_settings["outcome_questions"]
    if poll_questions and not _shutdown_event.is_set():
        poll_target = twitter_result if (twitter_result and twitter_result.env) else reddit_result
        if poll_target and poll_target.env:
            poll_platform = "twitter" if poll_target is twitter_result else "reddit"
            log_manager.info(f"开始最终问卷: {len(poll_questions)} 个问题, 平台={poll_platform}")
            poll_rows = await sim_runtime.run_final_poll(
                poll_target.env,
                poll_target.agent_graph,
                os.path.join(simulation_dir, f"{poll_platform}_simulation.db"),
                config,
                poll_questions,
                log=log_manager.info,
                status=(twitter_logger if poll_platform == "twitter" else reddit_logger).log_poll_status,
            )
            sim_runtime.write_final_poll(simulation_dir, poll_rows)
            parsed = sum(1 for row in poll_rows if row["parse_ok"])
            log_manager.info(f"最终问卷完成: {parsed}/{len(poll_rows)} 个Agent的回答可解析")
        else:
            log_manager.info("跳过最终问卷: 没有可用的平台环境")

    # 是否进入等待命令模式
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("进入等待命令模式 - 环境保持运行")
        log_manager.info("支持的命令: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # 创建IPC处理器
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")
        
        # 等待命令循环（使用全局 _shutdown_event）
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # 使用 wait_for 替代 sleep，这样可以响应 shutdown_event
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # 收到退出信号
                except asyncio.TimeoutError:
                    pass  # 超时继续循环
        except KeyboardInterrupt:
            print("\n收到中断信号")
        except asyncio.CancelledError:
            print("\n任务被取消")
        except Exception as e:
            print(f"\n命令处理出错: {e}")
        
        log_manager.info("\n关闭环境...")
        ipc_handler.update_status("stopped")
    
    # 关闭环境
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] 环境已关闭")
    
    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] 环境已关闭")
    
    log_manager.info("=" * 60)
    log_manager.info(f"全部完成!")
    log_manager.info(f"日志文件:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """
    设置信号处理器，确保收到 SIGTERM/SIGINT 时能够正确退出
    
    持久化模拟场景：模拟完成后不退出，等待 interview 命令
    当收到终止信号时，需要：
    1. 通知 asyncio 循环退出等待
    2. 让程序有机会正常清理资源（关闭数据库、环境等）
    3. 然后才退出
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n收到 {sig_name} 信号，正在退出...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # 设置事件通知 asyncio 循环退出（让循环有机会清理资源）
            if _shutdown_event:
                _shutdown_event.set()
        
        # 不要直接 sys.exit()，让 asyncio 循环正常退出并清理资源
        # 如果是重复收到信号，才强制退出
        else:
            print("强制退出...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被中断")
    except SystemExit:
        pass
    finally:
        # 清理 multiprocessing 资源跟踪器（防止退出时的警告）
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("模拟进程已退出")
