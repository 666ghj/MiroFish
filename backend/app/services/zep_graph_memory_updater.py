"""
Zep graph memory updater service
Dynamically pushes Agent activity from a simulation into a Zep graph
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale

logger = get_logger('mirofish.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """Agent activity record"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """
        Convert the activity into a text description that can be sent to Zep.

        Uses a natural-language description format so Zep can extract entities and
        relationships from it. No simulation-related prefix is added so as not to
        mislead the graph update.
        """
        # Generate different descriptions based on action type
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }

        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()

        # Return "<agent name>: <activity description>" — no simulation prefix
        return f"{self.agent_name}: {description}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f'posted: "{content}"'
        return "published a post"

    def _describe_like_post(self) -> str:
        """Like a post — includes original post text and author info"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f'liked {post_author}\'s post: "{post_content}"'
        elif post_content:
            return f'liked a post: "{post_content}"'
        elif post_author:
            return f"liked a post by {post_author}"
        return "liked a post"

    def _describe_dislike_post(self) -> str:
        """Dislike a post — includes original post text and author info"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f'disliked {post_author}\'s post: "{post_content}"'
        elif post_content:
            return f'disliked a post: "{post_content}"'
        elif post_author:
            return f"disliked a post by {post_author}"
        return "disliked a post"

    def _describe_repost(self) -> str:
        """Repost — includes original post content and author info"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")

        if original_content and original_author:
            return f'reposted {original_author}\'s post: "{original_content}"'
        elif original_content:
            return f'reposted a post: "{original_content}"'
        elif original_author:
            return f"reposted a post by {original_author}"
        return "reposted a post"

    def _describe_quote_post(self) -> str:
        """Quote a post — includes original content, author info, and the quote comment"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")

        base = ""
        if original_content and original_author:
            base = f'quoted {original_author}\'s post "{original_content}"'
        elif original_content:
            base = f'quoted a post "{original_content}"'
        elif original_author:
            base = f"quoted a post by {original_author}"
        else:
            base = "quoted a post"

        if quote_content:
            base += f', commenting: "{quote_content}"'
        return base

    def _describe_follow(self) -> str:
        """Follow user — includes the followed user's name"""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f'followed user "{target_user_name}"'
        return "followed a user"

    def _describe_create_comment(self) -> str:
        """Post a comment — includes comment text and the post being commented on"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if content:
            if post_content and post_author:
                return f'commented on {post_author}\'s post "{post_content}": "{content}"'
            elif post_content:
                return f'commented on the post "{post_content}": "{content}"'
            elif post_author:
                return f'commented on a post by {post_author}: "{content}"'
            return f'commented: "{content}"'
        return "posted a comment"

    def _describe_like_comment(self) -> str:
        """Like a comment — includes comment text and author info"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f'liked {comment_author}\'s comment: "{comment_content}"'
        elif comment_content:
            return f'liked a comment: "{comment_content}"'
        elif comment_author:
            return f"liked a comment by {comment_author}"
        return "liked a comment"

    def _describe_dislike_comment(self) -> str:
        """Dislike a comment — includes comment text and author info"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f'disliked {comment_author}\'s comment: "{comment_content}"'
        elif comment_content:
            return f'disliked a comment: "{comment_content}"'
        elif comment_author:
            return f"disliked a comment by {comment_author}"
        return "disliked a comment"

    def _describe_search(self) -> str:
        """Search posts — includes search keywords"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f'searched for "{query}"' if query else "performed a search"

    def _describe_search_user(self) -> str:
        """Search users — includes search keywords"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f'searched for user "{query}"' if query else "searched for a user"

    def _describe_mute(self) -> str:
        """Mute user — includes the muted user's name"""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f'muted user "{target_user_name}"'
        return "muted a user"

    def _describe_generic(self) -> str:
        # For unknown action types, generate a generic description
        return f"performed action {self.action_type}"


