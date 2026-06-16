"""
Adapters Package
图谱适配器实现，支持切换底层图数据库（Zep / Neo4j）
"""

from .graph_adapter import GraphAdapter, GraphNode, GraphEdge, GraphInfo, SearchResult
from .llm_extractor import LLMExtractionPipeline, LLMEntityEnricher, ExtractedEntity, ExtractedEdge
from .neo4j_graph_builder import Neo4jGraphBuilder, Neo4jAsyncGraphBuilder
from .neo4j_entity_reader import Neo4jEntityReader, EntityNode, FilteredEntities
from .neo4j_search_service import Neo4jSearchService, NodeInfo, EdgeInfo
from .neo4j_graph_memory_updater import (
    Neo4jGraphMemoryUpdater,
    Neo4jGraphMemoryManager,
    AgentActivity
)

__all__ = [
    # 核心接口
    'GraphAdapter',
    'GraphNode',
    'GraphEdge',
    'GraphInfo',
    'SearchResult',

    # LLM 提取
    'LLMExtractionPipeline',
    'LLMEntityEnricher',
    'ExtractedEntity',
    'ExtractedEdge',

    # Neo4j 图谱构建
    'Neo4jGraphBuilder',
    'Neo4jAsyncGraphBuilder',

    # Neo4j 实体读取
    'Neo4jEntityReader',
    'EntityNode',
    'FilteredEntities',

    # Neo4j 搜索服务
    'Neo4jSearchService',
    'NodeInfo',
    'EdgeInfo',

    # Neo4j 记忆更新
    'Neo4jGraphMemoryUpdater',
    'Neo4jGraphMemoryManager',
    'AgentActivity',
]
