"""SQLite-backed local graph store used when Zep is disabled.

This is a pragmatic replacement layer that keeps the app bootable and lets the
main graph/profile/report flows use local persistence instead of Zep Cloud.
It intentionally stores raw chunks, extracted nodes, extracted edges, and
lightweight episode metadata in SQLite.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Config

logger = logging.getLogger(__name__)


@dataclass
class ExtractedChunk:
    episode_uuid: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stable_uuid(*parts: str) -> str:
    payload = "::".join(part.strip().lower() for part in parts if part is not None)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


class LocalGraphStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or getattr(Config, "LOCAL_GRAPH_DB_PATH", "") or self._default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    @staticmethod
    def _default_db_path() -> str:
        return str(Path(__file__).resolve().parents[2] / "uploads" / "local_graphs.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS graphs (
                        graph_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        ontology_json TEXT NOT NULL DEFAULT '{}',
                        source_text TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        mode TEXT NOT NULL DEFAULT 'sqlite'
                    );

                    CREATE TABLE IF NOT EXISTS graph_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        graph_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS graph_episodes (
                        uuid TEXT PRIMARY KEY,
                        graph_id TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'chunk',
                        data TEXT NOT NULL,
                        processed INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS graph_nodes (
                        uuid TEXT PRIMARY KEY,
                        graph_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        labels_json TEXT NOT NULL DEFAULT '[]',
                        summary TEXT NOT NULL DEFAULT '',
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS graph_edges (
                        uuid TEXT PRIMARY KEY,
                        graph_id TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        fact TEXT NOT NULL DEFAULT '',
                        fact_type TEXT NOT NULL DEFAULT '',
                        source_node_uuid TEXT NOT NULL,
                        target_node_uuid TEXT NOT NULL,
                        source_node_name TEXT NOT NULL DEFAULT '',
                        target_node_name TEXT NOT NULL DEFAULT '',
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        episodes_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        valid_at TEXT,
                        invalid_at TEXT,
                        expired_at TEXT,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_graph_chunks_graph_id ON graph_chunks(graph_id);
                    CREATE INDEX IF NOT EXISTS idx_graph_episodes_graph_id ON graph_episodes(graph_id);
                    CREATE INDEX IF NOT EXISTS idx_graph_nodes_graph_id ON graph_nodes(graph_id);
                    CREATE INDEX IF NOT EXISTS idx_graph_edges_graph_id ON graph_edges(graph_id);
                    CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_uuid);
                    CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_uuid);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO graphs (graph_id, name, description, ontology_json, source_text, created_at, updated_at, mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'sqlite')
                    ON CONFLICT(graph_id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        updated_at=excluded.updated_at
                    """,
                    (graph_id, name, description, "{}", "", now, now),
                )
                conn.commit()
                return graph_id
            finally:
                conn.close()

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE graphs SET ontology_json = ?, updated_at = ? WHERE graph_id = ?",
                    (_json_dumps(ontology or {}), now, graph_id),
                )
                conn.commit()
            finally:
                conn.close()

    def append_source_text(self, graph_id: str, source_text: str) -> None:
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE graphs SET source_text = COALESCE(source_text, '') || ?, updated_at = ? WHERE graph_id = ?",
                    (source_text or "", now, graph_id),
                )
                conn.commit()
            finally:
                conn.close()

    def store_episode(self, graph_id: str, chunk_index: int, content: str, kind: str = "chunk") -> str:
        episode_uuid = str(uuid.uuid4())
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO graph_episodes (uuid, graph_id, kind, data, processed, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (episode_uuid, graph_id, kind, content, now),
                )
                conn.execute(
                    """
                    INSERT INTO graph_chunks (graph_id, chunk_index, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (graph_id, chunk_index, content, now),
                )
                conn.commit()
                return episode_uuid
            finally:
                conn.close()

    def upsert_node(
        self,
        graph_id: str,
        name: str,
        labels: Sequence[str],
        summary: str = "",
        attributes: Optional[Dict[str, Any]] = None,
        node_uuid: Optional[str] = None,
    ) -> str:
        node_uuid = node_uuid or _stable_uuid(graph_id, "node", name, ",".join(labels or []))
        now = _utcnow()
        payload = (
            node_uuid,
            graph_id,
            name.strip(),
            _json_dumps(list(labels or [])),
            summary or "",
            _json_dumps(attributes or {}),
            now,
            now,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO graph_nodes (uuid, graph_id, name, labels_json, summary, attributes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        name=excluded.name,
                        labels_json=excluded.labels_json,
                        summary=excluded.summary,
                        attributes_json=excluded.attributes_json,
                        updated_at=excluded.updated_at
                    """,
                    payload,
                )
                conn.commit()
                return node_uuid
            finally:
                conn.close()

    def upsert_edge(
        self,
        graph_id: str,
        name: str,
        fact: str,
        source_node_uuid: str,
        target_node_uuid: str,
        source_node_name: str,
        target_node_name: str,
        attributes: Optional[Dict[str, Any]] = None,
        episodes: Optional[Sequence[str]] = None,
        fact_type: Optional[str] = None,
        edge_uuid: Optional[str] = None,
        created_at: Optional[str] = None,
        valid_at: Optional[str] = None,
        invalid_at: Optional[str] = None,
        expired_at: Optional[str] = None,
    ) -> str:
        edge_uuid = edge_uuid or _stable_uuid(
            graph_id,
            "edge",
            name,
            source_node_uuid,
            target_node_uuid,
            fact[:160],
        )
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT episodes_json, created_at FROM graph_edges WHERE uuid = ?",
                    (edge_uuid,),
                ).fetchone()
                merged_episodes = list(episodes or [])
                if existing:
                    prev_episodes = _json_loads(existing["episodes_json"], [])
                    if isinstance(prev_episodes, list):
                        merged_episodes = list(dict.fromkeys([*prev_episodes, *merged_episodes]))
                    if not created_at:
                        created_at = existing["created_at"]
                conn.execute(
                    """
                    INSERT INTO graph_edges (
                        uuid, graph_id, name, fact, fact_type, source_node_uuid, target_node_uuid,
                        source_node_name, target_node_name, attributes_json, episodes_json,
                        created_at, valid_at, invalid_at, expired_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        name=excluded.name,
                        fact=excluded.fact,
                        fact_type=excluded.fact_type,
                        source_node_uuid=excluded.source_node_uuid,
                        target_node_uuid=excluded.target_node_uuid,
                        source_node_name=excluded.source_node_name,
                        target_node_name=excluded.target_node_name,
                        attributes_json=excluded.attributes_json,
                        episodes_json=excluded.episodes_json,
                        valid_at=excluded.valid_at,
                        invalid_at=excluded.invalid_at,
                        expired_at=excluded.expired_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        edge_uuid,
                        graph_id,
                        name or "",
                        fact or "",
                        fact_type or name or "",
                        source_node_uuid,
                        target_node_uuid,
                        source_node_name or "",
                        target_node_name or "",
                        _json_dumps(attributes or {}),
                        _json_dumps(merged_episodes),
                        created_at or now,
                        valid_at,
                        invalid_at,
                        expired_at,
                        now,
                    ),
                )
                conn.commit()
                return edge_uuid
            finally:
                conn.close()

    def _load_graph(self, conn: sqlite3.Connection, graph_id: str) -> Optional[sqlite3.Row]:
        return conn.execute("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()

    def get_graph(self, graph_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                graph = self._load_graph(conn, graph_id)
                if not graph:
                    return None
                nodes = self.list_nodes(graph_id, conn=conn)
                edges = self.list_edges(graph_id, conn=conn)
                chunks = conn.execute(
                    "SELECT chunk_index, content, created_at FROM graph_chunks WHERE graph_id = ? ORDER BY chunk_index, id",
                    (graph_id,),
                ).fetchall()
                return {
                    "graph_id": graph_id,
                    "name": graph["name"],
                    "description": graph["description"],
                    "ontology": _json_loads(graph["ontology_json"], {}),
                    "source_text": graph["source_text"],
                    "created_at": graph["created_at"],
                    "updated_at": graph["updated_at"],
                    "nodes": nodes,
                    "edges": edges,
                    "chunks": [dict(row) for row in chunks],
                }
            finally:
                conn.close()

    def list_graphs(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT graph_id, name, description, ontology_json, created_at, updated_at FROM graphs ORDER BY updated_at DESC"
                ).fetchall()
                return [
                    {
                        "graph_id": row["graph_id"],
                        "name": row["name"],
                        "description": row["description"],
                        "ontology": _json_loads(row["ontology_json"], {}),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                    for row in rows
                ]
            finally:
                conn.close()

    def list_nodes(self, graph_id: str, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
        own_conn = None
        if conn is None:
            own_conn = self._connect()
            conn = own_conn
        try:
            rows = conn.execute(
                "SELECT * FROM graph_nodes WHERE graph_id = ? ORDER BY updated_at DESC, created_at DESC, name",
                (graph_id,),
            ).fetchall()
            return [self._row_to_node(row) for row in rows]
        finally:
            if own_conn is not None:
                own_conn.close()

    def list_edges(self, graph_id: str, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
        own_conn = None
        if conn is None:
            own_conn = self._connect()
            conn = own_conn
        try:
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE graph_id = ? ORDER BY updated_at DESC, created_at DESC",
                (graph_id,),
            ).fetchall()
            return [self._row_to_edge(row) for row in rows]
        finally:
            if own_conn is not None:
                own_conn.close()

    def get_node(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM graph_nodes WHERE graph_id = ? AND uuid = ?",
                    (graph_id, node_uuid),
                ).fetchone()
                return self._row_to_node(row) if row else None
            finally:
                conn.close()

    def get_edges_for_node(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM graph_edges
                    WHERE graph_id = ? AND (source_node_uuid = ? OR target_node_uuid = ?)
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (graph_id, node_uuid, node_uuid),
                ).fetchall()
                return [self._row_to_edge(row) for row in rows]
            finally:
                conn.close()

    def get_edges_for_node_any(self, node_uuid: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM graph_edges
                    WHERE source_node_uuid = ? OR target_node_uuid = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (node_uuid, node_uuid),
                ).fetchall()
                return [self._row_to_edge(row) for row in rows]
            finally:
                conn.close()

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.list_nodes(graph_id)
        edges = self.list_edges(graph_id)
        entity_types: Dict[str, int] = {}
        relation_types: Dict[str, int] = {}
        for node in nodes:
            for label in node.get("labels", []):
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        for edge in edges:
            relation_types[edge.get("name", "")] = relation_types.get(edge.get("name", ""), 0) + 1
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def delete_graph(self, graph_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_id,))
                conn.commit()
            finally:
                conn.close()

    def append_activity(self, graph_id: str, payload: Dict[str, Any]) -> str:
        episode_uuid = str(uuid.uuid4())
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO graph_episodes (uuid, graph_id, kind, data, processed, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (episode_uuid, graph_id, "activity", _json_dumps(payload), now),
                )
                conn.commit()
                return episode_uuid
            finally:
                conn.close()

    def search(self, graph_id: str, query: str, scope: str = "edges", limit: int = 10) -> Dict[str, Any]:
        query_lower = (query or "").lower()
        keywords = [w.strip() for w in re.split(r"[\s,，]+", query_lower) if len(w.strip()) > 1]

        def score_text(text: str) -> int:
            if not text:
                return 0
            text_lower = text.lower()
            score = 0
            if query_lower and query_lower in text_lower:
                score += 100
            for kw in keywords:
                if kw in text_lower:
                    score += 10
            return score

        nodes = self.list_nodes(graph_id) if scope in ["nodes", "both"] else []
        edges = self.list_edges(graph_id) if scope in ["edges", "both"] else []
        facts: List[str] = []
        scored_nodes: List[Tuple[int, Dict[str, Any]]] = []
        scored_edges: List[Tuple[int, Dict[str, Any]]] = []

        for node in nodes:
            text = " ".join([
                node.get("name", ""),
                node.get("summary", ""),
                _json_dumps(node.get("attributes", {})),
            ])
            score = score_text(text)
            if score > 0:
                scored_nodes.append((score, node))

        for edge in edges:
            text = " ".join([
                edge.get("name", ""),
                edge.get("fact", ""),
                edge.get("source_node_name", ""),
                edge.get("target_node_name", ""),
                _json_dumps(edge.get("attributes", {})),
            ])
            score = score_text(text)
            if score > 0:
                scored_edges.append((score, edge))

        scored_nodes.sort(key=lambda item: item[0], reverse=True)
        scored_edges.sort(key=lambda item: item[0], reverse=True)

        node_results = [node for _, node in scored_nodes[:limit]]
        edge_results = [edge for _, edge in scored_edges[:limit]]

        for node in node_results:
            if node.get("summary"):
                facts.append(f"[{node['name']}]: {node['summary']}")
        for edge in edge_results:
            if edge.get("fact"):
                facts.append(edge["fact"])

        return {
            "facts": facts[:limit],
            "nodes": node_results,
            "edges": edge_results,
            "total_count": len(facts),
        }

    def extract_and_store_chunks(
        self,
        graph_id: str,
        chunks: Sequence[str],
        ontology: Optional[Dict[str, Any]] = None,
        llm_client: Optional[Any] = None,
        progress_callback: Optional[Any] = None,
        batch_size: int = 1,
    ) -> List[str]:
        episode_uuids: List[str] = []
        ontology = ontology or {}

        existing_nodes = {node["name"].strip().lower(): node for node in self.list_nodes(graph_id)}
        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(idx + 1, total)
            episode_uuid = self.store_episode(graph_id, idx, chunk, kind="text")
            episode_uuids.append(episode_uuid)
            extracted = self._extract_chunk(chunk, ontology, llm_client)
            node_map = self._store_extracted_chunk(graph_id, extracted, episode_uuid, existing_nodes)
            existing_nodes.update(node_map)
        return episode_uuids

    def _extract_chunk(self, chunk: str, ontology: Dict[str, Any], llm_client: Optional[Any]) -> ExtractedChunk:
        if llm_client is not None:
            try:
                payload = self._extract_with_llm(chunk, ontology, llm_client)
                return ExtractedChunk(
                    episode_uuid="",
                    nodes=payload.get("nodes", []),
                    edges=payload.get("edges", []),
                )
            except Exception as exc:
                logger.warning("Local graph extraction via LLM failed, falling back to heuristics: %s", exc)
        nodes = self._heuristic_extract_nodes(chunk, ontology)
        edges = self._heuristic_extract_edges(chunk, nodes, ontology)
        return ExtractedChunk(episode_uuid="", nodes=nodes, edges=edges)

    def _extract_with_llm(self, chunk: str, ontology: Dict[str, Any], llm_client: Any) -> Dict[str, Any]:
        entity_types = [e.get("name", "Entity") for e in ontology.get("entity_types", []) if isinstance(e, dict)]
        edge_types = [e.get("name", "RELATED_TO") for e in ontology.get("edge_types", []) if isinstance(e, dict)]
        system = (
            "You extract graph nodes and edges from source text for a social-simulation knowledge graph. "
            "Return only JSON with keys nodes and edges. "
            "Each node must have name, labels, summary, attributes. "
            "Each edge must have name, fact, source_node_name, target_node_name, attributes."
        )
        if entity_types:
            system += " Allowed entity types: " + ", ".join(entity_types)
        if edge_types:
            system += " Allowed relation types: " + ", ".join(edge_types)
        user = (
            f"Ontology:\n{_json_dumps(ontology)}\n\n"
            f"Text chunk:\n{chunk}\n\n"
            "Rules:\n"
            "- Prefer real-world entities that can act on social media\n"
            "- If the text mentions organizations or people, use those as nodes\n"
            "- Use labels like ['Entity', '<Type>']\n"
            "- Facts should be concise natural language statements\n"
            "- If you cannot infer a relationship, return an empty edges list\n"
        )
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=2500,
        )
        if not isinstance(result, dict):
            raise ValueError("Invalid extraction payload")
        return result

    def _heuristic_extract_nodes(self, chunk: str, ontology: Dict[str, Any]) -> List[Dict[str, Any]]:
        entity_types = [e.get("name", "Entity") for e in ontology.get("entity_types", []) if isinstance(e, dict)]
        fallback_type = entity_types[0] if entity_types else "Entity"
        candidates = self._guess_entities(chunk)
        nodes: List[Dict[str, Any]] = []
        for candidate in candidates[:8]:
            nodes.append(
                {
                    "name": candidate,
                    "labels": ["Entity", fallback_type],
                    "summary": candidate,
                    "attributes": {},
                }
            )
        return nodes

    def _heuristic_extract_edges(
        self,
        chunk: str,
        nodes: Sequence[Dict[str, Any]],
        ontology: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        relation_types = [e.get("name", "RELATED_TO") for e in ontology.get("edge_types", []) if isinstance(e, dict)]
        relation_name = relation_types[0] if relation_types else "RELATED_TO"
        node_names = [str(node.get("name", "")).strip() for node in nodes if str(node.get("name", "")).strip()]
        if len(node_names) < 2:
            return []

        # Split on sentence boundaries first; fall back to whole chunk if needed.
        sentences = [part.strip() for part in re.split(r"[\.!?。！？\n]+", chunk) if part.strip()]
        if not sentences:
            sentences = [chunk.strip()]

        edges: List[Dict[str, Any]] = []
        seen_pairs = set()

        for sentence in sentences:
            matched: List[str] = []
            lower_sentence = sentence.lower()
            for name in node_names:
                needle = name.lower()
                if needle and needle in lower_sentence and name not in matched:
                    matched.append(name)
            if len(matched) < 2:
                continue
            for source_name, target_name in zip(matched, matched[1:]):
                pair_key = (source_name.lower(), target_name.lower(), sentence.lower())
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                edges.append(
                    {
                        "name": relation_name,
                        "fact": sentence.strip() or f"{source_name} {relation_name} {target_name}",
                        "source_node_name": source_name,
                        "target_node_name": target_name,
                        "attributes": {},
                        "fact_type": relation_name,
                    }
                )

        if not edges:
            for source_name, target_name in zip(node_names, node_names[1:]):
                pair_key = (source_name.lower(), target_name.lower(), "fallback")
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                edges.append(
                    {
                        "name": relation_name,
                        "fact": f"{source_name} {relation_name} {target_name}",
                        "source_node_name": source_name,
                        "target_node_name": target_name,
                        "attributes": {},
                        "fact_type": relation_name,
                    }
                )

        return edges

    def _guess_entities(self, text: str) -> List[str]:
        # Simple fallback: quoted names, title-case words, and long nouns.
        candidates: List[str] = []
        for match in re.findall(r"[A-Z][A-Za-z0-9&_-]*(?:\s+[A-Z][A-Za-z0-9&_-]*){0,3}", text):
            match = match.strip().strip("'\"“”‘’,，。.!?；;:：")
            if len(match) > 2:
                candidates.append(match)
        for match in re.findall(r"[\u4e00-\u9fff]{2,10}", text):
            match = match.strip()
            if len(match) > 2:
                candidates.append(match)
        seen = set()
        result = []
        for item in candidates:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _store_extracted_chunk(
        self,
        graph_id: str,
        extracted: ExtractedChunk,
        episode_uuid: str,
        existing_nodes: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        ontology = self.get_graph(graph_id) or {}
        new_nodes: Dict[str, Dict[str, Any]] = {}
        node_uuid_by_name: Dict[str, str] = {}

        # First, upsert nodes.
        for node in extracted.nodes:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name", "")).strip()
            if not name:
                continue
            labels = node.get("labels") or ["Entity", "Entity"]
            if isinstance(labels, str):
                labels = [labels]
            summary = str(node.get("summary", ""))
            attributes = node.get("attributes") or {}
            entity_type = next((label for label in labels if label not in ["Entity", "Node"]), "Entity")
            node_uuid = node.get("uuid") or _stable_uuid(graph_id, "node", entity_type, name)
            self.upsert_node(graph_id, name, labels, summary=summary, attributes=attributes, node_uuid=node_uuid)
            node_uuid_by_name[name.lower()] = node_uuid
            node_uuid_by_name.setdefault(name.strip().lower(), node_uuid)
            new_nodes[name.lower()] = {
                "uuid": node_uuid,
                "name": name,
                "labels": list(labels),
                "summary": summary,
                "attributes": attributes,
            }

        # Resolve existing names too.
        for name, node in existing_nodes.items():
            node_uuid_by_name.setdefault(name, node.get("uuid", ""))

        # Now upsert edges.
        for edge in extracted.edges:
            if not isinstance(edge, dict):
                continue
            name = str(edge.get("name", "RELATED_TO")).strip() or "RELATED_TO"
            fact = str(edge.get("fact", "")).strip()
            source_name = str(edge.get("source_node_name", "")).strip()
            target_name = str(edge.get("target_node_name", "")).strip()
            if not source_name or not target_name:
                continue
            source_uuid = node_uuid_by_name.get(source_name.lower()) or existing_nodes.get(source_name.lower(), {}).get("uuid")
            target_uuid = node_uuid_by_name.get(target_name.lower()) or existing_nodes.get(target_name.lower(), {}).get("uuid")
            if not source_uuid:
                source_uuid = self.upsert_node(graph_id, source_name, ["Entity", "Entity"], summary=source_name)
                node_uuid_by_name[source_name.lower()] = source_uuid
            if not target_uuid:
                target_uuid = self.upsert_node(graph_id, target_name, ["Entity", "Entity"], summary=target_name)
                node_uuid_by_name[target_name.lower()] = target_uuid
            self.upsert_edge(
                graph_id=graph_id,
                name=name,
                fact=fact or f"{source_name} {name} {target_name}",
                source_node_uuid=source_uuid,
                target_node_uuid=target_uuid,
                source_node_name=source_name,
                target_node_name=target_name,
                attributes=edge.get("attributes") or {},
                episodes=[episode_uuid],
                fact_type=str(edge.get("fact_type", name) or name),
                edge_uuid=edge.get("uuid"),
            )

        return new_nodes

    def _row_to_node(self, row: Optional[sqlite3.Row]) -> Dict[str, Any]:
        if row is None:
            return {}
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "labels": _json_loads(row["labels_json"], []),
            "summary": row["summary"],
            "attributes": _json_loads(row["attributes_json"], {}),
            "created_at": row["created_at"],
        }

    def _row_to_edge(self, row: Optional[sqlite3.Row]) -> Dict[str, Any]:
        if row is None:
            return {}
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "fact": row["fact"],
            "fact_type": row["fact_type"],
            "source_node_uuid": row["source_node_uuid"],
            "target_node_uuid": row["target_node_uuid"],
            "source_node_name": row["source_node_name"],
            "target_node_name": row["target_node_name"],
            "attributes": _json_loads(row["attributes_json"], {}),
            "created_at": row["created_at"],
            "valid_at": row["valid_at"],
            "invalid_at": row["invalid_at"],
            "expired_at": row["expired_at"],
            "episodes": _json_loads(row["episodes_json"], []),
        }
