"""
本地图谱记忆更新服务
将模拟中的Agent活动动态更新到本地Neo4j图谱中

实现与 ZepGraphMemoryUpdater 相同的接口，但使用本地 Neo4j 存储。
核心能力：
1. 接收 Agent 活动，转换为 episode 文本
2. 使用 LLM 提取实体和关系
3. 实体去重：与已有实体匹配合并
4. 矛盾检测：检测新事实与旧事实的矛盾
5. 边失效：将矛盾的旧边标记为失效
"""

import time
import threading
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from queue import Queue, Empty

from app.utils.logger import get_logger
from app.services.zep.zep_graph_memory_updater import AgentActivity  # 复用数据类
from .local_graph_store import LocalNeo4jGraphStore, LocalEntity, LocalRelation
from .local_graph_extractor import LocalGraphExtractor
from .local_edge_invalidator import RuleBasedEdgeInvalidator
from .local_entity_resolver import LocalEntityResolver

logger = get_logger('mirofish.local_graph_memory_updater')


class LocalGraphMemoryUpdater:
    """
    本地图谱记忆更新器
    
    监控模拟的Agent活动，将新的活动实时更新到本地Neo4j图谱中。
    按平台分组，每累积BATCH_SIZE条活动后批量处理。
    """
    
    # 批量处理大小
    BATCH_SIZE = 5
    
    # 平台名称映射
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '世界1',
        'reddit': '世界2',
    }
    
    # 处理间隔（秒）
    PROCESS_INTERVAL = 0.5
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    def __init__(self, graph_id: str):
        """
        初始化更新器
        
        Args:
            graph_id: 图谱ID
        """
        self.graph_id = graph_id
        
        # 初始化存储和提取器
        self._graph_store = LocalNeo4jGraphStore()
        self._extractor = LocalGraphExtractor()
        self._edge_invalidator = RuleBasedEdgeInvalidator()
        self._entity_resolver = LocalEntityResolver(self._graph_store)
        
        # 获取图谱的 ontology 用于提取
        self._ontology = self._load_ontology()
        
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
        self._total_processed = 0
        self._total_entities = 0
        self._total_relations = 0
        self._failed_count = 0
        self._skipped_count = 0
        
        logger.info(f"LocalGraphMemoryUpdater 初始化完成: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")
    
    def _load_ontology(self) -> Dict[str, Any]:
        """从图谱加载 ontology"""
        try:
            with self._graph_store._driver.session(database=self._graph_store._database) as session:
                result = session.run(
                    "MATCH (g:Graph {graph_id: $graph_id}) RETURN g.ontology_json AS ontology",
                    graph_id=self.graph_id
                )
                record = result.single()
                if record and record.get("ontology"):
                    import json
                    return json.loads(record.get("ontology"))
        except Exception as e:
            logger.warning(f"加载 ontology 失败: {e}")
        
        # 返回默认 ontology
        return {
            "entity_types": [
                {"name": "Person", "description": "人物实体"},
                {"name": "Organization", "description": "组织机构"},
                {"name": "Product", "description": "产品"},
                {"name": "Location", "description": "地点"},
                {"name": "Topic", "description": "话题或概念"},
            ],
            "edge_types": [
                {"name": "LIKES", "description": "喜欢"},
                {"name": "DISLIKES", "description": "不喜欢"},
                {"name": "FOLLOWS", "description": "关注"},
                {"name": "MENTIONS", "description": "提及"},
                {"name": "INTERACTS_WITH", "description": "互动"},
                {"name": "DISCUSSES", "description": "讨论"},
                {"name": "SUPPORTS", "description": "支持"},
                {"name": "OPPOSES", "description": "反对"},
            ],
        }
    
    def _get_platform_display_name(self, platform: str) -> str:
        """获取平台的显示名称"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)
    
    def start(self):
        """启动后台工作线程"""
        if self._running:
            return
        
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"LocalMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"LocalGraphMemoryUpdater 已启动: graph_id={self.graph_id}")
    
    def stop(self):
        """停止后台工作线程"""
        self._running = False
        
        # 处理剩余的活动
        self._flush_remaining()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)
        
        # 关闭图谱存储
        try:
            self._graph_store.close()
        except Exception:
            pass
        
        logger.info(f"LocalGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"processed={self._total_processed}, "
                   f"entities={self._total_entities}, "
                   f"relations={self._total_relations}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")
    
    def add_activity(self, activity: AgentActivity):
        """
        添加一个agent活动到队列
        
        Args:
            activity: Agent活动记录
        """
        # 跳过DO_NOTHING类型的活动
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        
        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"添加活动到本地图谱队列: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        从字典数据添加活动
        
        Args:
            data: 从actions.jsonl解析的字典数据
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
    
    def _worker_loop(self):
        """后台工作循环 - 按平台批量处理活动"""
        while self._running or not self._activity_queue.empty():
            try:
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
                            # 释放锁后再处理
                            self._process_batch_activities(batch, platform)
                            time.sleep(self.PROCESS_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)
    
    def _process_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        批量处理活动到本地图谱
        
        Args:
            activities: Agent活动列表
            platform: 平台名称
        """
        if not activities:
            return
        
        # 将多条活动合并为一条文本
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)
        
        # 生成 episode ID
        episode_id = f"ep_{uuid.uuid4().hex[:16]}"
        timestamp = datetime.now().isoformat()
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # 1. 使用 LLM 提取实体和关系
                extraction_result = self._extractor.extract(combined_text, self._ontology)
                
                extracted_entities = extraction_result.get("entities", [])
                extracted_relations = extraction_result.get("relations", [])
                
                if not extracted_entities and not extracted_relations:
                    logger.debug(f"批量处理: 未提取到实体或关系，跳过")
                    self._total_processed += len(activities)
                    return
                
                # 2. 处理实体（去重 + upsert）
                entity_uuid_map = self._process_entities(extracted_entities, timestamp)
                
                # 3. 处理关系（矛盾检测 + 失效 + upsert）
                self._process_relations(extracted_relations, entity_uuid_map, episode_id, timestamp)
                
                # 更新统计
                self._total_processed += len(activities)
                self._total_entities += len(extracted_entities)
                self._total_relations += len(extracted_relations)
                
                display_name = self._get_platform_display_name(platform)
                logger.info(f"成功处理 {len(activities)} 条{display_name}活动到本地图谱 "
                           f"(entities={len(extracted_entities)}, relations={len(extracted_relations)})")
                return
                
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"批量处理失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量处理失败，已重试{self.MAX_RETRIES}次: {e}")
                    self._failed_count += 1
    
    def _process_entities(self, entities: List[Dict], timestamp: str) -> Dict[str, str]:
        """
        处理提取的实体，使用 LocalEntityResolver 进行去重并 upsert
        
        流程（遵循 Zep/Graphiti 的两阶段策略）：
        1. 对每个提取的实体，使用 LocalEntityResolver 进行消歧
        2. 如果找到匹配的已有实体，复用其 UUID 并更新摘要
        3. 如果是新实体，创建新节点
        
        Args:
            entities: 提取的实体列表
            timestamp: 时间戳
            
        Returns:
            entity_uuid_map: {(name:type): uuid} 映射
        """
        entity_uuid_map: Dict[str, str] = {}
        new_entities: List[LocalEntity] = []
        entities_to_update: List[tuple] = []  # (uuid, summary, source_types)
        
        # 清空解析缓存（每批次独立处理）
        self._entity_resolver.clear_cache()
        
        project_id = self.graph_id.split("_")[2] if "_" in self.graph_id else "default"
        
        for ent in entities:
            name = ent.get("name", "").strip()
            entity_type = ent.get("type", "Entity").strip()
            summary = ent.get("summary", "")
            attributes = ent.get("attributes")
            
            if not name:
                continue
            
            # 使用 LocalEntityResolver 进行实体消歧
            resolved = self._entity_resolver.resolve(
                graph_id=self.graph_id,
                name=name,
                entity_type=entity_type,
                summary=summary,
                attributes=attributes,
            )
            
            # 记录 UUID 映射
            key = f"{name}:{entity_type}"
            
            if resolved.is_new:
                # 新实体：创建 LocalEntity
                local_ent = LocalEntity(
                    project_id=project_id,
                    graph_id=self.graph_id,
                    name=resolved.name,
                    entity_type=entity_type,
                    summary=summary,
                    attributes=attributes,
                    source_entity_types=[entity_type],
                    created_at=timestamp,
                )
                new_entities.append(local_ent)
                entity_uuid_map[key] = local_ent.uuid
                
                logger.debug(f"创建新实体: {name} (type={entity_type})")
            else:
                # 已有实体：复用 UUID
                entity_uuid_map[key] = resolved.uuid
                
                # 如果需要更新摘要或类型
                if resolved.should_update_summary and summary:
                    entities_to_update.append((resolved.uuid, summary, [entity_type]))
                elif entity_type:
                    # 至少追加类型信息
                    entities_to_update.append((resolved.uuid, None, [entity_type]))
                
                logger.debug(
                    f"复用已有实体: {name} -> {resolved.matched_uuid} "
                    f"(score={resolved.match_score:.2f})"
                )
        
        # 批量创建新实体
        if new_entities:
            self._graph_store.upsert_entities(new_entities)
        
        # 批量更新已有实体的摘要和类型
        for uuid, summary, source_types in entities_to_update:
            try:
                self._graph_store.update_entity_summary(
                    uuid=uuid,
                    summary=summary or "",
                    append_source_types=source_types,
                )
            except Exception as e:
                logger.warning(f"更新实体摘要失败: uuid={uuid}, error={e}")
        
        return entity_uuid_map
    
    def _find_existing_entity(self, name: str, entity_type: str) -> Optional[str]:
        """
        在图谱中查找已有实体的 UUID
        
        使用 LocalEntityResolver 进行消歧，而不是简单的精确匹配，
        以符合 Zep 的两阶段实体去重策略。
        
        Args:
            name: 实体名称
            entity_type: 实体类型
            
        Returns:
            已有实体的 UUID，如果不存在则返回 None
        """
        if not name or not name.strip():
            return None
        
        # 使用 EntityResolver 进行解析
        resolved = self._entity_resolver.resolve(
            graph_id=self.graph_id,
            name=name.strip(),
            entity_type=entity_type,
            summary="",
        )
        
        # 只返回已有实体的 UUID，不创建新实体
        if not resolved.is_new:
            return resolved.uuid
        
        return None
    
    def _process_relations(
        self,
        relations: List[Dict],
        entity_uuid_map: Dict[str, str],
        episode_id: str,
        timestamp: str
    ):
        """
        处理提取的关系，进行矛盾检测并 upsert
        
        Args:
            relations: 提取的关系列表
            entity_uuid_map: 实体名称到UUID的映射
            episode_id: Episode ID
            timestamp: 时间戳
        """
        local_relations: List[LocalRelation] = []
        
        for rel in relations:
            source_name = rel.get("source", "").strip()
            source_type = rel.get("source_type", "Entity").strip()
            target_name = rel.get("target", "").strip()
            target_type = rel.get("target_type", "Entity").strip()
            relation_name = rel.get("relation", "").strip()
            fact = rel.get("fact", "").strip()
            
            if not source_name or not target_name or not relation_name:
                continue
            
            # 获取源和目标的 UUID
            source_key = f"{source_name}:{source_type}"
            target_key = f"{target_name}:{target_type}"
            
            source_uuid = entity_uuid_map.get(source_key)
            target_uuid = entity_uuid_map.get(target_key)
            
            # 如果找不到映射的 UUID，尝试查找已有实体
            if not source_uuid:
                source_uuid = self._find_existing_entity(source_name, source_type)
            if not target_uuid:
                target_uuid = self._find_existing_entity(target_name, target_type)
            
            if not source_uuid or not target_uuid:
                logger.debug(f"跳过关系: 找不到实体 UUID - {source_name} -> {target_name}")
                continue
            
            # 获取实体间已有边（用于去重和矛盾检测）
            existing_edges = self._graph_store.get_edges_between_entities(
                self.graph_id, source_uuid, target_uuid, include_invalid=False
            )
            
            # ① 检查是否为重复事实
            if existing_edges and self._is_duplicate_fact(existing_edges, relation_name, fact):
                # 重复事实，跳过创建新边
                continue
            
            # ② 检测矛盾并处理失效
            if existing_edges:
                self._detect_and_invalidate_contradictions_with_edges(
                    existing_edges, source_uuid, target_uuid, relation_name, fact, timestamp
                )
            
            # ③ 创建新关系
            rel_uuid = f"rel_{uuid.uuid4().hex[:16]}"
            local_rel = LocalRelation(
                project_id=self.graph_id.split("_")[2] if "_" in self.graph_id else "default",
                graph_id=self.graph_id,
                source_uuid=source_uuid,
                target_uuid=target_uuid,
                relation_name=relation_name,
                fact=fact,
                attributes={
                    "valid_at": timestamp,
                    "episodes": [episode_id],
                    **(rel.get("attributes") or {}),
                },
                created_at=timestamp,
                uuid=rel_uuid,
            )
            local_relations.append(local_rel)
        
        # 批量 upsert
        if local_relations:
            self._graph_store.upsert_relations(local_relations)
    
    def _detect_and_invalidate_contradictions(
        self,
        source_uuid: str,
        target_uuid: str,
        new_relation_name: str,
        new_fact: str,
        timestamp: str
    ):
        """
        检测并处理矛盾的边
        
        使用 RuleBasedEdgeInvalidator 进行快速矛盾检测
        """
        try:
            # 获取已有边
            existing_edges = self._graph_store.get_edges_between_entities(
                self.graph_id, source_uuid, target_uuid, include_invalid=False
            )
            
            if not existing_edges:
                return
            
            # 获取源和目标实体名称
            source_entity = self._graph_store.get_entity_by_uuid(source_uuid)
            target_entity = self._graph_store.get_entity_by_uuid(target_uuid)
            
            source_name = source_entity.get("name", "") if source_entity else ""
            target_name = target_entity.get("name", "") if target_entity else ""
            
            # 构建新边信息
            new_edge = {
                "source_name": source_name,
                "target_name": target_name,
                "relation_name": new_relation_name,
                "fact": new_fact,
            }
            
            # 为已有边添加名称信息
            for edge in existing_edges:
                edge["source_name"] = source_name
                edge["target_name"] = target_name
                edge["relation_name"] = edge.get("name", "")
            
            # 使用规则检测器检测矛盾
            contradicted_uuids = self._edge_invalidator.detect_contradictions(
                new_edge, existing_edges
            )
            
            # 标记矛盾边为失效
            for edge_uuid in contradicted_uuids:
                self._graph_store.invalidate_edge(edge_uuid, timestamp)
                logger.debug(f"已标记边失效: {edge_uuid}")
                
        except Exception as e:
            logger.warning(f"矛盾检测失败: {e}")
    
    def _detect_and_invalidate_contradictions_with_edges(
        self,
        existing_edges: List[Dict],
        source_uuid: str,
        target_uuid: str,
        new_relation_name: str,
        new_fact: str,
        timestamp: str
    ):
        """
        使用已有边列表检测并处理矛盾（避免重复查询）
        
        Args:
            existing_edges: 已获取的边列表
            source_uuid: 源实体UUID
            target_uuid: 目标实体UUID
            new_relation_name: 新关系名称
            new_fact: 新事实描述
            timestamp: 时间戳
        """
        if not existing_edges:
            return
        
        try:
            # 获取源和目标实体名称
            source_entity = self._graph_store.get_entity_by_uuid(source_uuid)
            target_entity = self._graph_store.get_entity_by_uuid(target_uuid)
            
            source_name = source_entity.get("name", "") if source_entity else ""
            target_name = target_entity.get("name", "") if target_entity else ""
            
            # 构建新边信息
            new_edge = {
                "source_name": source_name,
                "target_name": target_name,
                "relation_name": new_relation_name,
                "fact": new_fact,
            }
            
            # 为已有边添加名称信息（创建副本避免修改原数据）
            edges_with_names = []
            for edge in existing_edges:
                edge_copy = dict(edge)
                edge_copy["source_name"] = source_name
                edge_copy["target_name"] = target_name
                edge_copy["relation_name"] = edge_copy.get("name", "")
                edges_with_names.append(edge_copy)
            
            # 使用规则检测器检测矛盾
            contradicted_uuids = self._edge_invalidator.detect_contradictions(
                new_edge, edges_with_names
            )
            
            # 标记矛盾边为失效
            for edge_uuid in contradicted_uuids:
                self._graph_store.invalidate_edge(edge_uuid, timestamp)
                logger.info(f"已标记边失效: {edge_uuid} (矛盾关系: {new_relation_name})")
                
        except Exception as e:
            logger.warning(f"矛盾检测失败: {e}")
    
    def _is_duplicate_fact(
        self,
        existing_edges: List[Dict],
        new_relation: str,
        new_fact: str
    ) -> bool:
        """
        检查是否为重复事实
        
        通过比较关系类型和事实描述的相似度来判断是否重复。
        
        Args:
            existing_edges: 已有边列表
            new_relation: 新关系类型
            new_fact: 新事实描述
            
        Returns:
            是否为重复事实
        """
        from .local_entity_resolver import calculate_similarity, normalize_string
        
        DUPLICATE_THRESHOLD = 0.75  # 相似度阈值
        
        new_relation_normalized = normalize_string(new_relation)
        new_fact_normalized = normalize_string(new_fact)
        
        for edge in existing_edges:
            existing_relation = edge.get("name", "")
            existing_relation_normalized = normalize_string(existing_relation)
            
            # 关系类型必须相同或非常相似
            relation_similarity = calculate_similarity(
                new_relation_normalized, 
                existing_relation_normalized
            )
            if relation_similarity < 0.8:
                continue
            
            # 检查事实相似度
            existing_fact = edge.get("fact", "")
            existing_fact_normalized = normalize_string(existing_fact)
            
            # 如果都无事实描述，视为重复
            if not new_fact_normalized and not existing_fact_normalized:
                logger.debug(f"跳过重复事实: {new_relation} (无描述)")
                return True
            
            # 计算事实相似度
            fact_similarity = calculate_similarity(
                new_fact_normalized,
                existing_fact_normalized
            )
            
            if fact_similarity >= DUPLICATE_THRESHOLD:
                logger.debug(
                    f"跳过重复事实: {new_relation} "
                    f"(相似度={fact_similarity:.2f})"
                )
                return True
        
        return False
    
    def _flush_remaining(self):
        """处理队列和缓冲区中剩余的活动"""
        # 首先处理队列中剩余的活动
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
        
        # 处理各平台缓冲区中剩余的活动
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"处理{display_name}平台剩余的 {len(buffer)} 条活动")
                    self._process_batch_activities(buffer, platform)
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
            "processed": self._total_processed,
            "entities_extracted": self._total_entities,
            "relations_extracted": self._total_relations,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class LocalGraphMemoryManager:
    """
    管理多个模拟的本地图谱记忆更新器
    
    每个模拟可以有自己的更新器实例
    """
    
    _updaters: Dict[str, LocalGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> LocalGraphMemoryUpdater:
        """
        为模拟创建图谱记忆更新器
        
        Args:
            simulation_id: 模拟ID
            graph_id: 图谱ID
            
        Returns:
            LocalGraphMemoryUpdater实例
        """
        with cls._lock:
            # 如果已存在，先停止旧的
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            
            updater = LocalGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            
            logger.info(f"创建本地图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[LocalGraphMemoryUpdater]:
        """获取模拟的更新器"""
        return cls._updaters.get(simulation_id)
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """停止并移除模拟的更新器"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止本地图谱记忆更新器: simulation_id={simulation_id}")
    
    _stop_all_done = False
    
    @classmethod
    def stop_all(cls):
        """停止所有更新器"""
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        
        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"停止更新器失败: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("已停止所有本地图谱记忆更新器")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有更新器的统计信息"""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
