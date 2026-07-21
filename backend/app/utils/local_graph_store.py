"""
本地JSON文件图谱存储
替代Zep Cloud，将图谱数据（节点、边、情节）存储在本地JSON文件中

存储目录结构:
    {storage_dir}/
      {graph_id}/
        metadata.json    - 图谱元数据和本体定义
        nodes.json       - 节点列表
        edges.json       - 边列表
        episodes.jsonl   - 情节文本日志（追加写入）
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger('mirofish.local_graph_store')

# 每个图谱一把锁，保证并发写入安全
_global_lock = threading.Lock()
_graph_locks: Dict[str, threading.Lock] = {}


def _lock_for(graph_id: str) -> threading.Lock:
    with _global_lock:
        if graph_id not in _graph_locks:
            _graph_locks[graph_id] = threading.Lock()
        return _graph_locks[graph_id]


class LocalGraphStore:
    """本地JSON文件图谱存储"""

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    # ── 图谱生命周期 ──────────────────────────────────────────────────────────

    def create_graph(self, graph_id: str, name: str, description: str = "") -> None:
        graph_dir = self._graph_dir(graph_id)
        os.makedirs(graph_dir, exist_ok=True)
        self._write_json(self._meta_path(graph_id), {
            "graph_id": graph_id,
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "ontology": None,
        })
        if not os.path.exists(self._nodes_path(graph_id)):
            self._write_json(self._nodes_path(graph_id), [])
        if not os.path.exists(self._edges_path(graph_id)):
            self._write_json(self._edges_path(graph_id), [])
        logger.info(f"本地图谱已创建: {graph_id}")

    def delete_graph(self, graph_id: str) -> None:
        graph_dir = self._graph_dir(graph_id)
        if os.path.exists(graph_dir):
            shutil.rmtree(graph_dir)
            logger.info(f"本地图谱已删除: {graph_id}")

    def graph_exists(self, graph_id: str) -> bool:
        return os.path.exists(self._meta_path(graph_id))

    # ── 本体 ──────────────────────────────────────────────────────────────────

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        meta = self._read_json(self._meta_path(graph_id)) or {}
        meta["ontology"] = ontology
        self._write_json(self._meta_path(graph_id), meta)

    def get_ontology(self, graph_id: str) -> Optional[Dict[str, Any]]:
        meta = self._read_json(self._meta_path(graph_id)) or {}
        return meta.get("ontology")

    def get_metadata(self, graph_id: str) -> Optional[Dict[str, Any]]:
        return self._read_json(self._meta_path(graph_id))

    # ── 情节（Episode）────────────────────────────────────────────────────────

    def add_episode(self, graph_id: str, text: str) -> str:
        """追加一条情节文本，返回情节uuid（本地存储立即处理完成）"""
        episode_id = uuid.uuid4().hex
        record = {
            "uuid": episode_id,
            "text": text,
            "created_at": datetime.now().isoformat(),
            "processed": True,
        }
        ep_path = self._episodes_path(graph_id)
        with _lock_for(graph_id):
            with open(ep_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        return episode_id

    def add_episodes_batch(self, graph_id: str, texts: List[str]) -> List[str]:
        return [self.add_episode(graph_id, t) for t in texts]

    def episode_is_processed(self, graph_id: str, episode_uuid: str) -> bool:
        """本地存储中的情节总是立即处理完成"""
        return True

    # ── 节点 ──────────────────────────────────────────────────────────────────

    def get_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        return self._read_json(self._nodes_path(graph_id)) or []

    def get_node(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        for node in self.get_nodes(graph_id):
            if node.get("uuid") == node_uuid:
                return node
        return None

    def upsert_node(
        self,
        graph_id: str,
        name: str,
        labels: Optional[List[str]] = None,
        summary: str = "",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """按名称查找节点，存在则更新，不存在则创建。返回uuid。"""
        labels = labels or ["Entity"]
        attributes = attributes or {}

        with _lock_for(graph_id):
            nodes = self._read_json(self._nodes_path(graph_id)) or []
            # 按名称（不区分大小写）查找
            for node in nodes:
                if node.get("name", "").lower() == name.lower():
                    # 合并标签
                    existing = set(node.get("labels", []))
                    existing.update(labels)
                    node["labels"] = list(existing)
                    # 若原摘要为空则填充
                    if summary and not node.get("summary"):
                        node["summary"] = summary
                    # 合并属性
                    if attributes:
                        node.setdefault("attributes", {}).update(attributes)
                    self._write_json(self._nodes_path(graph_id), nodes)
                    return node["uuid"]
            # 创建新节点
            node_uuid = uuid.uuid4().hex
            nodes.append({
                "uuid": node_uuid,
                "name": name,
                "labels": labels,
                "summary": summary,
                "attributes": attributes,
                "created_at": datetime.now().isoformat(),
            })
            self._write_json(self._nodes_path(graph_id), nodes)
            return node_uuid

    # ── 边 ───────────────────────────────────────────────────────────────────

    def get_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        return self._read_json(self._edges_path(graph_id)) or []

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        """获取与指定节点相关的所有边（作为源或目标）"""
        return [
            e for e in self.get_edges(graph_id)
            if e.get("source_node_uuid") == node_uuid or e.get("target_node_uuid") == node_uuid
        ]

    def add_edge(self, graph_id: str, edge: Dict[str, Any]) -> str:
        """添加一条边，返回其uuid。"""
        edge_uuid = edge.get("uuid") or uuid.uuid4().hex
        edge = dict(edge)
        edge["uuid"] = edge_uuid
        edge.setdefault("created_at", datetime.now().isoformat())
        edge.setdefault("valid_at", None)
        edge.setdefault("invalid_at", None)
        edge.setdefault("expired_at", None)
        edge.setdefault("attributes", {})

        with _lock_for(graph_id):
            edges = self._read_json(self._edges_path(graph_id)) or []
            edges.append(edge)
            self._write_json(self._edges_path(graph_id), edges)
        return edge_uuid

    def add_fact_edge(
        self,
        graph_id: str,
        source_uuid: str,
        target_uuid: str,
        name: str,
        fact: str,
    ) -> str:
        """便利方法：在两个节点之间添加一条命名事实边。"""
        return self.add_edge(graph_id, {
            "name": name,
            "fact": fact,
            "source_node_uuid": source_uuid,
            "target_node_uuid": target_uuid,
        })

    # ── 搜索 ─────────────────────────────────────────────────────────────────

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> Dict[str, Any]:
        """基于关键词的本地搜索"""
        query_lower = query.lower()
        keywords = [
            w.strip()
            for w in query_lower.replace(',', ' ').replace('，', ' ').split()
            if len(w.strip()) > 1
        ]

        def score(text: str) -> int:
            if not text:
                return 0
            tl = text.lower()
            if query_lower in tl:
                return 100
            return sum(10 for kw in keywords if kw in tl)

        result_edges: List[Dict] = []
        result_nodes: List[Dict] = []
        facts: List[str] = []

        if scope in ("edges", "both"):
            scored = sorted(
                [(score(e.get("fact", "")) + score(e.get("name", "")), e)
                 for e in self.get_edges(graph_id)
                 if score(e.get("fact", "")) + score(e.get("name", "")) > 0],
                key=lambda x: x[0], reverse=True,
            )
            for _, edge in scored[:limit]:
                result_edges.append(edge)
                if edge.get("fact"):
                    facts.append(edge["fact"])

        if scope in ("nodes", "both"):
            scored = sorted(
                [(score(n.get("name", "")) + score(n.get("summary", "")), n)
                 for n in self.get_nodes(graph_id)
                 if score(n.get("name", "")) + score(n.get("summary", "")) > 0],
                key=lambda x: x[0], reverse=True,
            )
            for _, node in scored[:limit]:
                result_nodes.append(node)
                if node.get("summary"):
                    facts.append(f"[{node['name']}]: {node['summary']}")

        return {"facts": facts, "edges": result_edges, "nodes": result_nodes}

    # ── 内部路径辅助 ──────────────────────────────────────────────────────────

    def _graph_dir(self, graph_id: str) -> str:
        return os.path.join(self.storage_dir, graph_id)

    def _meta_path(self, graph_id: str) -> str:
        return os.path.join(self._graph_dir(graph_id), "metadata.json")

    def _nodes_path(self, graph_id: str) -> str:
        return os.path.join(self._graph_dir(graph_id), "nodes.json")

    def _edges_path(self, graph_id: str) -> str:
        return os.path.join(self._graph_dir(graph_id), "edges.json")

    def _episodes_path(self, graph_id: str) -> str:
        return os.path.join(self._graph_dir(graph_id), "episodes.jsonl")

    def _read_json(self, path: str) -> Any:
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_json(self, path: str, data: Any) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
