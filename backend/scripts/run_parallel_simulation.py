"""OASIS dual-platform parallel simulation runner.

Runs the Twitter and the Reddit simulation at the same time from one config
file.

Features:
- Parallel simulation on both platforms (Twitter + Reddit)
- Keeps the environments alive after the run instead of closing them, and
  waits for commands
- Receives interview commands over IPC
- Supports both a single-agent interview and a batch interview
- Supports a remote command to close the environments

Usage:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # close as soon as the run finishes
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

Log layout:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter platform action log
    ├── reddit/
    │   └── actions.jsonl    # Reddit platform action log
    ├── simulation.log       # Main simulation process log
    └── run_state.json       # Run state, read by the API
"""

# ============================================================
# Windows encoding fix, applied before every other import: OASIS and its
# dependencies open files without naming an encoding, so UTF-8 has to be the
# process default.
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # Make UTF-8 the default I/O encoding, which covers every open() call
    # that does not name one.
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    # Reconfigure the standard streams as UTF-8 so console output is not
    # mangled.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # PYTHONUTF8 only takes effect at interpreter start-up, so setting it here
    # may do nothing. The built-in open() is patched as well to be certain.
    import builtins
    _original_open = builtins.open
    
    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None, 
                   newline=None, closefd=True, opener=None):
        """Wrap open() so text mode defaults to UTF-8.

        This is what stops a third-party library such as OASIS from reading a
        file in the platform encoding.
        """
        # Only default the encoding for text mode with none supplied.
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


# Globals shared with the signal handlers.
_shutdown_event = None
_cleanup_done = False

# Add the backend directory to the import path. This script always lives in
# backend/scripts/.
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# Load the .env at the repository root, which holds LLM_API_KEY and friends.
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
    print(f"Loaded the environment configuration: {_env_file}")
