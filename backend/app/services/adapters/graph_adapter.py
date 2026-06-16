"""
图谱适配器接口定义
抽象 Zep Cloud 和 Neo4j 的共同操作，支持底层图数据库切换
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class GraphNode:
    """图谱节点"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None


@dataclass
class GraphEdge:
    """图谱边"""
    uuid: str
    name: str  # 关系类型名称
    fact: str  # 事实描述
    source_node_uuid: str
    target_node_uuid: str
    attributes: Dict[str, Any]
    # 时间信息
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count,
        }

    def to_text(self) -> str:
        text_parts = [
            f"搜索查询: {self.query}",
            f"找到 {self.total_count} 条相关信息",
        ]

        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")

        if self.nodes:
            text_parts.append("\n### 相关节点:")
            for i, node in enumerate(self.nodes, 1):
                name = node.get("name", "未知实体")
                labels = ", ".join(node.get("labels") or [])
                summary = node.get("summary") or ""
                text_parts.append(f"- **{name}** ({labels})")
                if summary:
                    text_parts.append(f"   摘要: {summary}")

        if self.edges:
            text_parts.append("\n### 相关边:")
            for edge in self.edges:
                name = edge.get("name", "关系")
                fact = edge.get("fact") or ""
                source = edge.get("source_name") or edge.get("source_node_name") or edge.get("source_node_uuid", "")[:8]
                target = edge.get("target_name") or edge.get("target_node_name") or edge.get("target_node_uuid", "")[:8]
                text_parts.append(f"- {source} --[{name}]--> {target}")
                if fact:
                    text_parts.append(f"   事实: {fact}")

        return "\n".join(text_parts)


class GraphAdapter(ABC):
    """
    图谱适配器接口

    定义所有图谱操作的抽象接口，Zep 和 Neo4j 都必须实现这些方法。
    这样上层服务可以透明地切换底层图数据库。
    """

    @abstractmethod
    def create_graph(self, name: str) -> str:
        """
        创建新图谱

        Args:
            name: 图谱名称

        Returns:
            graph_id: 新创建的图谱ID
        """
        pass

    @abstractmethod
    def set_ontology(
        self,
        graph_id: str,
        entity_types: List[Dict[str, Any]],
        edge_types: List[Dict[str, Any]]
    ) -> None:
        """
        设置图谱本体（Schema）

        Args:
            graph_id: 图谱ID
            entity_types: 实体类型定义列表
            edge_types: 关系类型定义列表
        """
        pass

    @abstractmethod
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """
        批量添加文本到图谱

        Args:
            graph_id: 图谱ID
            chunks: 文本块列表
            batch_size: 每批发送的块数量
            progress_callback: 进度回调函数

        Returns:
            episode_uuids: 所有文本块的UUID列表
        """
        pass

    @abstractmethod
    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        """
        获取图谱的所有节点

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        pass

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        """
        获取图谱的所有边

        Args:
            graph_id: 图谱ID

        Returns:
            边列表
        """
        pass

    @abstractmethod
    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        """
        获取单个节点

        Args:
            node_uuid: 节点UUID

        Returns:
            节点对象或None
        """
        pass

    @abstractmethod
    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        """
        获取指定节点的所有相关边

        Args:
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        pass

    @abstractmethod
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱语义搜索

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围 ("edges" / "nodes" / "both")

        Returns:
            SearchResult: 搜索结果
        """
        pass

    @abstractmethod
    def add_activities(
        self,
        graph_id: str,
        activities: List[str]
    ) -> None:
        """
        添加活动记录到图谱

        Args:
            graph_id: 图谱ID
            activities: 活动描述文本列表
        """
        pass

    @abstractmethod
    def delete_graph(self, graph_id: str) -> None:
        """
        删除图谱

        Args:
            graph_id: 图谱ID
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            True 如果连接正常
        """
        pass
