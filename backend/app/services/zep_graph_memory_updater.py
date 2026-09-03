"""Stream agent activity from a running simulation into its Zep graph."""

import time
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep import (
    ZEP_INGESTION_WAIT_TIMEOUT_SECONDS,
    call_zep_read_with_retry,
    get_zep_client,
)

logger = get_logger('sosim.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """One action an agent took during a simulation round."""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """Render the activity as the natural-language episode Zep ingests.

        The wording stays plain prose so Zep can extract entities and
        relations from it. No simulation-specific prefix is added, because
        that would skew the extracted graph.
        """
        # Each action type gets its own phrasing.
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
        
        # Keep the event time in the source text as well as episode metadata so
        # temporal extraction does not collapse a multi-action batch.
        return (
            f"[{self.timestamp}] [{self.platform} round {self.round_num}] "
            f"{self.agent_name}: {description}"
        )
    
    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f'posted: "{content}"'
        return "posted"

    def _describe_like_post(self) -> str:
        """Describe a post like, quoting the post and naming its author."""
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
        """Describe a post dislike, quoting the post and naming its author."""
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
        """Describe a repost, quoting the original and naming its author."""
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
        """Describe a quote post: the original, its author, and the comment."""
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
            base += f', adding: "{quote_content}"'
        return base

    def _describe_follow(self) -> str:
        """Describe a follow, naming the followed user."""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f'followed the user "{target_user_name}"'
        return "followed a user"

    def _describe_create_comment(self) -> str:
        """Describe a comment, quoting it and the post it replies to."""
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
        """Describe a comment like, quoting it and naming its author."""
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
        """Describe a comment dislike, quoting it and naming its author."""
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
        """Describe a post search, quoting the search terms."""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f'searched for "{query}"' if query else "ran a search"

    def _describe_search_user(self) -> str:
        """Describe a user search, quoting the search terms."""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f'searched for the user "{query}"' if query else "searched for a user"

    def _describe_mute(self) -> str:
        """Describe a mute, naming the muted user."""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f'muted the user "{target_user_name}"'
        return "muted a user"

    def _describe_generic(self) -> str:
        # Unknown action types still need a readable sentence for Zep.
        return f"performed a {self.action_type} action"


class _DrainDeadlineExceeded(TimeoutError):
    def __init__(self, processed_count: int):
        super().__init__("Zep updater drain deadline elapsed")
        self.processed_count = processed_count


class ZepGraphMemoryUpdater:
    """
    Push simulation agent activity into a Zep graph.

    Activity read from the simulation action logs is buffered per platform and
    sent to Zep once a platform has accumulated BATCH_SIZE entries.

    Every meaningful action is forwarded, and action_args carries the full
    context with it:
    - the text of a liked or disliked post
    - the text of a reposted or quoted post
    - the name of a followed or muted user
    - the text of a liked or disliked comment
    """

    # Entries buffered per platform before a batch is sent.
    BATCH_SIZE = 5

    # Console-facing names for the two simulated platforms.
    PLATFORM_DISPLAY_NAMES = {
        'twitter': 'World 1',
        'reddit': 'World 2',
    }

    # Seconds between batches, so Zep is not hammered.
    SEND_INTERVAL = 0.5
    
    # Zep recommends keeping an episode below 10,000 characters. Leave room
    # for future source formatting changes.
    MAX_EPISODE_CHARS = 9_500
    
    def __init__(
        self,
        graph_id: str,
        api_key: Optional[str] = None,
        simulation_id: Optional[str] = None,
    ):
        """Create an updater bound to one graph.

        Args:
            graph_id: Zep graph ID
            api_key: Zep API key; falls back to the configured one
            simulation_id: Simulation the activity belongs to
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id or "unknown"
        self.api_key = api_key or Config.ZEP_API_KEY
        
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured.")
        
        self.client = get_zep_client(self.api_key)
        
        self._activity_queue: Queue = Queue()

        # One buffer per platform; each is flushed on its own once it reaches
        # BATCH_SIZE.
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()
        self._acceptance_lock = threading.Lock()
        
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Counters
        self._total_activities = 0  # activities enqueued
        self._total_sent = 0        # batches accepted by Zep
        self._total_items_sent = 0  # activities accepted by Zep
        self._failed_count = 0      # batches that failed to send
        self._skipped_count = 0     # activities filtered out, such as DO_NOTHING
        self._failed_batches: List[Dict[str, Any]] = []
        self._pending_episode_uuids: List[str] = []

        logger.info(f"ZepGraphMemoryUpdater initialized: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")

    def _get_platform_display_name(self, platform: str) -> str:
        """Return the console-facing name for a platform."""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        """Start the background worker thread."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater started: graph_id={self.graph_id}")
    
    def stop(self):
        """Drain the worker, flush tail events, and wait for Cloud ingestion."""
        deadline = time.time() + ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
        # Serialize the accepting->closed transition with add_activity's
        # check+enqueue operation. This closes the small race where a producer
        # could enqueue after both the worker and final flush had exited.
        with self._acceptance_lock:
            self._running = False

        if self._worker_thread and self._worker_thread.is_alive():
            join_timeout = max(0.0, deadline - time.time())
            self._worker_thread.join(timeout=join_timeout)
            if self._worker_thread.is_alive():
                raise TimeoutError(
                    f"Zep updater worker did not stop within {join_timeout:.0f}s"
                )

        # The worker has drained the queue. Only now is it safe to flush
        # buffers; doing this before join loses an item already dequeued by the
        # worker but not yet buffered.
        self._flush_remaining(deadline=deadline)

        if self._failed_batches:
            raise RuntimeError(
                f"{len(self._failed_batches)} Zep activity batch(es) failed; "
                "simulation graph ingestion is incomplete"
            )

        self._wait_for_pending_episodes(deadline=deadline)
        
        logger.info(f"ZepGraphMemoryUpdater stopped: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")
    
    def add_activity(self, activity: AgentActivity):
        """Enqueue one agent activity.

        Every meaningful action is enqueued:
        - CREATE_POST, CREATE_COMMENT, QUOTE_POST
        - SEARCH_POSTS, SEARCH_USER
        - LIKE_POST, DISLIKE_POST, REPOST
        - FOLLOW, MUTE
        - LIKE_COMMENT, DISLIKE_COMMENT

        action_args carries the full context with it, such as the text of the
        post being acted on and the name of the user involved.

        Args:
            activity: The agent activity to enqueue
        """
        # DO_NOTHING carries no signal for the graph.
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        with self._acceptance_lock:
            if not self._running:
                raise RuntimeError("Zep graph updater is not running")
            self._activity_queue.put(activity)
            self._total_activities += 1
        logger.debug(f"Queued activity for Zep: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """Enqueue one activity parsed from an actions.jsonl line.

        Args:
            data: One decoded actions.jsonl record
            platform: Platform name, twitter or reddit
        """
        # Lifecycle events are not agent activity.
        if "event_type" in data:
            return
        if data.get("success") is False:
            self._skipped_count += 1
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
    
    def _worker_loop(self):
        """Drain the queue, batching activity per platform on the way to Zep."""
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)

                    platform = activity.platform.lower()
                    batch = None
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]

                    # Never hold the buffer lock across network I/O or sleep.
                    if batch:
                        self._send_batch_activities(batch, platform)
                        time.sleep(self.SEND_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"Worker loop failed: {e}")
                time.sleep(1)
    
    def _build_episode_payloads(
        self,
        activities: List[AgentActivity],
    ) -> List[tuple[List[AgentActivity], str]]:
        payloads: List[tuple[List[AgentActivity], str]] = []
        current_activities: List[AgentActivity] = []
        current_lines: List[str] = []
        current_length = 0

        for activity in activities:
            text = activity.to_episode_text()
            if len(text) > self.MAX_EPISODE_CHARS:
                marker = "... [truncated by SoSim]"
                text = text[: self.MAX_EPISODE_CHARS - len(marker)] + marker
            projected_length = current_length + (1 if current_lines else 0) + len(text)
            if current_lines and projected_length > self.MAX_EPISODE_CHARS:
                payloads.append((current_activities, "\n".join(current_lines)))
                current_activities = []
                current_lines = []
                current_length = 0
            current_activities.append(activity)
            current_lines.append(text)
            current_length += (1 if len(current_lines) > 1 else 0) + len(text)

        if current_lines:
            payloads.append((current_activities, "\n".join(current_lines)))
        return payloads

    def _send_batch_activities(
        self,
        activities: List[AgentActivity],
        platform: str,
        *,
        deadline: float | None = None,
    ) -> int:
        """Send a batch of activities to the graph as combined episode text.

        Args:
            activities: The activities to send
            platform: Platform the activities came from
            deadline: Monotonic wall-clock deadline for the whole batch

        Returns:
            How many activities were accounted for, sent or failed
        """
        if not activities:
            return 0

        processed_count = 0
        for payload_activities, combined_text in self._build_episode_payloads(activities):
            if deadline is not None and time.time() >= deadline:
                raise _DrainDeadlineExceeded(processed_count)
            try:
                episode = self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text,
                    created_at=self._to_rfc3339(payload_activities[-1].timestamp),
                    source_description="SoSim simulation activity batch",
                    metadata={
                        "source": "sosim_simulation",
                        "simulation_id": self.simulation_id,
                        "platform": platform,
                        "activity_count": len(payload_activities),
                        "first_round": min(a.round_num for a in payload_activities),
                        "last_round": max(a.round_num for a in payload_activities),
                        "agent_ids": ",".join(
                            str(value)
                            for value in sorted({a.agent_id for a in payload_activities})
                        ),
                        "action_types": ",".join(
                            value
                            for value in sorted({a.action_type for a in payload_activities})
                            if value
                        ) or "unknown",
                    },
                )

                episode_uuid = (
                    getattr(episode, "uuid_", None)
                    or getattr(episode, "uuid", None)
                )
                if not episode_uuid:
                    raise RuntimeError("Zep graph.add returned no episode UUID")
                self._pending_episode_uuids.append(str(episode_uuid))
                self._total_sent += 1
                self._total_items_sent += len(payload_activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"Sent {len(payload_activities)} {display_name} activities to graph {self.graph_id}")
                logger.debug(f"Batch preview: {combined_text[:200]}...")

            except Exception as e:
                # graph.add has no idempotency key. Replaying an ambiguous
                # response can duplicate extracted facts, so fail closed and
                # surface the incomplete batch to SimulationRunner.
                logger.error(f"Failed to send batch to Zep; the non-idempotent write was not replayed: {e}")
                self._failed_count += 1
                self._failed_batches.append({
                    "platform": platform,
                    "activities": payload_activities,
                    "error": str(e),
                })
            finally:
                # Successes have a confirmed episode UUID; failures are kept
                # durably in _failed_batches and must never be replayed. Either
                # way this payload is accounted for before moving on.
                processed_count += len(payload_activities)
        return processed_count

    @staticmethod
    def _to_rfc3339(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return parsed.isoformat()
        except (AttributeError, TypeError, ValueError):
            return datetime.now().astimezone().isoformat()

    def _flush_remaining(self, *, deadline: float | None = None):
        """Send whatever is still sitting in the queue and the buffers."""
        # Move anything left in the queue into its platform buffer first.
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
        
        for platform in list(self._platform_buffers):
            with self._buffer_lock:
                buffer = list(self._platform_buffers.get(platform, []))
            if not buffer:
                continue
            display_name = self._get_platform_display_name(platform)
            logger.info(f"Sending {len(buffer)} remaining {display_name} activities")
            if deadline is not None and time.time() >= deadline:
                raise TimeoutError(
                    "Zep updater drain deadline elapsed before flushing all activities"
                )
            try:
                processed_count = self._send_batch_activities(
                    buffer,
                    platform,
                    deadline=deadline,
                )
            except _DrainDeadlineExceeded as error:
                with self._buffer_lock:
                    del self._platform_buffers[platform][:error.processed_count]
                raise TimeoutError(str(error)) from error
            else:
                with self._buffer_lock:
                    del self._platform_buffers[platform][:processed_count]

    def _wait_for_pending_episodes(self, *, deadline: float | None = None) -> None:
        pending = set(self._pending_episode_uuids)
        if not pending:
            return

        if deadline is None:
            deadline = time.time() + ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
        while pending:
            if time.time() >= deadline:
                raise TimeoutError(
                    f"Zep simulation ingestion timed out with {len(pending)} "
                    "episode(s) pending"
                )
            for episode_uuid in list(pending):
                episode = call_zep_read_with_retry(
                    lambda: self.client.graph.episode.get(uuid_=episode_uuid),
                    operation_name=f"poll simulation episode {episode_uuid}",
                )
                if getattr(episode, "processed", False):
                    pending.remove(episode_uuid)
            if pending:
                time.sleep(3)
        self._pending_episode_uuids = []
    
    def get_stats(self) -> Dict[str, Any]:
        """Return a snapshot of the updater's counters."""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # activities enqueued
            "batches_sent": self._total_sent,            # batches accepted by Zep
            "items_sent": self._total_items_sent,        # activities accepted by Zep
            "failed_count": self._failed_count,          # batches that failed to send
            "pending_episode_count": len(self._pending_episode_uuids),
            "skipped_count": self._skipped_count,        # activities filtered out, such as DO_NOTHING
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # buffered entries per platform
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """Own the Zep graph memory updaters, one per running simulation."""
    
    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """Create and start the graph memory updater for one simulation.

        Args:
            simulation_id: Simulation ID
            graph_id: Zep graph ID

        Returns:
            The started ZepGraphMemoryUpdater
        """
        with cls._lock:
            # Stop an updater left over from a previous run first.
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            
            updater = ZepGraphMemoryUpdater(
                graph_id,
                simulation_id=simulation_id,
            )
            updater.start()
            cls._updaters[simulation_id] = updater
            cls._stop_all_done = False
            
            logger.info(f"Created graph memory updater: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """Return the updater for one simulation, if it still exists."""
        with cls._lock:
            return cls._updaters.get(simulation_id)

    @classmethod
    def get_simulation_ids_for_graph(cls, graph_id: str) -> List[str]:
        """Return simulations whose updater still owns or drains this graph."""

        with cls._lock:
            return sorted(
                simulation_id
                for simulation_id, updater in cls._updaters.items()
                if updater.graph_id == graph_id
            )

    @classmethod
    def get_simulation_ids(cls) -> List[str]:
        """Return every simulation with a retained updater."""

        with cls._lock:
            return sorted(cls._updaters)

    @classmethod
    def discard_inactive_updater(cls, simulation_id: str) -> bool:
        """Discard a failed, fully stopped updater during graph destruction."""

        with cls._lock:
            updater = cls._updaters.get(simulation_id)
            if updater is None:
                return False
            worker_alive = bool(
                updater._worker_thread and updater._worker_thread.is_alive()
            )
            if updater._running or worker_alive:
                raise RuntimeError(
                    f"Zep updater for {simulation_id} is still active"
                )
            cls._updaters.pop(simulation_id, None)
        logger.warning(
            "Discarded incomplete Zep updater during explicit graph deletion: "
            "simulation_id=%s, graph_id=%s",
            simulation_id,
            updater.graph_id,
        )
        return True
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """Stop one simulation's updater and drop it once it has drained."""
        with cls._lock:
            updater = cls._updaters.get(simulation_id)
        if updater is None:
            return

        # Do not hold the manager lock through up to several minutes of Cloud
        # polling. Crucially, only remove the updater after a successful drain;
        # on failure it remains visible to report/deletion barriers and can be
        # stopped again.
        updater.stop()
        with cls._lock:
            if cls._updaters.get(simulation_id) is updater:
                cls._updaters.pop(simulation_id, None)
        logger.info(f"Stopped graph memory updater: simulation_id={simulation_id}")
    
    # Guards stop_all against being run twice.
    _stop_all_done = False

    @classmethod
    def stop_all(cls):
        """Stop every updater, keeping the ones that fail registered."""
        if cls._stop_all_done:
            return

        with cls._lock:
            simulation_ids = list(cls._updaters)

        errors = []
        for simulation_id in simulation_ids:
            try:
                cls.stop_updater(simulation_id)
            except Exception as error:
                # Keep a failed updater registered so the caller can retry and
                # lifecycle/report guards still see the incomplete ingestion.
                logger.error(
                    "Failed to stop updater: simulation_id=%s, error=%s",
                    simulation_id,
                    error,
                )
                errors.append((simulation_id, error))

        with cls._lock:
            cls._stop_all_done = not cls._updaters

        if errors:
            details = "; ".join(
                f"{simulation_id}: {error}"
                for simulation_id, error in errors
            )
            raise RuntimeError(
                f"Some graph memory updaters did not stop cleanly: {details}"
            )
        logger.info("Stopped all graph memory updaters")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """Return the counters of every registered updater."""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