else:
    # Fall back to backend/.env.
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"Loaded the environment configuration: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """Drop the camel-ai max_tokens warning.

    Leaving max_tokens unset is deliberate, so the model decides for itself.
    """
    
    def filter(self, record):
        # Drop any record carrying the max_tokens warning.
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# Install the filter at import time, before any camel code runs.
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """Silence the verbose OASIS library logging.

    OASIS logs every agent observation and action, which is far too much. This
    script records what matters through its own action_logger instead.
    """
    # Silence every OASIS logger.
    oasis_loggers = [
        "social.agent",
        "social.twitter", 
        "social.rec",
        "oasis.env",
        "table",
    ]
    
    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # Critical errors only.
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """Initialize logging for one simulation.

    Args:
        simulation_dir: Path of the simulation directory.
    """
    # Silence the verbose OASIS logging.
    disable_oasis_logging()
    
    # Remove the previous run's log directory.
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger

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
    print(f"Error: missing dependency {e}")
    print("Install the dependencies first: pip install oasis-ai camel-ai")
    sys.exit(1)


# The actions a Twitter agent may choose. INTERVIEW is excluded on purpose: it
# is only ever triggered by hand through a ManualAction.
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

# The actions a Reddit agent may choose. INTERVIEW is excluded on purpose: it
# is only ever triggered by hand through a ManualAction.
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


# IPC constants.
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """Command type constants."""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """Handle IPC commands across both platform environments."""
    
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
        
        # Create the IPC directories.
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """Write the current environment status."""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "twitter_available": self.twitter_env is not None,
                "reddit_available": self.reddit_env is not None,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """Return the oldest pending command, or None."""
        if not os.path.exists(self.commands_dir):
            return None
        
        # Collect the command files, oldest first.
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
        """Write the response for one command."""
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
        
        # Remove the command file.
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def _get_env_and_graph(self, platform: str):
        """Return the environment and agent graph of one platform.

        Args:
            platform: Platform name, "twitter" or "reddit".

        Returns:
            (env, agent_graph, platform_name), or (None, None, None).
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """Run an interview on one platform.

        Returns:
            The result dict, or a dict carrying an error key.
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)
        
        if not env or not agent_graph:
            return {"platform": platform, "error": f"The {platform} platform is unavailable"}
        
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
        """Run a single-agent interview command.

        Args:
            command_id: The command id.
            agent_id: The agent id.
            prompt: The interview question.
            platform: An optional platform.
                - "twitter": interview on Twitter only
                - "reddit": interview on Reddit only
                - None: interview on both platforms and merge the results

        Returns:
            True on success, False on failure.
        """
        # A named platform means only that platform is interviewed.
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
        
        # With no platform named, interview on both.
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="No simulation environment is available")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # Interview both platforms in parallel.
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # Run them together.
        platform_results = await asyncio.gather(*tasks)
        
        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1
        
        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interview completed: agent_id={agent_id}, platforms succeeded={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', 'unknown error')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interview failed: agent_id={agent_id}, every platform failed")
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """Run a batch interview command.

        Args:
            command_id: The command id.
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: The default platform, which any interview item may
                override.
                - "twitter": interview on Twitter only
                - "reddit": interview on Reddit only
                - None: interview every agent on both platforms
        """
        # Group the interviews by platform.
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # Interviews that run on both.
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # No platform named, so interview on both.
                both_platforms_interviews.append(interview)
        
        # Fan both_platforms_interviews out to each available platform.
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # Twitter interviews.
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
                        print(f"  Warning: could not load Twitter agent {agent_id}: {e}")
                
                if twitter_actions:
                    await self.twitter_env.step(twitter_actions)
                    
                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "twitter")
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitter batch interview failed: {e}")
        
        # Reddit interviews.
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
                        print(f"  Warning: could not load Reddit agent {agent_id}: {e}")
                
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
            self.send_response(command_id, "failed", error="No interview succeeded")
            return False
    
    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """Read the most recent interview answer out of the database."""
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
            
            # Query the most recent interview record.
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
            print(f"  Failed to read the interview result: {e}")
        
        return result
    
    async def process_commands(self) -> bool:
        """Handle every pending command.

        Returns:
            True to keep running, False to shut down.
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
            print("Received the close-environment command")
            self.send_response(command_id, "completed", result={"message": "The environments are closing"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"Unknown command type: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """Load the simulation config."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# Action types dropped from the log because they carry little analytical value.
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# Action type map, from the database name to the canonical name.
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
    """Map agent_id to entity_name using simulation_config.

    This is what lets actions.jsonl carry the real entity name instead of a
    placeholder such as "Agent_0".

    Args:
        config: The contents of simulation_config.json.

    Returns:
        A dict mapping agent_id to entity_name.
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
    """Read the new action records out of the database and enrich them.

    Args:
        db_path: Path of the database file.
        last_rowid: The highest rowid read so far. rowid is used rather than
            created_at because the two platforms format created_at
            differently.
        agent_names: A dict mapping agent_id to agent_name.

    Returns:
        (actions_list, new_last_rowid)
        - actions_list: the actions, each carrying agent_id, agent_name,
          action_type and action_args including the enriched context
        - new_last_rowid: the new highest rowid
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # rowid, SQLite's built-in auto-increment column, tracks what has been
        # processed. It sidesteps the created_at format difference: Twitter
        # writes an integer, Reddit a datetime string.
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # Advance the highest rowid.
            new_last_rowid = rowid
            
            # Drop the non-core actions.
            if action in FILTERED_ACTIONS:
                continue
            
            # Parse the action arguments.
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # Keep only the fields that matter, with their content intact.
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
            
            # Map the action type to its canonical name.
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # Enrich with context such as the post content and author name.
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)
            
            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })
        
        conn.close()
    except Exception as e:
        print(f"Failed to read the actions from the database: {e}")
    
    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """Enrich one action with context such as post content and author name.

    Args:
        cursor: The database cursor.
        action_type: The action type.
        action_args: The action arguments, modified in place.
        agent_names: A dict mapping agent_id to agent_name.
    """
    try:
        # Like or dislike a post: add the post content and its author.
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # Repost: add the original post content and its author.
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # A repost's original_post_id points at the original post.
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
        
        # Quote a post: add the original content, its author and the quote.
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # Read the quote text of the quoting post.
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # Follow: add the name of the followed user.
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # Read followee_id from the follow table.
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # Mute: add the name of the muted user.
        elif action_type == 'MUTE':
            # The target is under user_id or target_id.
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # Like or dislike a comment: add its content and its author.
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # Create a comment: add the post it replies to.
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # Failing to enrich an action must not stop the run.
        print(f"Failed to enrich the action context: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """Return one post's details.

    Args:
        cursor: The database cursor.
        post_id: The post id.
        agent_names: A dict mapping agent_id to agent_name.

    Returns:
        A dict with content and author_name, or None.
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
            
            # Prefer the name from agent_names.
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Fall back to the user table.
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
    """Return one user's display name.

    Args:
        cursor: The database cursor.
        user_id: The user id.
        agent_names: A dict mapping agent_id to agent_name.

    Returns:
        The user name, or None.
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
            
            # Prefer the name from agent_names.
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
    """Return one comment's details.

    Args:
        cursor: The database cursor.
        comment_id: The comment id.
        agent_names: A dict mapping agent_id to agent_name.

    Returns:
        A dict with content and author_name, or None.
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
            
            # Prefer the name from agent_names.
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # Fall back to the user table.
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


# The per-request budget handed to the LLM client. camel-ai would otherwise
# default to a 180s timeout with 3 retries, i.e. 4 attempts and a 720s ceiling
# per agent request. An unresponsive endpoint therefore burns that budget on
# every round, which is how a dead endpoint once cost a full 11-hour run
# without failing the run. Both values are configurable so a slow endpoint can
# be given more room and a fragile one can be made to fail fast.
DEFAULT_MODEL_TIMEOUT = 180.0
DEFAULT_MODEL_MAX_RETRIES = 3


def get_model_request_budget() -> Tuple[float, int]:
    """Read the per-request timeout and retry count from the environment.

    Returns:
        Tuple[float, int]: the timeout in seconds and the retry count.
    """
    try:
        timeout = float(os.environ.get("SIM_MODEL_TIMEOUT", DEFAULT_MODEL_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_MODEL_TIMEOUT
    try:
        max_retries = int(os.environ.get("SIM_MODEL_MAX_RETRIES", DEFAULT_MODEL_MAX_RETRIES))
    except ValueError:
        max_retries = DEFAULT_MODEL_MAX_RETRIES
    return max(1.0, timeout), max(0, max_retries)


def resolve_llm_settings(config: Dict[str, Any], use_boost: bool = False) -> Dict[str, str]:
    """Resolve the LLM settings one platform will run against.

    Two LLM configurations are supported, which speeds a parallel run up:
    - primary: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
    - boost (optional): LLM_BOOST_API_KEY, LLM_BOOST_BASE_URL,
      LLM_BOOST_MODEL_NAME

    With a boost configuration in place, the two platforms can run against
    different API providers, which raises the achievable concurrency.

    Args:
        config: The simulation config.
        use_boost: Use the boost configuration when one is available.

    Returns:
        Dict[str, str]: the api_key, base_url, model and label to run against.
    """
    # Is a boost configuration available?
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = bool(boost_api_key)
    
    # Choose the configuration to run against.
    if use_boost and has_boost_config:
        # Boost configuration.
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[boost LLM]"
    else:
        # Primary configuration.
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[primary LLM]"
    
    # Fall back to the simulation config when .env names no model.
    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")
    
    # Export the environment variables camel-ai expects.
    if llm_api_key:
        os.environ["OPENAI_API_KEY"] = llm_api_key
    
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError(
            "No API key is configured. Set LLM_API_KEY in the .env file at the "
            "repository root."
        )
    
    if llm_base_url:
        os.environ["OPENAI_API_BASE_URL"] = llm_base_url
    
    return {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": llm_base_url or os.environ.get("OPENAI_API_BASE_URL", ""),
        "model": llm_model,
        "label": config_label,
    }


def create_model(config: Dict[str, Any], use_boost: bool = False):
    """Create the LLM model for one platform.

    Args:
        config: The simulation config.
        use_boost: Use the boost configuration when one is available.
    """
    settings = resolve_llm_settings(config, use_boost)
    timeout, max_retries = get_model_request_budget()
    
    base_url = settings["base_url"]
    print(
        f"{settings['label']} model={settings['model']}, "
        f"base_url={base_url[:40] if base_url else 'default'}..., "
        f"timeout={timeout:.0f}s, max_retries={max_retries}"
    )
    
    # Pass the budget explicitly rather than inheriting the library default,
    # so the value is visible in the log and tunable from the environment.
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=settings["model"],
        timeout=timeout,
        max_retries=max_retries,
    )


# How many LLM requests one platform keeps in flight. This must be matched to
# what the serving side will actually run at once: vLLM's --max-num-seqs caps
# its running batch and queues the rest, and a queued request's wait counts
# against the client timeout. Both platforms run concurrently, so the load on
# the endpoint is twice this number. Overshooting does not raise throughput on
# a bandwidth-bound server; it just moves every request closer to timing out.
DEFAULT_LLM_SEMAPHORE = 30


def get_llm_semaphore() -> int:
    """Read the per-platform limit on concurrent LLM requests.

    Returns:
        int: the number of requests one platform may keep in flight.
    """
    try:
        value = int(os.environ.get("SIM_LLM_SEMAPHORE", DEFAULT_LLM_SEMAPHORE))
    except ValueError:
        value = DEFAULT_LLM_SEMAPHORE
    return max(1, value)


DEFAULT_PREFLIGHT_TIMEOUT = 60.0


async def preflight_check_llm(
    config: Dict[str, Any],
    use_boost: bool,
    log,
) -> Tuple[bool, str]:
    """Send one tiny completion to prove the endpoint actually answers.

    A simulation makes no progress at all when the configured model does not
    respond, but the round loop tolerates per-agent failures and so keeps
    going, reporting a full round count against zero real actions. Checking
    once up front turns that silent multi-hour failure into an immediate one.

    The check deliberately uses no retries and a short timeout: the question
    is whether the endpoint responds at all, not whether it responds quickly
    under load.

    Args:
        config: The simulation config.
        use_boost: Check the boost configuration rather than the primary one.
        log: A callable taking one message string.

    Returns:
        Tuple[bool, str]: whether the endpoint answered, plus a description.
    """
    try:
        settings = resolve_llm_settings(config, use_boost)
    except ValueError as exc:
        return False, str(exc)
    
    try:
        timeout = float(os.environ.get("SIM_PREFLIGHT_TIMEOUT", DEFAULT_PREFLIGHT_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_PREFLIGHT_TIMEOUT
    
    base_url = settings["base_url"]
    log(
        f"{settings['label']} preflight: model={settings['model']}, "
        f"base_url={base_url[:40] if base_url else 'default'}..., "
        f"timeout={timeout:.0f}s"
    )
    
    from openai import AsyncOpenAI
    
    client = AsyncOpenAI(
        api_key=settings["api_key"],
        base_url=base_url or None,
        timeout=timeout,
        max_retries=0,
    )
    
    started = datetime.now()
    try:
        response = await client.chat.completions.create(
            model=settings["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:
        elapsed = (datetime.now() - started).total_seconds()
        # Name the exception type: a timeout, a refused connection and a
        # rejected key each call for a different fix.
        return False, (
            f"{type(exc).__name__} after {elapsed:.1f}s: {exc}"
        )
    finally:
        try:
            await client.close()
        except Exception:
            pass
    
    elapsed = (datetime.now() - started).total_seconds()
    
    # A 200 carrying no choices means the endpoint is reachable but is not
    # serving completions, which fails agents just as surely as a timeout.
    if not getattr(response, "choices", None):
        return False, f"responded in {elapsed:.1f}s but returned no choices"
    
    return True, f"answered in {elapsed:.1f}s"


async def preflight_check_all(
    config: Dict[str, Any],
    run_twitter: bool,
    run_reddit: bool,
    log_manager,
) -> bool:
    """Preflight every LLM configuration the run is about to depend on.

    Args:
        config: The simulation config.
        run_twitter: Whether the Twitter platform will run.
        run_reddit: Whether the Reddit platform will run.
        log_manager: The main log manager.

    Returns:
        bool: True when every configuration in use answered.
    """
    def log(msg):
        if log_manager:
            log_manager.info(msg)
        else:
            print(msg)
    
    # Twitter runs against the primary configuration and Reddit against boost,
    # but boost silently falls back to primary when it is not configured, so
    # only check it separately when it is genuinely a second endpoint.
    checks = []
    if run_twitter:
        checks.append(False)
    if run_reddit:
        has_boost = bool(os.environ.get("LLM_BOOST_API_KEY", ""))
        if has_boost:
            checks.append(True)
        elif not run_twitter:
            checks.append(False)
    
    log("=" * 60)
    log("LLM preflight check")
    
    all_ok = True
    for use_boost in checks:
        ok, detail = await preflight_check_llm(config, use_boost, log)
        label = "[boost LLM]" if use_boost else "[primary LLM]"
        if ok:
            log(f"  OK      {label} {detail}")
        else:
            log(f"  FAILED  {label} {detail}")
            all_ok = False
    
    if all_ok:
        log("Preflight passed.")
    else:
        log("")
        log("Preflight FAILED - aborting before the simulation starts.")
        log("A simulation cannot produce any agent behaviour while the model")
        log("is unreachable; it would only burn the full round budget on")
        log("timeouts and finish with an empty action log.")
        log("Check that the endpoint is up, that LLM_BASE_URL and")
        log("LLM_MODEL_NAME are correct, and that the key is accepted.")
        log("Pass --skip-preflight to run anyway.")
    log("=" * 60)
    
    return all_ok


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int
) -> List:
    """Pick the agents that act in this round."""
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


DEFAULT_ZERO_ACTION_ABORT = 10


def get_zero_action_limit() -> int:
    """Read how many consecutive empty rounds should abort a run.

    Returns:
        int: the limit, or 0 when the check is disabled.
    """
    try:
        limit = int(os.environ.get("SIM_ZERO_ACTION_ABORT", DEFAULT_ZERO_ACTION_ABORT))
    except ValueError:
        limit = DEFAULT_ZERO_ACTION_ABORT
    return max(0, limit)


class PlatformSimulation:
    """The result of one platform's simulation."""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0
        # Set when the circuit breaker cut the run short.
        self.abort_reason = None


async def run_twitter_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """Run the Twitter simulation.

    Args:
        config: The simulation config.
        simulation_dir: The simulation directory.
        action_logger: The platform action logger.
        main_logger: The main log manager.
        max_rounds: Cap on the number of rounds, to truncate a long run.

    Returns:
        PlatformSimulation: the result, carrying env and agent_graph.
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")
    
    log_info("Initializing...")
    
    # Twitter runs against the primary LLM configuration.
    model = create_model(config, use_boost=False)
    
    llm_semaphore = get_llm_semaphore()
    log_info(f"Concurrent LLM requests capped at {llm_semaphore}")
    
    # OASIS Twitter reads a CSV.
    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"Error: profile file not found: {profile_path}")
        return result
    
    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )
    
    # Take the real agent names from the config, preferring entity_name over
    # the default Agent_X.
    agent_names = get_agent_names_from_config(config)
    # Fall back to the OASIS name for an agent the config does not cover.
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
        semaphore=llm_semaphore,
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # The last database row processed, tracked by rowid.
    
    # Publish the seed events.
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Round 0 covers the seed events.
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
            log_info(f"Published {len(initial_actions)} seed posts")
    
    # Close out round 0.
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Main simulation loop.
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # Truncate when a round cap was supplied.
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    # Circuit breaker. A round that activates agents and still records no
    # action is the signature of a failing model backend, because the round
    # loop absorbs per-agent errors and cannot otherwise tell "the agents
    # chose to do nothing" apart from "every request failed". A single such
    # round is normal; a long unbroken run of them is not, and continuing only
    # burns the timeout budget on every remaining round.
    zero_action_streak = 0
    zero_action_limit = get_zero_action_limit()
    
    for round_num in range(total_rounds):
        # Stop as soon as a shutdown was requested.
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received the shutdown signal; stopping at round {round_num + 1}")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # Record the round start whether or not any agent is active.
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # Record the round end too, with no actions.
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # Read the actions that actually ran and log them.
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
        
        # Trip the breaker only on rounds that actually asked agents to act.
        if round_action_count > 0:
            zero_action_streak = 0
        else:
            zero_action_streak += 1
            if zero_action_limit and zero_action_streak == 1:
                log_info(
                    f"Round {round_num + 1} activated {len(active_agents)} "
                    f"agents but recorded no action - watching for a run of "
                    f"these (abort at {zero_action_limit})"
                )
            if zero_action_limit and zero_action_streak >= zero_action_limit:
                result.abort_reason = (
                    f"{zero_action_streak} consecutive rounds activated agents "
                    f"but recorded no action, so the model backend is almost "
                    f"certainly failing every request"
                )
                log_info("=" * 60)
                log_info(f"ABORTING at round {round_num + 1}/{total_rounds}")
                log_info(result.abort_reason)
                log_info(
                    "Check the model endpoint, then re-run. Set "
                    "SIM_ZERO_ACTION_ABORT=0 to disable this check."
                )
                log_info("=" * 60)
                break
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # The environment is deliberately left open, so interviews can still run.
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    status = "ABORTED" if result.abort_reason else "complete"
    log_info(f"Simulation loop {status}. Elapsed: {elapsed:.1f}s, actions: {total_actions}")
    
    return result


async def run_reddit_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """Run the Reddit simulation.

    Args:
        config: The simulation config.
        simulation_dir: The simulation directory.
        action_logger: The platform action logger.
        main_logger: The main log manager.
        max_rounds: Cap on the number of rounds, to truncate a long run.

    Returns:
        PlatformSimulation: the result, carrying env and agent_graph.
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")
    
    log_info("Initializing...")
    
    # Reddit runs against the boost LLM configuration when one exists, and
    # falls back to the primary one otherwise.
    model = create_model(config, use_boost=True)
    
    llm_semaphore = get_llm_semaphore()
    log_info(f"Concurrent LLM requests capped at {llm_semaphore}")
    
    profile_path = os.path.join(simulation_dir, "reddit_profiles.json")
    if not os.path.exists(profile_path):
        log_info(f"Error: profile file not found: {profile_path}")
        return result
    
    result.agent_graph = await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=REDDIT_ACTIONS,
    )
    
    # Take the real agent names from the config, preferring entity_name over
    # the default Agent_X.
    agent_names = get_agent_names_from_config(config)
    # Fall back to the OASIS name for an agent the config does not cover.
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
        semaphore=llm_semaphore,
    )
    
    await result.env.reset()
    log_info("Environment started")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # The last database row processed, tracked by rowid.
    
    # Publish the seed events.
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # Round 0 covers the seed events.
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
            log_info(f"Published {len(initial_actions)} seed posts")
    
    # Close out round 0.
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # Main simulation loop.
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # Truncate when a round cap was supplied.
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"Rounds truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    # Circuit breaker. A round that activates agents and still records no
    # action is the signature of a failing model backend, because the round
    # loop absorbs per-agent errors and cannot otherwise tell "the agents
    # chose to do nothing" apart from "every request failed". A single such
    # round is normal; a long unbroken run of them is not, and continuing only
    # burns the timeout budget on every remaining round.
    zero_action_streak = 0
    zero_action_limit = get_zero_action_limit()
    
    for round_num in range(total_rounds):
        # Stop as soon as a shutdown was requested.
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"Received the shutdown signal; stopping at round {round_num + 1}")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # Record the round start whether or not any agent is active.
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # Record the round end too, with no actions.
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # Read the actions that actually ran and log them.
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
        
        # Trip the breaker only on rounds that actually asked agents to act.
        if round_action_count > 0:
            zero_action_streak = 0
        else:
            zero_action_streak += 1
            if zero_action_limit and zero_action_streak == 1:
                log_info(
                    f"Round {round_num + 1} activated {len(active_agents)} "
                    f"agents but recorded no action - watching for a run of "
                    f"these (abort at {zero_action_limit})"
                )
            if zero_action_limit and zero_action_streak >= zero_action_limit:
                result.abort_reason = (
                    f"{zero_action_streak} consecutive rounds activated agents "
                    f"but recorded no action, so the model backend is almost "
                    f"certainly failing every request"
                )
                log_info("=" * 60)
                log_info(f"ABORTING at round {round_num + 1}/{total_rounds}")
                log_info(result.abort_reason)
                log_info(
                    "Check the model endpoint, then re-run. Set "
                    "SIM_ZERO_ACTION_ABORT=0 to disable this check."
                )
                log_info("=" * 60)
                break
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # The environment is deliberately left open, so interviews can still run.
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    status = "ABORTED" if result.abort_reason else "complete"
    log_info(f"Simulation loop {status}. Elapsed: {elapsed:.1f}s, actions: {total_actions}")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description='OASIS dual-platform parallel simulation')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='Path of the simulation config file (simulation_config.json)'
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='Run the Twitter simulation only'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='Run the Reddit simulation only'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='Cap on the number of rounds, to truncate a long run'
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='Close the environments as soon as the run finishes instead of waiting for commands'
    )
    parser.add_argument(
        '--skip-preflight',
        action='store_true',
        default=False,
        help='Skip the LLM preflight check and start the run regardless'
    )
    
    args = parser.parse_args()
    
    # Create the shutdown event first, so the whole program can respond to a
    # termination signal.
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"Error: config file not found: {args.config}")
        sys.exit(1)
    
    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    wait_for_commands = not args.no_wait
    
    # Configure logging: silence OASIS and clear the previous run's files.
    init_logging_for_simulation(simulation_dir)
    
    # Create the log manager.
    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()
    
    log_manager.info("=" * 60)
    log_manager.info("OASIS dual-platform parallel simulation")
    log_manager.info(f"Config file: {args.config}")
    log_manager.info(f"Simulation id: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"Wait-for-commands mode: {'enabled' if wait_for_commands else 'disabled'}")
    log_manager.info("=" * 60)
    
    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 30)
    config_total_rounds = (total_hours * 60) // minutes_per_round
    
    log_manager.info("Simulation parameters:")
    log_manager.info(f"  - Total simulated time: {total_hours} hours")
    log_manager.info(f"  - Minutes per round: {minutes_per_round}")
    log_manager.info(f"  - Rounds in the config: {config_total_rounds}")
    if args.max_rounds:
        log_manager.info(f"  - Round cap: {args.max_rounds}")
        if args.max_rounds < config_total_rounds:
            log_manager.info(f"  - Rounds actually run: {args.max_rounds} (truncated)")
    log_manager.info(f"  - Agents: {len(config.get('agent_configs', []))}")

    log_manager.info("Log layout:")
    log_manager.info("  - Main log: simulation.log")
    log_manager.info("  - Twitter actions: twitter/actions.jsonl")
    log_manager.info("  - Reddit actions: reddit/actions.jsonl")
    log_manager.info("=" * 60)
    
    # Prove the model answers before building any environment. Doing this
    # first means a misconfigured or down endpoint costs seconds instead of
    # the whole round budget.
    if args.skip_preflight:
        log_manager.info("LLM preflight check skipped (--skip-preflight)")
    else:
        preflight_ok = await preflight_check_all(
            config,
            run_twitter=not args.reddit_only,
            run_reddit=not args.twitter_only,
            log_manager=log_manager,
        )
        if not preflight_ok:
            sys.exit(1)
    
    start_time = datetime.now()
    
    # The result of each platform's simulation.
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds)
    else:
        # Run both platforms together, each with its own action logger.
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds),
        )
        twitter_result, reddit_result = results
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    
    # Report an aborted run as aborted. A round count alone hid exactly this
    # failure before: every round "finished" while no agent ever acted.
    aborts = [
        (name, r.abort_reason)
        for name, r in (("Twitter", twitter_result), ("Reddit", reddit_result))
        if r is not None and r.abort_reason
    ]
    total_recorded_actions = sum(
        r.total_actions for r in (twitter_result, reddit_result) if r is not None
    )
    
    if aborts:
        log_manager.info(f"Simulation ABORTED. Total elapsed: {total_elapsed:.1f}s")
        for name, reason in aborts:
            log_manager.info(f"  [{name}] {reason}")
    else:
        log_manager.info(f"Simulation loop complete. Total elapsed: {total_elapsed:.1f}s")
    
    log_manager.info(f"Total actions recorded: {total_recorded_actions}")
    if total_recorded_actions == 0:
        log_manager.info(
            "WARNING: no action was recorded, so there is no behaviour to "
            "interview or report on. Treat this run as failed."
        )
    
    # Optionally stay alive and wait for IPC commands.
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("Waiting for commands - the environments stay running")
        log_manager.info("Supported commands: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # Start the IPC handler.
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")
        
        # Command loop, driven by the global _shutdown_event.
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # wait_for rather than sleep, so a shutdown is acted on at once.
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # The shutdown signal arrived.
                except asyncio.TimeoutError:
                    pass  # Timed out, so poll again.
        except KeyboardInterrupt:
            print("\nInterrupted")
        except asyncio.CancelledError:
            print("\nTask cancelled")
        except Exception as e:
            print(f"\nFailed to process a command: {e}")
        
        log_manager.info("\nClosing the environments...")
        ipc_handler.update_status("stopped")
    
    # Close the environments.
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] Environment closed")
    
    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] Environment closed")
    
    log_manager.info("=" * 60)
    log_manager.info("All done")
    log_manager.info("Log files:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """Install the signal handlers.

    A simulation stays alive after the run and waits for interview commands, so
    SIGTERM and SIGINT must:
    1. tell the asyncio loop to stop waiting,
    2. give the program a chance to close the databases and environments,
    3. and only then exit.
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\nReceived {sig_name}; shutting down...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # Wake the asyncio loop so it can clean up and exit.
            if _shutdown_event:
                _shutdown_event.set()
        
        # Never call sys.exit() here: the asyncio loop has to unwind and
        # release its resources. Only a second signal forces the exit.
        else:
            print("Forcing exit...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    # Carry the exit status out past the cleanup below. Swallowing it would
    # report a failed run as a clean one, because the API decides a run failed
    # by looking at this process's exit code.
    exit_code = 0
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    finally:
        # Shut the multiprocessing resource tracker down, which otherwise
        # warns on exit.
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("Simulation process exited")
    
    sys.exit(exit_code)
