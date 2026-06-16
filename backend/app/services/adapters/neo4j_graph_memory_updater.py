"""
Neo4j 图谱记忆更新服务
将模拟中的 Agent 活动动态更新到 Neo4j 图谱中
替代 ZepGraphMemoryUpdater
"""

import time
import threading
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue, Empty

if TYPE_CHECKING:
    from neo4j import Driver

from .llm_extractor import LLMExtractionPipeline
from ...utils.logger import get_logger
from ...utils.locale import get_locale, set_locale

logger = get_logger('mirofish.neo4j_memory_updater')


def _safe_neo4j_identifier(value: str, fallback: str = "RELATED_TO") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value or ""))
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


@dataclass
class AgentActivity:
    """Agent 活动记录"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """
        将活动转换为可以写入 Neo4j 的文本描述

        采用自然语言描述格式，让 LLM 能够从中提取实体和关系
        """
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

        describe_func = action_descriptions.get(
            self.action_type,
            self._describe_generic
        )
        description = describe_func()

        return f"{self.agent_name}: {description}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"发布了一条帖子：「{content}」"
        return "发布了一条帖子"

    def _describe_like_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"点赞了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"点赞了一条帖子：「{post_content}」"
        elif post_author:
            return f"点赞了{post_author}的一条帖子"
        return "点赞了一条帖子"

    def _describe_dislike_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"踩了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"踩了一条帖子：「{post_content}」"
        elif post_author:
            return f"踩了{post_author}的一条帖子"
        return "踩了一条帖子"

    def _describe_repost(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")

        if original_content and original_author:
            return f"转发了{original_author}的帖子：「{original_content}」"
        elif original_content:
            return f"转发了一条帖子：「{original_content}」"
        elif original_author:
            return f"转发了{original_author}的一条帖子"
        return "转发了一条帖子"

    def _describe_quote_post(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")

        base = ""
        if original_content and original_author:
            base = f"引用了{original_author}的帖子「{original_content}」"
        elif original_content:
            base = f"引用了一条帖子「{original_content}」"
        elif original_author:
            base = f"引用了{original_author}的一条帖子"
        else:
            base = "引用了一条帖子"

        if quote_content:
            base += f"，并评论道：「{quote_content}」"
        return base

    def _describe_follow(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        if target_user_name:
            return f"关注了用户「{target_user_name}」"
        return "关注了一个用户"

    def _describe_create_comment(self) -> str:
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if content:
            if post_content and post_author:
                return f"在{post_author}的帖子「{post_content}」下评论道：「{content}」"
            elif post_content:
                return f"在帖子「{post_content}」下评论道：「{content}」"
            elif post_author:
                return f"在{post_author}的帖子下评论道：「{content}」"
            return f"评论道：「{content}」"
        return "发表了评论"

    def _describe_like_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"点赞了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"点赞了一条评论：「{comment_content}」"
        elif comment_author:
            return f"点赞了{comment_author}的一条评论"
        return "点赞了一条评论"

    def _describe_dislike_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"踩了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"踩了一条评论：「{comment_content}」"
        elif comment_author:
            return f"踩了{comment_author}的一条评论"
        return "踩了一条评论"

    def _describe_search(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"搜索了「{query}」" if query else "进行了搜索"

    def _describe_search_user(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"搜索了用户「{query}」" if query else "搜索了用户"

    def _describe_mute(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        if target_user_name:
            return f"屏蔽了用户「{target_user_name}」"
        return "屏蔽了一个用户"

    def _describe_generic(self) -> str:
        return f"执行了{self.action_type}操作"


class Neo4jGraphMemoryUpdater:
    """
    Neo4j 图谱记忆更新器

    监控模拟的 actions 日志文件，将新的 agent 活动实时更新到 Neo4j 图谱中。
    按平台分组，每累积 BATCH_SIZE 条活动后批量处理。
    """

    # 批量发送大小
    BATCH_SIZE = 5

    # 平台显示名称
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '世界1',
        'reddit': '世界2',
    }

    # 发送间隔（秒）
    SEND_INTERVAL = 0.5

    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(
        self,
        graph_id: str,
        driver: 'Driver' = None,
        llm_extractor: LLMExtractionPipeline = None
    ):
        """
        初始化更新器

        Args:
            graph_id: 图谱ID
            driver: Neo4j 驱动
            llm_extractor: LLM 提取器
        """
        from ...utils.neo4j.driver import get_neo4j_driver

        self.graph_id = graph_id
        self.driver = driver or get_neo4j_driver()
        self.extractor = llm_extractor or LLMExtractionPipeline()

        # 活动队列
        self._activity_queue: Queue = Queue()

        # 按平台分组的活动缓冲区
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        # 控制标志
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # 统计
        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0

        logger.info(
            f"Neo4jGraphMemoryUpdater 初始化完成: "
            f"graph_id={graph_id}, batch_size={self.BATCH_SIZE}"
        )

    def _get_platform_display_name(self, platform: str) -> str:
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        """启动后台工作线程"""
        if self._running:
            return

        current_locale = get_locale()

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(current_locale,),
            daemon=True,
            name=f"Neo4jMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"Neo4jGraphMemoryUpdater 已启动: graph_id={self.graph_id}")

    def stop(self):
        """停止后台工作线程"""
        self._running = False

        # 发送剩余的活动
        self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(
            f"Neo4jGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
            f"total_activities={self._total_activities}, "
            f"batches_sent={self._total_sent}, "
            f"items_sent={self._total_items_sent}, "
            f"failed={self._failed_count}, "
            f"skipped={self._skipped_count}"
        )

    def add_activity(self, activity: AgentActivity):
        """
        添加一个 agent 活动到队列

        Args:
            activity: Agent 活动记录
        """
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(
            f"添加活动到队列: {activity.agent_name} - {activity.action_type}"
        )

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        从字典数据添加活动

        Args:
            data: 从 actions.jsonl 解析的字典数据
            platform: 平台名称 (twitter/reddit)
        """
        # 跳过事件类型的条目
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
        """后台工作循环 - 按平台批量发送活动到 Neo4j"""
        set_locale(locale)

        while self._running or not self._activity_queue.empty():
            try:
                # 尝试从队列获取活动（超时1秒）
                try:
                    activity = self._activity_queue.get(timeout=1)

                    # 将活动添加到对应平台的缓冲区
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        # 检查该平台是否达到批量大小
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # 释放锁后再发送
                            self._send_batch_activities(batch, platform)
                            # 发送间隔，避免请求过快
                            time.sleep(self.SEND_INTERVAL)

                except Empty:
                    pass

            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)

    def _send_batch_activities(
        self,
        activities: List[AgentActivity],
        platform: str
    ):
        """
        批量发送活动到 Neo4j 图谱

        Args:
            activities: Agent 活动列表
            platform: 平台名称
        """
        if not activities:
            return

        # 将活动转换为文本
        activity_texts = [activity.to_episode_text() for activity in activities]

        # 带重试的发送
        for attempt in range(self.MAX_RETRIES):
            try:
                # 使用 LLM 提取实体和关系
                ontology = self._get_activity_ontology()
                entities, edges = self.extractor.extract_from_chunks(
                    chunks=activity_texts,
                    ontology=ontology,
                    graph_id=self.graph_id,
                    parallel_workers=1
                )

                # 写入 Neo4j
                with self.driver.session() as session:
                    # 写入实体
                    for entity in entities:
                        self._write_activity_node(session, entity)

                    # 建立映射并写入边
                    name_to_uuid = self._get_name_to_uuid_mapping(session)
                    for edge in edges:
                        self._write_activity_edge(session, edge, name_to_uuid)

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(
                    f"成功批量发送 {len(activities)} 条{display_name}活动到图谱 {self.graph_id}"
                )
                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"批量发送到 Neo4j 失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}"
                    )
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(
                        f"批量发送到 Neo4j 失败，已重试{self.MAX_RETRIES}次: {e}"
                    )
                    self._failed_count += 1

    def _get_activity_ontology(self) -> Dict[str, Any]:
        """获取活动提取用的简化本体"""
        return {
            "entity_types": [
                {"name": "Agent", "description": "模拟中的 AI Agent"},
                {"name": "Post", "description": "社交媒体帖子"},
                {"name": "Comment", "description": "评论"},
                {"name": "User", "description": "用户"},
            ],
            "edge_types": [
                {"name": "POSTED", "description": "发布"},
                {"name": "LIKED", "description": "点赞"},
                {"name": "COMMENTED_ON", "description": "评论"},
                {"name": "FOLLOWED", "description": "关注"},
                {"name": "REPOSTED", "description": "转发"},
            ]
        }

    def _write_activity_node(self, session, entity) -> None:
        """写入活动节点"""
        entity_type = _safe_neo4j_identifier(entity.entity_type or "Agent", "Agent")
        labels = ["Entity", f"Entity_{entity_type}", "Activity"]

        properties = {
            "uuid": str(uuid.uuid4()),
            "name": entity.name,
            "summary": entity.summary,
            "graph_id": self.graph_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entity_type": entity_type
        }

        label_str = ":".join(labels)
        set_clause = ", ".join([f"n.{k} = ${k}" for k in properties.keys()])

        cypher = f"""
        MERGE (n:{label_str} {{name: $name, graph_id: $graph_id}})
        ON CREATE SET {set_clause}
        ON MATCH SET {set_clause}
        """

        try:
            session.run(cypher, **properties)
        except Exception as e:
            logger.warning(f"写入活动节点失败: {entity.name}, {e}")

    def _write_activity_edge(
        self,
        session,
        edge,
        name_to_uuid: Dict[str, str]
    ) -> None:
        """写入活动边"""
        source_uuid = name_to_uuid.get(edge.source_name)
        target_uuid = name_to_uuid.get(edge.target_name)

        if not source_uuid or not target_uuid:
            return

        properties = {
            "uuid": str(uuid.uuid4()),
            "name": edge.name,
            "fact": edge.fact,
            "graph_id": self.graph_id,
            "source_node_uuid": source_uuid,
            "target_node_uuid": target_uuid,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }

        rel_type = _safe_neo4j_identifier(edge.name)
        cypher = f"""
        MATCH (source:Entity {{uuid: $source_node_uuid}})
        MATCH (target:Entity {{uuid: $target_node_uuid}})
        MERGE (source)-[r:`{rel_type}` {{
            graph_id: $graph_id,
            source_node_uuid: $source_node_uuid,
            target_node_uuid: $target_node_uuid
        }}]->(target)
        SET r.uuid = coalesce(r.uuid, $uuid),
            r.name = $name,
            r.fact = $fact,
            r.created_at = coalesce(r.created_at, $created_at)
        """

        try:
            session.run(cypher, **properties)
        except Exception as e:
            logger.warning(f"写入活动边失败: {edge.name}, {e}")

    def _get_name_to_uuid_mapping(self, session) -> Dict[str, str]:
        """获取节点名称到 UUID 的映射"""
        cypher = """
        MATCH (n:Entity)
        WHERE n.graph_id = $graph_id
        RETURN n.name AS name, n.uuid AS uuid
        """
        result = session.run(cypher, graph_id=self.graph_id)
        return {record["name"]: record["uuid"] for record in result}

    def _flush_remaining(self):
        """发送队列和缓冲区中剩余的活动"""
        # 首先处理队列中剩余的活动，添加到缓冲区
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

        # 发送各平台缓冲区中剩余的活动
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"发送{display_name}平台剩余的 {len(buffer)} 条活动")
                    self._send_batch_activities(buffer, platform)
            # 清空所有缓冲区
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class Neo4jGraphMemoryManager:
    """
    管理多个模拟的 Neo4j 图谱记忆更新器

    每个模拟可以有自己的更新器实例
    """

    _updaters: Dict[str, Neo4jGraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(
        cls,
        simulation_id: str,
        graph_id: str,
        driver=None,
        llm_extractor=None
    ) -> Neo4jGraphMemoryUpdater:
        """
        为模拟创建图谱记忆更新器

        Args:
            simulation_id: 模拟ID
            graph_id: 图谱ID
            driver: Neo4j 驱动
            llm_extractor: LLM 提取器

        Returns:
            Neo4jGraphMemoryUpdater 实例
        """
        with cls._lock:
            # 如果已存在，先停止旧的
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            updater = Neo4jGraphMemoryUpdater(
                graph_id=graph_id,
                driver=driver,
                llm_extractor=llm_extractor
            )
            updater.start()
            cls._updaters[simulation_id] = updater

            logger.info(
                f"创建图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}"
            )
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[Neo4jGraphMemoryUpdater]:
        """获取模拟的更新器"""
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        """停止并移除模拟的更新器"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止图谱记忆更新器: simulation_id={simulation_id}")

    @classmethod
    def stop_all(cls):
        """停止所有更新器"""
        if cls._updaters:
            for simulation_id, updater in list(cls._updaters.items()):
                try:
                    updater.stop()
                except Exception as e:
                    logger.error(f"停止更新器失败: simulation_id={simulation_id}, error={e}")
            cls._updaters.clear()
            logger.info("已停止所有图谱记忆更新器")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有更新器的统计信息"""
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }


# 导入 uuid
import uuid
