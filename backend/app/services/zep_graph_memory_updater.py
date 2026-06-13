"""
Dịch vụ cập nhật bộ nhớ đồ thị (Graphiti + Neo4j backend)
Cập nhật động các hoạt động của Agent trong mô phỏng lên đồ thị tri thức
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue, Empty

from graphiti_core.nodes import EpisodeType

from ..config import Config
from ..utils.logger import get_logger
from ..utils.graphiti_client import get_graphiti, run_async

logger = get_logger('mirofish.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """Bản ghi hoạt động của Agent"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str
    
    def to_episode_text(self) -> str:
        """
        Chuyển đổi hoạt động thành mô tả văn bản để gửi cho Zep
        
        Sử dụng định dạng mô tả bằng ngôn ngữ tự nhiên để Zep có thể trích xuất thực thể và mối quan hệ
        Không thêm tiền tố liên quan đến mô phỏng để tránh gây nhiễu khi cập nhật đồ thị
        """
        # Tạo mô tả khác nhau dựa trên từng loại hành động
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
        
        # Trả về trực tiếp định dạng "Tên agent: Mô tả hoạt động", không thêm tiền tố mô phỏng
        return f"{self.agent_name}: {description}"
    
    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"posted a post: `{content}`"
        return "posted a post"
    
    def _describe_like_post(self) -> str:
        """Like bài viết - bao gồm nội dung gốc bài viết và thông tin tác giả"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"liked {post_author}'s post: `{post_content}`"
        elif post_content:
            return f"liked a post: `{post_content}`"
        elif post_author:
            return f"liked a post by {post_author}"
        return "liked a post"
    
    def _describe_dislike_post(self) -> str:
        """Dislike bài viết - bao gồm nội dung gốc và thông tin tác giả"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"disliked {post_author}'s post: `{post_content}`"
        elif post_content:
            return f"disliked a post: `{post_content}`"
        elif post_author:
            return f"disliked a post by {post_author}"
        return "disliked a post"
    
    def _describe_repost(self) -> str:
        """Repost bài viết - bao gồm nội dung gốc và thông tin tác giả"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        
        if original_content and original_author:
            return f"reposted {original_author}'s post: `{original_content}`"
        elif original_content:
            return f"reposted a post: `{original_content}`"
        elif original_author:
            return f"reposted a post by {original_author}"
        return "reposted a post"
    
    def _describe_quote_post(self) -> str:
        """Quote bài viết - bao gồm nội dung bài gốc, tác giả và nội dung bình luận quote"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        
        base = ""
        if original_content and original_author:
            base = f"quoted {original_author}'s post `{original_content}`"
        elif original_content:
            base = f"quoted a post `{original_content}`"
        elif original_author:
            base = f"quoted a post by {original_author}"
        else:
            base = "quoted a post"
        
        if quote_content:
            base += f" and commented: `{quote_content}`"
        return base
    
    def _describe_follow(self) -> str:
        """Follow người dùng - bao gồm tên người được follow"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"followed user `{target_user_name}`"
        return "followed a user"
    
    def _describe_create_comment(self) -> str:
        """Tạo bình luận - bao gồm nội dung bình luận và thông tin bài viết được bình luận"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if content:
            if post_content and post_author:
                return f"commented under {post_author}'s post `{post_content}`: `{content}`"
            elif post_content:
                return f"commented under post `{post_content}`: `{content}`"
            elif post_author:
                return f"commented under {post_author}'s post: `{content}`"
            return f"commented: `{content}`"
        return "posted a comment"
    
    def _describe_like_comment(self) -> str:
        """Like bình luận - bao gồm nội dung bình luận và tác giả"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"liked {comment_author}'s comment: `{comment_content}`"
        elif comment_content:
            return f"liked a comment: `{comment_content}`"
        elif comment_author:
            return f"liked a comment by {comment_author}"
        return "liked a comment"
    
    def _describe_dislike_comment(self) -> str:
        """Dislike bình luận - bao gồm nội dung bình luận và tác giả"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"disliked {comment_author}'s comment: `{comment_content}`"
        elif comment_content:
            return f"disliked a comment: `{comment_content}`"
        elif comment_author:
            return f"disliked a comment by {comment_author}"
        return "disliked a comment"
    
    def _describe_search(self) -> str:
        """Tìm kiếm bài viết - bao gồm từ khóa tìm kiếm"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"searched for `{query}`" if query else "performed a search"
    
    def _describe_search_user(self) -> str:
        """Tìm kiếm người dùng - bao gồm từ khóa tìm kiếm"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"searched for user `{query}`" if query else "searched for a user"
    
    def _describe_mute(self) -> str:
        """Mute người dùng - bao gồm tên người bị mute"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"muted user `{target_user_name}`"
        return "muted a user"
    
    def _describe_generic(self) -> str:
        # Tạo mô tả chung cho các loại hành động không xác định
        return f"performed {self.action_type} action"


class ZepGraphMemoryUpdater:
    """
    Trình cập nhật bộ nhớ đồ thị Zep
    
    Giám sát file log actions của mô phỏng, cập nhật trực tiếp các hoạt động mới của agent lên đồ thị Zep.
    Nhóm theo nền tảng, gửi hàng loạt lên Zep sau khi tích lũy đủ số lượng hoạt động (BATCH_SIZE).
    
    Tất cả các hành vi có ý nghĩa đều được cập nhật lên Zep, action_args chứa đầy đủ thông tin ngữ cảnh:
    - Nội dung gốc của bài viết được like/dislike
    - Nội dung gốc của bài viết được repost/quote
    - Tên người dùng được follow/mute
    - Nội dung gốc của bình luận được like/dislike
    """
    
    # Số lượng gửi mỗi lô (gửi sau khi mỗi nền tảng tích lũy đủ số lượng này)
    BATCH_SIZE = 5
    
    # Ánh xạ tên nền tảng (dùng để hiển thị trên console)
    PLATFORM_DISPLAY_NAMES = {
        'twitter': 'World 1',
        'reddit': 'World 2',
    }
    
    # Thời gian gửi cách nhau (giây), tránh request quá nhanh
    SEND_INTERVAL = 0.5
    
    # Cấu hình thử lại (retry)
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # giây
    
    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        """
        Khởi tạo trình cập nhật

        Args:
            graph_id: group_id của đồ thị Graphiti (Neo4j)
            api_key: giữ lại trong chữ ký để tương thích caller cũ, không còn dùng
                     (Graphiti lấy cấu hình Neo4j + LLM qua get_graphiti()).
        """
        self.graph_id = graph_id
        self.api_key = api_key

        # Graphiti instance lấy lazy per-thread qua get_graphiti() trong _send_batch_activities,
        # không khởi tạo client ở đây để tránh chia sẻ event loop giữa các thread.

        # Hàng đợi hoạt động
        self._activity_queue: Queue = Queue()
        
        # Bộ đệm hoạt động nhóm theo nền tảng (gửi hàng loạt sau khi đạt đến BATCH_SIZE)
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()
        
        # Cờ điều khiển
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # Thống kê
        self._total_activities = 0  # Số lượng hoạt động thực tế được thêm vào hàng đợi
        self._total_sent = 0        # Số đợt hàng gửi đi thành công tới Zep
        self._total_items_sent = 0  # Số lượng các hoạt động đã gửi thành công tới Zep
        self._failed_count = 0      # Số lượt gửi đi thất bại
        self._skipped_count = 0     # Số lượng các hoạt động bị filter bỏ qua (DO_NOTHING)
        
        logger.info(f"ZepGraphMemoryUpdater initialized: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")
    
    def _get_platform_display_name(self, platform: str) -> str:
        """Lấy tên hiển thị của nền tảng"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)
    
    def start(self):
        """Khởi chạy luồng làm việc dưới background"""
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
        """Tắt luồng làm việc dưới background"""
        self._running = False
        
        # Gửi nốt các hoạt động còn lại
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
        Thêm một hoạt động của agent vào hàng đợi
        
        Tất cả các hành vi có ý nghĩa đều sẽ được thêm vào hàng đợi, bao gồm:
        - CREATE_POST (Đăng bài)
        - CREATE_COMMENT (Bình luận)
        - QUOTE_POST (Trích dẫn bài viết)
        - SEARCH_POSTS (Tìm kiếm bài viết)
        - SEARCH_USER (Tìm kiếm người dùng)
        - LIKE_POST/DISLIKE_POST (Like/Dislike bài viết)
        - REPOST (Repost)
        - FOLLOW (Theo dõi)
        - MUTE (Chặn)
        - LIKE_COMMENT/DISLIKE_COMMENT (Like/dislike bình luận)
        
        action_args sẽ bao gồm toàn bộ thông tin ngữ cảnh (như nội dung gốc của bài viết, tên người dùng, v.v..).
        
        Args:
            activity: Bản ghi hoạt động của Agent
        """
        # Bỏ qua những hoạt động thuộc loại DO_NOTHING
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        
        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"Action added to Zep queue: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        Thêm hoạt động từ dữ liệu dictionary
        
        Args:
            data: Dữ liệu dictionary parse từ actions.jsonl
            platform: Tên nền tảng (twitter/reddit)
        """
        # Bỏ qua các mục liên quan tới thuộc loại sự kiện (event_type)
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
    
    def _worker_loop(self):
        """Vòng lặp làm việc chung (background) - Gửi hàng loạt các hoạt động lên Zep theo từng nền tảng"""
        while self._running or not self._activity_queue.empty():
            try:
                # Thử lấy hoạt động từ hàng đợi (Timeout: 1 giây)
                try:
                    activity = self._activity_queue.get(timeout=1)
                    
                    # Thêm hoạt động vào bộ đệm của nền tảng tương ứng
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        
                        # Kiểm tra xem nền tảng đã đủ số lượng batch (gửi hàng loạt) chưa
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # Gửi sau khi giải phóng lock
                            self._send_batch_activities(batch, platform)
                            # Thời gian giãn giữa mỗi lần gửi để tránh request quá nhanh
                            time.sleep(self.SEND_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)
    
    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        Gửi hàng loạt các hoạt động lên đồ thị tri thức (Gộp chung vào một episode)

        Args:
            activities: Danh sách hoạt động của Agent
            platform: Tên nền tảng
        """
        if not activities:
            return

        # Gộp nhiều hoạt động vào một văn bản chung, tách nhau bởi xuống dòng
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)

        # Gửi với cơ chế thử lại
        for attempt in range(self.MAX_RETRIES):
            try:
                # Graphiti add_episode xử lý đồng bộ (extract + ghi Neo4j xong khi await trả về).
                # group_id=self.graph_id để episode ghi vào đúng partition của simulation.
                graphiti = get_graphiti()
                run_async(graphiti.add_episode(
                    name=f"sim_{platform}_round_{activities[0].round_num}",
                    episode_body=combined_text,
                    source_description=f"MiroFish simulation activity ({platform})",
                    reference_time=datetime.now(timezone.utc),
                    source=EpisodeType.text,
                    group_id=self.graph_id,
                ))

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"Successfully sent batch of {len(activities)} {display_name} actions to graph {self.graph_id}")
                logger.debug(f"Batch content preview: {combined_text[:200]}...")
                return
                
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Failed to send batch to graph (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Failed to send batch to graph after {self.MAX_RETRIES} attempts: {e}")
                    self._failed_count += 1
    
    def _flush_remaining(self):
        """Gửi các hoạt động còn sót lại trong hàng đợi và bộ đệm"""
        # Đầu tiên xử lý các hoạt động sót lại trong hàng đợi, đưa vào bộ đệm
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
        
        # Tiếp sau đó là gửi các hoạt động nằm trong bộ đệm của từng nền tảng đi (mặc dù chưa đạt đến số lượng BATCH_SIZE)
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"Sending remaining {len(buffer)} actions for platform {display_name}")
                    self._send_batch_activities(buffer, platform)
            # Dọn sạch toàn bộ bộ đệm
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []
    
    def get_stats(self) -> Dict[str, Any]:
        """Lấy thông tin thống kê"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # Tổng số hoạt động được thêm vào hàng đợi
            "batches_sent": self._total_sent,            # Số đợt hàng đã gửi thành công
            "items_sent": self._total_items_sent,        # Số lượng hoạt động đã gửi thành công
            "failed_count": self._failed_count,          # Số đợt hàng gửi thất bại
            "skipped_count": self._skipped_count,        # Số lượng hoạt động bị bỏ qua (DO_NOTHING)
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # Kích thước bộ đệm của từng nền tảng
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    Quản lý các trình cập nhật bộ nhớ đồ thị Zep cho nhiều mô phỏng
    
    Mỗi mô phỏng có thể có instance trình cập nhật của riêng nó
    """
    
    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """
        Tạo trình cập nhật bộ nhớ đồ thị cho mô phỏng
        
        Args:
            simulation_id: ID của mô phỏng
            graph_id: ID của đồ thị Zep
            
        Returns:
            Instance của ZepGraphMemoryUpdater
        """
        with cls._lock:
            # Nếu đã tồn tại, dừng cái cũ lại trước
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            
            updater = ZepGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            
            logger.info(f"Created graph memory updater: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """Lấy trình cập nhật của mô phỏng"""
        return cls._updaters.get(simulation_id)
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """Dừng và gỡ bỏ trình cập nhật của mô phỏng"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"Graph memory updater stopped: simulation_id={simulation_id}")
    
    # Cờ ngăn chặn gọi stop_all lặp lại
    _stop_all_done = False
    
    @classmethod
    def stop_all(cls):
        """Dừng toàn bộ các trình cập nhật"""
        # Ngăn gọi lặp lại
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
            logger.info("All graph memory updaters stopped")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """Lấy thông tin thống kê của toàn bộ các trình cập nhật"""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
