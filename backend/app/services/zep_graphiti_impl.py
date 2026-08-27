"""
Graphiti 本地客户端实现

使用 graphiti-core + Neo4j 实现本地知识图谱服务。
替代 Zep Cloud，实现 ZepClientAdapter 接口。

MVP 范围：
- 图谱创建/删除（使用 group_id 隔离）
- Episode 添加（单条/批量）
- 节点/边检索
- 语义搜索

Ontology 在 MVP 阶段先 no-op。
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from functools import lru_cache

from .zep_adapter import (
    ZepClientAdapter,
    GraphNode,
    GraphEdge,
    SearchResult,
    EpisodeStatus,
)

logger = logging.getLogger('mirofish.graphiti_client')


# ============================================================================
# 单后台线程 + 专用事件循环（方案 A）
# ============================================================================
# 所有 Graphiti/Neo4j 异步操作都在这个专用线程的事件循环中执行
# Flask 线程通过 run_coroutine_threadsafe 提交任务并等待结果
# ============================================================================

_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_thread: Optional[threading.Thread] = None
_init_lock = threading.Lock()


def _start_async_loop():
    """在后台线程中启动事件循环"""
    global _async_loop
    _async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_async_loop)
    logger.info("Graphiti 专用事件循环已启动")
    _async_loop.run_forever()


def _ensure_async_loop():
    """确保后台事件循环已启动"""
    global _async_thread
    if _async_thread is None or not _async_thread.is_alive():
        with _init_lock:
            if _async_thread is None or not _async_thread.is_alive():
                _async_thread = threading.Thread(
                    target=_start_async_loop,
                    daemon=True,
                    name="graphiti-async-loop"
                )
                _async_thread.start()
                # 等待循环启动
                while _async_loop is None:
                    import time
                    time.sleep(0.01)


def _operation_timeout_seconds() -> int:
    timeout = int(os.environ.get('GRAPHITI_OPERATION_TIMEOUT_SECONDS', '3600'))
    if timeout <= 0:
        raise ValueError("GRAPHITI_OPERATION_TIMEOUT_SECONDS must be greater than 0")
    return timeout


def _run_async(coro):
    """
    在同步上下文中运行异步协程

    使用专用后台线程的事件循环，通过 run_coroutine_threadsafe 提交任务。
    这样 Neo4j driver 始终绑定到同一个循环，避免跨循环问题。
    """
    _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _async_loop)
    return future.result(timeout=_operation_timeout_seconds())


class DashScopeEmbedderWrapper:
    """
    DashScope 兼容的 Embedder 包装器

    DashScope API 有批次大小限制（max 10），graphiti-core 的 OpenAIEmbedder
    会将所有输入一次性发送。此包装器对请求进行分块处理。

    注意：此类动态继承 EmbedderClient 以满足 Pydantic 类型检查。
    """

    def __init__(self, embedder: Any, max_batch_size: int = 10):
        self._embedder = embedder
        self.max_batch_size = max_batch_size
        # 复制原 embedder 的属性以保持兼容性
        if hasattr(embedder, 'config'):
            self.config = embedder.config

    async def create(self, input_data) -> list[float]:
        """单条 embedding 请求（直接透传）"""
        return await self._embedder.create(input_data)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """批量 embedding 请求（分块处理）"""
        if len(input_data_list) <= self.max_batch_size:
            return await self._embedder.create_batch(input_data_list)

        # 分块处理
        results = []
        for i in range(0, len(input_data_list), self.max_batch_size):
            chunk = input_data_list[i : i + self.max_batch_size]
            chunk_results = await self._embedder.create_batch(chunk)
            results.extend(chunk_results)
        return results


def _create_dashscope_embedder_wrapper(base_embedder: Any, max_batch_size: int = 10) -> Any:
    """
    创建 DashScope 兼容的 Embedder 包装器

    动态继承 EmbedderClient 以满足 graphiti-core 的 Pydantic 类型检查。
    """
    try:
        from graphiti_core.embedder.client import EmbedderClient

        class _DashScopeEmbedderClient(EmbedderClient):
            """动态生成的 EmbedderClient 子类"""

            def __init__(self, embedder: Any, batch_size: int):
                self._embedder = embedder
                self.max_batch_size = batch_size
                if hasattr(embedder, 'config'):
                    self.config = embedder.config

            async def create(self, input_data) -> list[float]:
                return await self._embedder.create(input_data)

            async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
                if len(input_data_list) <= self.max_batch_size:
                    return await self._embedder.create_batch(input_data_list)

                results = []
                for i in range(0, len(input_data_list), self.max_batch_size):
                    chunk = input_data_list[i : i + self.max_batch_size]
                    chunk_results = await self._embedder.create_batch(chunk)
                    results.extend(chunk_results)
                return results

        return _DashScopeEmbedderClient(base_embedder, max_batch_size)

    except ImportError:
        # fallback: 返回普通包装器
        return DashScopeEmbedderWrapper(base_embedder, max_batch_size)


class GraphitiClient(ZepClientAdapter):
    """
    Graphiti 本地客户端实现

    使用 graphiti-core 库连接 Neo4j 图数据库。
    通过 group_id 参数实现多图谱隔离（对应 MiroFish 的 graph_id）。
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        llm_client: Optional[Any] = None,
        embedder: Optional[Any] = None,
    ):
        """
        初始化 Graphiti 客户端

        Args:
            neo4j_uri: Neo4j Bolt 连接 URI (如 bolt://localhost:7687)
            neo4j_user: Neo4j 用户名
            neo4j_password: Neo4j 密码
            llm_client: 可选的 LLM 客户端（用于实体抽取）
            embedder: 可选的 Embedder（用于语义搜索）
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._llm_client = llm_client
        self._embedder = embedder

        # 延迟初始化 Graphiti 实例
        self._graphiti = None
        self._driver = None
        self._initialized = False

        # 记录创建的 graph_id（用于 group_id 映射）
        self._graph_metadata: Dict[str, Dict[str, Any]] = {}

        # 存储 ontology 定义（MVP 阶段仅记录，不强制执行）
        self._ontology_cache: Dict[str, Dict[str, Any]] = {}

    def _ensure_initialized(self):
        """确保 Graphiti 已初始化"""
        if self._initialized:
            return

        try:
            from graphiti_core import Graphiti

            # 应用 Neo4j 属性 sanitization patch (Issue #683 workaround)
            from .graphiti_patch import apply_patch
            apply_patch()

            llm_client = self._llm_client
            if llm_client is None:
                llm_client = self._build_default_llm_client()

            embedder = self._embedder
            if embedder is None:
                embedder = self._build_default_embedder()

            # 创建 Graphiti 实例
            self._graphiti = Graphiti(
                self.neo4j_uri,
                self.neo4j_user,
                self.neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
            )

            # 初始化索引和约束
            _run_async(self._graphiti.build_indices_and_constraints())

            # 获取底层 Neo4j driver 用于直接查询
            self._driver = self._graphiti.driver

            self._initialized = True
            logger.info("Graphiti 客户端初始化完成")

        except ImportError as e:
            raise ImportError(
                "graphiti-core 未安装。请运行: pip install graphiti-core"
            ) from e
        except Exception as e:
            logger.error(f"Graphiti 初始化失败: {e}")
            raise

    def _build_default_llm_client(self) -> Any:
        """
        构建 Graphiti 默认 LLM client（OpenAI-compatible）

        Graphiti 默认会用 `gpt-4.1-mini`，对 DashScope 这类 OpenAI-compatible 服务通常不适用；
        这里优先使用：
        - GRAPHITI_LLM_MODEL（如有）
        - 否则使用 LLM_MODEL_NAME（与 MiroFish 现有配置保持一致）
        """
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

        api_key = os.environ.get('GRAPHITI_LLM_API_KEY') or os.environ.get('OPENAI_API_KEY')
        base_url = os.environ.get('GRAPHITI_LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
        model = os.environ.get('GRAPHITI_LLM_MODEL') or os.environ.get('LLM_MODEL_NAME')
        small_model = os.environ.get('GRAPHITI_LLM_SMALL_MODEL') or None

        temperature = float(os.environ.get('GRAPHITI_LLM_TEMPERATURE', '0') or '0')
        max_tokens = int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '8192') or '8192')

        config = LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            small_model=small_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if base_url and 'api.deepseek.com' in base_url.lower():
            from .deepseek_graphiti_client import DeepSeekGraphitiClient

            return DeepSeekGraphitiClient(config=config)
        return OpenAIGenericClient(config=config)

    def _build_default_embedder(self) -> Any:
        """
        构建 Graphiti 默认 Embedder（OpenAI-compatible /embeddings）

        默认 embedding model 是 `text-embedding-3-small`（OpenAI），DashScope 下需要显式配置：
        - GRAPHITI_EMBEDDING_MODEL=text-embedding-v4

        非标准 OpenAI-compatible embedding API 通常有批次大小限制：
        - DashScope 默认 max 10
        - 本地 TEI 等兼容服务默认 max 32

        可通过 GRAPHITI_EMBEDDING_MAX_BATCH_SIZE 显式覆盖。
        """
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        api_key = os.environ.get('GRAPHITI_EMBEDDING_API_KEY') or os.environ.get('OPENAI_API_KEY')
        base_url = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
        embedding_model = os.environ.get('GRAPHITI_EMBEDDING_MODEL')

        if embedding_model:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
                embedding_model=embedding_model,
            )
        else:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
            )

        base_embedder = OpenAIEmbedder(config=config)

        configured_batch_size = os.environ.get('GRAPHITI_EMBEDDING_MAX_BATCH_SIZE')
        if configured_batch_size:
            max_batch_size = int(configured_batch_size)
            if max_batch_size <= 0:
                raise ValueError("GRAPHITI_EMBEDDING_MAX_BATCH_SIZE must be greater than 0")
        elif base_url and any(
            indicator in base_url.lower() for indicator in ('dashscope', 'aliyun')
        ):
            max_batch_size = 10
        elif base_url and 'api.openai.com' not in base_url.lower():
            max_batch_size = 32
        else:
            max_batch_size = None

        if max_batch_size is not None:
            logger.info(
                "检测到受限的 OpenAI-compatible Embedding API，"
                f"启用分块处理: max_batch_size={max_batch_size}"
            )
            return _create_dashscope_embedder_wrapper(
                base_embedder,
                max_batch_size=max_batch_size,
            )

        return base_embedder

    # ==================== Graph 操作 ====================

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        """
        创建图谱（在 Graphiti 中通过 group_id 隔离）

        Graphiti 没有显式的图谱创建 API，数据通过 group_id 自动隔离。
        这里仅记录元数据，实际数据在 add_episode 时创建。
        """
        self._graph_metadata[graph_id] = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"图谱元数据已记录: graph_id={graph_id}, name={name}")

    def delete_graph(self, graph_id: str) -> None:
        """
        删除图谱（删除 group_id 相关的所有数据）

        使用 Cypher 直接删除 Neo4j 中 group_id 匹配的所有节点和边。
        Graphiti 的所有节点（Entity、Episodic 等）都带 group_id 属性，
        一个通用查询即可覆盖。
        """
        self._ensure_initialized()

        async def _delete():
            # 删除所有带有此 group_id 的节点（级联删除边）
            # Graphiti 的 Entity 和 Episodic 节点都带 group_id，无需分别删除
            result = await self._driver.execute_query(
                """
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                RETURN count(n) as deleted_count
                """,
                group_id=graph_id,
            )
            records = result.records if hasattr(result, 'records') else result[0]
            deleted = records[0]['deleted_count'] if records else 0
            logger.debug(f"删除了 {deleted} 个节点 (group_id={graph_id})")

        _run_async(_delete())

        # 清理本地缓存
        self._graph_metadata.pop(graph_id, None)
        self._ontology_cache.pop(graph_id, None)
        logger.info(f"图谱已删除: graph_id={graph_id}")

    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        设置图谱本体

        MVP 说明：Graphiti 不支持与 Zep Cloud 完全相同的 ontology API。
        这里仅缓存定义，可用于：
        1. 添加 episode 时作为 prompt 提示
        2. 后续对齐时做类型映射

        Full parity 阶段可实现：
        - 动态生成 Pydantic Entity/Edge 模型传递给 add_episode
        - 在 Neo4j 中创建类型约束
        """
        for graph_id in graph_ids:
            self._ontology_cache[graph_id] = {
                "entities": entities or {},
                "edges": edges or {},
            }
            logger.info(
                f"Ontology 已缓存 (MVP no-op): graph_id={graph_id}, "
                f"entity_types={len(entities or {})}, edge_types={len(edges or {})}"
            )

    # ==================== Episode 操作 ====================

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        """添加单条 episode"""
        self._ensure_initialized()

        from graphiti_core.nodes import EpisodeType

        # 映射 episode_type
        source_type = EpisodeType.text
        if episode_type == "message":
            source_type = EpisodeType.message
        elif episode_type == "json":
            source_type = EpisodeType.json

        async def _add():
            result = await self._graphiti.add_episode(
                name=f"episode_{graph_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                episode_body=data,
                source=source_type,
                source_description="mirofish_simulation",
                reference_time=datetime.now(timezone.utc),
                group_id=graph_id,
            )
            return result.episode.uuid if result and result.episode else ""

        return _run_async(_add())

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        """批量添加 episode"""
        self._ensure_initialized()

        from graphiti_core.nodes import EpisodeType
        from graphiti_core.utils.bulk_utils import RawEpisode

        # 构建 RawEpisode 列表
        raw_episodes = []
        for i, ep in enumerate(episodes):
            ep_type = ep.get("type", "text")
            source_type = EpisodeType.text
            if ep_type == "message":
                source_type = EpisodeType.message
            elif ep_type == "json":
                source_type = EpisodeType.json

            raw_episodes.append(
                RawEpisode(
                    name=f"episode_{graph_id}_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    content=ep.get("data", ""),
                    source=source_type,
                    source_description="mirofish_simulation",
                    reference_time=datetime.now(timezone.utc),
                )
            )

        async def _add_bulk():
            result = await self._graphiti.add_episode_bulk(
                bulk_episodes=raw_episodes,
                group_id=graph_id,
            )
            # 返回所有 episode UUID
            return [ep.uuid for ep in result.episodes] if result and result.episodes else []

        return _run_async(_add_bulk())

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        """
        获取 episode 处理状态

        Graphiti 同步处理 episode，添加完成即为已处理。
        """
        return EpisodeStatus(uuid=episode_uuid, processed=True)

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        """
        等待 episode 处理完成

        Graphiti 同步处理，直接返回 True。
        """
        return True

    # ==================== Node 操作 ====================

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        """获取图谱所有节点"""
        self._ensure_initialized()

        async def _get_nodes():
            # 尝试多种 label 模式，提高 schema 兼容性
            # Graphiti 标准使用 :Entity，但也可能有其他 label
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})
                    RETURN
                        n.uuid AS uuid,
                        n.name AS name,
                        labels(n) AS labels,
                        n.summary AS summary,
                        properties(n) AS props,
                        n.created_at AS created_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            # 所有 label 都没找到，记录警告并返回空
            logger.warning(
                f"get_all_nodes: 未找到 group_id={graph_id} 的节点。"
                f"可能的原因：1) 图谱为空 2) Graphiti schema 不匹配（尝试过 Entity, EntityNode）"
            )
            return []

        records = _run_async(_get_nodes())
        nodes = []
        for record in records:
            props = record.get("props", {})
            # 过滤掉已单独提取的属性
            attributes = {
                k: v for k, v in props.items()
                if k not in ["uuid", "name", "summary", "created_at", "group_id"]
            }
            created_at = record.get("created_at")
            if hasattr(created_at, 'to_native'):
                created_at = created_at.to_native().isoformat()
            elif created_at:
                created_at = str(created_at)

            nodes.append(GraphNode(
                uuid=record.get("uuid", ""),
                name=record.get("name", ""),
                labels=record.get("labels", ["Entity"]),
                summary=record.get("summary", ""),
                attributes=attributes,
                created_at=created_at,
            ))
        return nodes

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        """获取单个节点"""
        self._ensure_initialized()

        async def _get_node():
            # 按 uuid 查找节点，不限定 label（更灵活）
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})
                RETURN
                    n.uuid AS uuid,
                    n.name AS name,
                    labels(n) AS labels,
                    n.summary AS summary,
                    properties(n) AS props,
                    n.created_at AS created_at
                LIMIT 1
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_node())
        if not records:
            logger.debug(f"get_node: 未找到 uuid={node_uuid} 的节点")
            return None

        record = records[0]
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "name", "summary", "created_at", "group_id"]
        }
        created_at = record.get("created_at")
        if hasattr(created_at, 'to_native'):
            created_at = created_at.to_native().isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            labels=record.get("labels", ["Entity"]),
            summary=record.get("summary", ""),
            attributes=attributes,
            created_at=created_at,
        )

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        """获取节点的所有相关边（双向）"""
        self._ensure_initialized()

        async def _get_edges():
            # 不限定节点 label，按 uuid 匹配，获取双向边
            # 优先用 r.name（实际关系名），fallback 到 type(r)（关系类型）
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})-[r]-(m)
                RETURN DISTINCT
                    r.uuid AS uuid,
                    COALESCE(r.name, type(r)) AS name,
                    r.fact AS fact,
                    startNode(r).uuid AS source_uuid,
                    endNode(r).uuid AS target_uuid,
                    properties(r) AS props,
                    r.created_at AS created_at,
                    r.valid_at AS valid_at,
                    r.invalid_at AS invalid_at,
                    r.expired_at AS expired_at
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_edges())
        if not records:
            logger.debug(f"get_node_edges: 节点 uuid={node_uuid} 没有关联的边")
        return [self._record_to_edge(record) for record in records]

    # ==================== Edge 操作 ====================

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        """获取图谱所有边（通过节点的 group_id 过滤）"""
        self._ensure_initialized()

        async def _get_edges():
            # 通过节点的 group_id 过滤边，使用 DISTINCT 避免重复
            # 注意：边本身可能没有 group_id，所以通过连接的节点过滤
            # 优先用 r.name（实际关系名），fallback 到 type(r)（关系类型）
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})-[r]-(m:{label})
                    WHERE n.group_id = m.group_id
                    RETURN DISTINCT
                        r.uuid AS uuid,
                        COALESCE(r.name, type(r)) AS name,
                        r.fact AS fact,
                        startNode(r).uuid AS source_uuid,
                        endNode(r).uuid AS target_uuid,
                        properties(r) AS props,
                        r.created_at AS created_at,
                        r.valid_at AS valid_at,
                        r.invalid_at AS invalid_at,
                        r.expired_at AS expired_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            logger.warning(
                f"get_all_edges: 未找到 group_id={graph_id} 的边。"
                f"可能的原因：1) 图谱无边 2) Graphiti schema 不匹配"
            )
            return []

        records = _run_async(_get_edges())
        return [self._record_to_edge(record) for record in records]

    # ==================== Search 操作 ====================

    def _is_openai_compatible_only(self) -> bool:
        """
        检测是否使用非标准 OpenAI API（如 DashScope、Azure 等）

        这些 API 可能不支持 cross_encoder 需要的 logprobs 功能，
        需要 fallback 到 RRF 重排序。

        可通过 GRAPHITI_FORCE_CROSS_ENCODER=true 强制使用 cross_encoder
        （适用于确认支持 logprobs 的兼容服务）。
        """
        import os

        # 显式覆盖：强制使用 cross_encoder
        if os.environ.get('GRAPHITI_FORCE_CROSS_ENCODER', '').lower() in ('true', '1', 'yes'):
            return False

        base_url = os.environ.get('OPENAI_BASE_URL', '')
        # 标准 OpenAI API
        if not base_url or 'api.openai.com' in base_url:
            return False
        # 非标准 API（DashScope、Azure、本地部署等）
        non_standard_indicators = [
            'dashscope', 'aliyun', 'azure', 'localhost',
            'ollama', 'vllm', 'lmstudio', 'openrouter'
        ]
        return any(indicator in base_url.lower() for indicator in non_standard_indicators)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "rrf"  # 默认改为 rrf，更安全
    ) -> SearchResult:
        """
        图谱混合搜索

        使用 Graphiti 公开的 search_() API（带 config）进行搜索。
        如果 search_() 不可用，fallback 到简单的 search() API。

        注意：reranker="cross_encoder" 需要 OpenAI API 支持 logprobs，
        非标准 API（如 DashScope）会自动降级为 rrf。
        """
        self._ensure_initialized()

        # 非标准 OpenAI API 不支持 cross_encoder，强制使用 rrf
        if reranker == "cross_encoder" and self._is_openai_compatible_only():
            logger.info("检测到非标准 OpenAI API，cross_encoder 降级为 rrf")
            reranker = "rrf"

        from graphiti_core.search.search_config_recipes import (
            NODE_HYBRID_SEARCH_RRF,
            EDGE_HYBRID_SEARCH_RRF,
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
        )

        async def _do_search():
            nodes = []
            edges = []

            # 检查是否有 search_() 方法（公开的高级搜索 API）
            has_search_method = hasattr(self._graphiti, 'search_')

            if not has_search_method:
                # Fallback: 使用简单的 search() API
                logger.info("使用 graphiti.search() 简单 API（search_() 不可用）")
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    # 简单 search 主要返回边
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                    return nodes, edges
                except Exception as e:
                    logger.warning(f"graphiti.search() 失败: {e}，返回空结果")
                    return [], []

            # 使用 search_() 高级 API
            try:
                if scope == "nodes":
                    config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'nodes'):
                        nodes = result.nodes or []

                elif scope == "edges":
                    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'edges'):
                        edges = result.edges or []

                else:  # both
                    if reranker == "cross_encoder":
                        config = COMBINED_HYBRID_SEARCH_CROSS_ENCODER.model_copy(deep=True)
                        config.limit = limit
                        result = await self._graphiti.search_(
                            query=query,
                            config=config,
                            group_ids=[graph_id],
                        )
                        if result:
                            nodes = result.nodes or [] if hasattr(result, 'nodes') else []
                            edges = result.edges or [] if hasattr(result, 'edges') else []
                    else:
                        # 分别搜索 nodes 和 edges
                        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        node_config.limit = limit // 2
                        edge_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        edge_config.limit = limit // 2

                        node_result = await self._graphiti.search_(
                            query=query, config=node_config, group_ids=[graph_id]
                        )
                        edge_result = await self._graphiti.search_(
                            query=query, config=edge_config, group_ids=[graph_id]
                        )

                        if node_result and hasattr(node_result, 'nodes'):
                            nodes = node_result.nodes or []
                        if edge_result and hasattr(edge_result, 'edges'):
                            edges = edge_result.edges or []

            except Exception as e:
                logger.warning(f"graphiti.search_() 失败: {e}，尝试 fallback")
                # Fallback 到简单搜索
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                except Exception as fallback_e:
                    logger.error(f"search fallback 也失败: {fallback_e}")

            return nodes, edges

        raw_nodes, raw_edges = _run_async(_do_search())

        if not raw_nodes and not raw_edges:
            logger.debug(f"search: query='{query}' group_id={graph_id} 无结果")

        # 转换为适配器数据结构
        nodes = [self._graphiti_node_to_graph_node(n) for n in raw_nodes]
        edges = [self._graphiti_edge_to_graph_edge(e) for e in raw_edges]

        return SearchResult(nodes=nodes, edges=edges)

    # ==================== 转换辅助方法 ====================

    def _record_to_edge(self, record: Dict[str, Any]) -> GraphEdge:
        """将 Neo4j 查询结果转换为 GraphEdge"""
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "fact", "created_at", "valid_at", "invalid_at", "expired_at", "group_id"]
        }

        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'to_native'):
                return t.to_native().isoformat()
            return str(t)

        return GraphEdge(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            fact=record.get("fact", ""),
            source_node_uuid=record.get("source_uuid", ""),
            target_node_uuid=record.get("target_uuid", ""),
            attributes=attributes,
            created_at=_format_time(record.get("created_at")),
            valid_at=_format_time(record.get("valid_at")),
            invalid_at=_format_time(record.get("invalid_at")),
            expired_at=_format_time(record.get("expired_at")),
            episodes=[],  # Graphiti 边可能没有 episodes 字段
            fact_type=record.get("name", ""),
        )

    def _graphiti_node_to_graph_node(self, node: Any) -> GraphNode:
        """将 Graphiti 节点对象转换为 GraphNode"""
        created_at = getattr(node, 'created_at', None)
        if hasattr(created_at, 'isoformat'):
            created_at = created_at.isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=getattr(node, 'uuid', ''),
            name=getattr(node, 'name', ''),
            labels=getattr(node, 'labels', ['Entity']),
            summary=getattr(node, 'summary', ''),
            attributes=getattr(node, 'attributes', {}),
            created_at=created_at,
        )

    def _graphiti_edge_to_graph_edge(self, edge: Any) -> GraphEdge:
        """将 Graphiti 边对象转换为 GraphEdge"""
        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'isoformat'):
                return t.isoformat()
            return str(t)

        return GraphEdge(
            uuid=getattr(edge, 'uuid', ''),
            name=getattr(edge, 'name', '') or getattr(edge, 'fact_type', ''),
            fact=getattr(edge, 'fact', ''),
            source_node_uuid=getattr(edge, 'source_node_uuid', ''),
            target_node_uuid=getattr(edge, 'target_node_uuid', ''),
            attributes=getattr(edge, 'attributes', {}),
            created_at=_format_time(getattr(edge, 'created_at', None)),
            valid_at=_format_time(getattr(edge, 'valid_at', None)),
            invalid_at=_format_time(getattr(edge, 'invalid_at', None)),
            expired_at=_format_time(getattr(edge, 'expired_at', None)),
            episodes=getattr(edge, 'episodes', []),
            fact_type=getattr(edge, 'fact_type', '') or getattr(edge, 'name', ''),
        )

    def close(self):
        """关闭连接"""
        if self._graphiti:
            _run_async(self._graphiti.close())
            self._initialized = False
            logger.info("Graphiti 连接已关闭")

    def __del__(self):
        """析构时关闭连接"""
        try:
            self.close()
        except Exception:
            pass
