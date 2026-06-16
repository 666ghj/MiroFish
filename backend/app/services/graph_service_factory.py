"""
图谱服务工厂
根据配置动态选择 Zep 或 Neo4j 后端实现
"""

from typing import Optional, TYPE_CHECKING

from ..config import Config
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from .adapters.graph_adapter import GraphAdapter
    from .adapters.neo4j_graph_builder import Neo4jGraphBuilder

logger = get_logger('mirofish.graph_factory')


class GraphServiceFactory:
    """
    图谱服务工厂

    根据 Config.GRAPH_BACKEND 配置返回对应的服务实现：
    - 'zep': 使用 Zep Cloud 服务
    - 'neo4j': 使用 Neo4j 本地服务
    """

    _instance: Optional['GraphServiceFactory'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self._backend = Config.GRAPH_BACKEND or 'zep'
            logger.info(f"GraphServiceFactory 初始化: backend={self._backend}")

    @property
    def backend(self) -> str:
        return self._backend

    def get_graph_builder(self):
        """
        获取图谱构建服务

        Returns:
            GraphBuilderService 或 Neo4jGraphBuilder
        """
        if self._backend == 'neo4j':
            from .adapters.neo4j_graph_builder import Neo4jGraphBuilder
            logger.info("使用 Neo4jGraphBuilder")
            return Neo4jGraphBuilder()
        else:
            from .graph_builder import GraphBuilderService
            logger.info("使用 GraphBuilderService (Zep)")
            return GraphBuilderService(api_key=Config.ZEP_API_KEY)

    def get_entity_reader(self):
        """
        获取实体读取服务

        Returns:
            ZepEntityReader 或 Neo4jEntityReader
        """
        if self._backend == 'neo4j':
            from .adapters.neo4j_entity_reader import Neo4jEntityReader
            logger.info("使用 Neo4jEntityReader")
            return Neo4jEntityReader()
        else:
            from .zep_entity_reader import ZepEntityReader
            logger.info("使用 ZepEntityReader")
            return ZepEntityReader(api_key=Config.ZEP_API_KEY)

    def get_search_service(self, llm_client=None):
        """
        获取检索工具服务

        Args:
            llm_client: LLM 客户端（用于需要 LLM 的功能）

        Returns:
            ZepToolsService 或 Neo4jSearchService
        """
        if self._backend == 'neo4j':
            from .adapters.neo4j_search_service import Neo4jSearchService
            logger.info("使用 Neo4jSearchService")
            return Neo4jSearchService(llm_client=llm_client)
        else:
            from .zep_tools import ZepToolsService
            logger.info("使用 ZepToolsService")
            return ZepToolsService(api_key=Config.ZEP_API_KEY, llm_client=llm_client)

    def get_memory_updater(self, simulation_id: str, graph_id: str):
        """
        获取图谱记忆更新器

        Args:
            simulation_id: 模拟ID
            graph_id: 图谱ID

        Returns:
            ZepGraphMemoryUpdater 或 Neo4jGraphMemoryUpdater
        """
        if self._backend == 'neo4j':
            from .adapters.neo4j_graph_memory_updater import Neo4jGraphMemoryManager
            logger.info("使用 Neo4jGraphMemoryManager")
            return Neo4jGraphMemoryManager.create_updater(simulation_id, graph_id)
        else:
            from .zep_graph_memory_updater import ZepGraphMemoryManager
            logger.info("使用 ZepGraphMemoryManager")
            return ZepGraphMemoryManager.create_updater(simulation_id, graph_id)

    def get_existing_memory_updater(self, simulation_id: str):
        """获取已存在的图谱记忆更新器。"""
        if self._backend == 'neo4j':
            from .adapters.neo4j_graph_memory_updater import Neo4jGraphMemoryManager
            return Neo4jGraphMemoryManager.get_updater(simulation_id)
        else:
            from .zep_graph_memory_updater import ZepGraphMemoryManager
            return ZepGraphMemoryManager.get_updater(simulation_id)

    def stop_memory_updater(self, simulation_id: str) -> None:
        """停止指定模拟的图谱记忆更新器。"""
        if self._backend == 'neo4j':
            from .adapters.neo4j_graph_memory_updater import Neo4jGraphMemoryManager
            Neo4jGraphMemoryManager.stop_updater(simulation_id)
        else:
            from .zep_graph_memory_updater import ZepGraphMemoryManager
            ZepGraphMemoryManager.stop_updater(simulation_id)

    def stop_all_memory_updaters(self) -> None:
        """停止所有图谱记忆更新器。"""
        if self._backend == 'neo4j':
            from .adapters.neo4j_graph_memory_updater import Neo4jGraphMemoryManager
            Neo4jGraphMemoryManager.stop_all()
        else:
            from .zep_graph_memory_updater import ZepGraphMemoryManager
            ZepGraphMemoryManager.stop_all()

    def check_backend_health(self) -> dict:
        """
        检查后端健康状态

        Returns:
            健康状态字典
        """
        if self._backend == 'neo4j':
            from ..utils.neo4j import neo4j_health_check
            healthy = neo4j_health_check()
            return {
                "backend": "neo4j",
                "healthy": healthy,
                "uri": Config.NEO4J_URI
            }
        else:
            # Zep 没有内置健康检查，简单返回 True
            return {
                "backend": "zep",
                "healthy": True,
                "api_key_configured": bool(Config.ZEP_API_KEY)
            }


# 全局工厂实例
_graph_factory: Optional[GraphServiceFactory] = None


def get_graph_factory() -> GraphServiceFactory:
    """获取图谱服务工厂实例"""
    global _graph_factory
    if _graph_factory is None:
        _graph_factory = GraphServiceFactory()
    return _graph_factory