class ZepGraphMemoryUpdater:
    """
    Zep graph memory updater

    Watches the simulation's actions log file and pushes new agent activity into
    the Zep graph in real time. Activity is grouped by platform; once BATCH_SIZE
    activities have accumulated for a platform, the batch is sent to Zep.

    All meaningful behaviors are pushed to Zep, and action_args contains full
    context information:
    - Original text of the post being liked/disliked
    - Original text of the post being reposted/quoted
    - Username of the user being followed/muted
    - Original text of the comment being liked/disliked
    """

    # Batch send size (how many activities accumulate per platform before sending)
    BATCH_SIZE = 5

    # Platform display-name map (used for console display)
    PLATFORM_DISPLAY_NAMES = {
        'twitter': 'World 1',
        'reddit': 'World 2',
    }

    # Send interval (seconds), to avoid sending requests too quickly
    SEND_INTERVAL = 0.5

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        """
        Initialize the updater

        Args:
            graph_id: Zep graph ID
            api_key: Zep API key (optional; defaults to value from config)
        """
        self.graph_id = graph_id
        self.api_key = api_key or Config.ZEP_API_KEY

        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")

        self.client = Zep(api_key=self.api_key)

        # Activity queue
        self._activity_queue: Queue = Queue()

        # Per-platform activity buffers (each platform accumulates to BATCH_SIZE then sends)
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        # Control flags
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Statistics
        self._total_activities = 0  # number of activities actually added to the queue
        self._total_sent = 0        # number of batches successfully sent to Zep
        self._total_items_sent = 0  # number of activity items successfully sent to Zep
        self._failed_count = 0      # number of batches that failed to send
        self._skipped_count = 0     # number of activities filtered/skipped (DO_NOTHING)

        logger.info(f"ZepGraphMemoryUpdater initialized: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")

    def _get_platform_display_name(self, platform: str) -> str:
        """Get the display name for the platform"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        """Start the background worker thread"""
        if self._running:
            return

        # Capture locale before spawning background thread
        current_locale = get_locale()

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(current_locale,),
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater started: graph_id={self.graph_id}")

    def stop(self):
        """Stop the background worker thread"""
        self._running = False

        # Send any remaining activities
        self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(f"ZepGraphMemoryUpdater stopped: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")

    def add_activity(self, activity: AgentActivity):
        """
        Add an agent activity to the queue.

        All meaningful behaviors are added to the queue, including:
        - CREATE_POST (publish a post)
        - CREATE_COMMENT (post a comment)
        - QUOTE_POST (quote a post)
        - SEARCH_POSTS (search posts)
        - SEARCH_USER (search users)
        - LIKE_POST/DISLIKE_POST (like/dislike a post)
        - REPOST (repost)
        - FOLLOW (follow)
        - MUTE (mute)
        - LIKE_COMMENT/DISLIKE_COMMENT (like/dislike a comment)

        action_args contains the full context (e.g., original post text, usernames, etc.).

        Args:
            activity: Agent activity record
        """
        # Skip DO_NOTHING activities
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"Added activity to Zep queue: {activity.agent_name} - {activity.action_type}")

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        Add an activity from a dict.

        Args:
            data: Dict parsed from actions.jsonl
            platform: Platform name (twitter/reddit)
        """
        # Skip event-type entries
        if "event_type" in data:
            return

        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )

        self.add_activity(activity)

    def _worker_loop(self, locale: str = 'zh'):
        """Background worker loop — sends activity to Zep in per-platform batches"""
        set_locale(locale)
        while self._running or not self._activity_queue.empty():
            try:
                # Try to grab an activity from the queue (1 second timeout)
                try:
                    activity = self._activity_queue.get(timeout=1)

                    # Add the activity to the corresponding platform's buffer
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        # Check whether the platform reached the batch size
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # Release the lock before sending
                            self._send_batch_activities(batch, platform)
                            # Send interval, to avoid sending requests too quickly
                            time.sleep(self.SEND_INTERVAL)

                except Empty:
                    pass

            except Exception as e:
                logger.error(f"Worker loop exception: {e}")
                time.sleep(1)

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        Send a batch of activities to the Zep graph (merged into one text payload)

        Args:
            activities: List of agent activities
            platform: Platform name
        """
        if not activities:
            return

        # Merge multiple activities into one text payload, separated by newlines
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)

        # Send with retry
        for attempt in range(self.MAX_RETRIES):
            try:
                self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text
                )

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"Successfully sent batch of {len(activities)} {display_name} activities to graph {self.graph_id}")
                logger.debug(f"Batch content preview: {combined_text[:200]}...")
                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Batch send to Zep failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Batch send to Zep failed after {self.MAX_RETRIES} retries: {e}")
                    self._failed_count += 1

    def _flush_remaining(self):
        """Send any activities remaining in the queue and per-platform buffers"""
        # First, drain remaining activities from the queue into the buffers
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break

        # Then send remaining activities in each platform's buffer (even if below BATCH_SIZE)
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"Sending {len(buffer)} remaining activities for {display_name}")
                    self._send_batch_activities(buffer, platform)
            # Clear all buffers
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # total activities added to queue
            "batches_sent": self._total_sent,            # number of batches successfully sent
            "items_sent": self._total_items_sent,        # number of activity items successfully sent
            "failed_count": self._failed_count,          # number of batches that failed to send
            "skipped_count": self._skipped_count,        # number of activities filtered/skipped (DO_NOTHING)
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # per-platform buffer sizes
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    Manages multiple simulations' Zep graph memory updaters.

    Each simulation can have its own updater instance.
    """

    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """
        Create a graph-memory updater for the given simulation.

        Args:
            simulation_id: Simulation ID
            graph_id: Zep graph ID

        Returns:
            ZepGraphMemoryUpdater instance
        """
        with cls._lock:
            # If one already exists, stop the old one first
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            updater = ZepGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater

            logger.info(f"Created graph memory updater: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """Get the simulation's updater"""
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        """Stop and remove the simulation's updater"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"Stopped graph memory updater: simulation_id={simulation_id}")

    # Flag to prevent stop_all from being called repeatedly
    _stop_all_done = False

    @classmethod
    def stop_all(cls):
        """Stop all updaters"""
        # Prevent repeated calls
        if cls._stop_all_done:
            return
        cls._stop_all_done = True

        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"Failed to stop updater: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("Stopped all graph memory updaters")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """Get stats for all updaters"""
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }
