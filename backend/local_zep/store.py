from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .embeddings import EmbeddingClient, cosine_similarity
from .extraction import GraphExtractor
from .models import GraphEdge, GraphEpisode, GraphNode, GraphRecord, GraphSearchResults
from .reranker import RerankerClient
from .settings import settings

logger = logging.getLogger("mirofish.local_zep")
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_CONFLICTING_EDGE_NAMES = {
    "SUPPORTS": {"OPPOSES"},
    "OPPOSES": {"SUPPORTS"},
    "APPROVES": {"REJECTS", "OPPOSES"},
    "REJECTS": {"APPROVES", "SUPPORTS"},
    "LIKES": {"DISLIKES"},
    "DISLIKES": {"LIKES"},
}


@dataclass
class _SearchCandidate:
    kind: str
    uuid: str
    text: str
    item: GraphNode | GraphEdge | GraphEpisode
    embedding: list[float] = field(default_factory=list)
    semantic_score: float = 0.0
    lexical_score: float = 0.0
    score: float = 0.0
    relevance: float | None = None
    episode_count: int = 0
    distance: int | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_iso(value: str | None) -> str:
    value = (value or "").strip()
    return value or _now_iso()


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_fact(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower().rstrip("."))


def _primary_label(labels: list[str]) -> str:
    for label in labels:
        if label not in {"Entity", "Node"}:
            return label
    return "Entity"


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _camel_case(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _get_value(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default

    keys = [key, _camel_case(key)]
    for candidate in keys:
        if isinstance(source, dict) and candidate in source:
            return source[candidate]
        if hasattr(source, candidate):
            return getattr(source, candidate)

    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _bm25_scores(query: str, documents: list[str]) -> list[float]:
    query_terms = _tokenize(query[:400])
    if not query_terms or not documents:
        return [0.0] * len(documents)

    tokenized_docs = [_tokenize(document) for document in documents]
    doc_count = len(tokenized_docs)
    avg_len = sum(len(tokens) for tokens in tokenized_docs) / max(doc_count, 1)
    if avg_len <= 0:
        avg_len = 1.0

    document_frequency: dict[str, int] = {}
    for tokens in tokenized_docs:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    scores: list[float] = []
    k1 = 1.5
    b = 0.75
    for tokens in tokenized_docs:
        term_counts: dict[str, int] = {}
        for token in tokens:
            term_counts[token] = term_counts.get(token, 0) + 1

        score = 0.0
        doc_len = max(len(tokens), 1)
        for token in query_terms:
            tf = term_counts.get(token, 0)
            if tf <= 0:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            denominator = tf + k1 * (1.0 - b + b * doc_len / avg_len)
            score += idf * (tf * (k1 + 1.0)) / denominator

        if query.lower().strip() and query.lower().strip() in (documents[len(scores)] or "").lower():
            score += 1.5
        scores.append(score)

    return scores


def _rank_positions(candidates: list[_SearchCandidate], attr: str) -> dict[str, int]:
    ranked = sorted(candidates, key=lambda candidate: getattr(candidate, attr), reverse=True)
    return {
        candidate.uuid: rank
        for rank, candidate in enumerate(ranked, start=1)
        if getattr(candidate, attr) > 0
    }


def _matches_labels(labels: list[str], include: list[str], exclude: list[str]) -> bool:
    label_set = set(labels)
    if include and not label_set.intersection(include):
        return False
    if exclude and label_set.intersection(exclude):
        return False
    return True


def _compare_value(value: Any, operator: str, expected: Any = None) -> bool:
    operator = (operator or "=").upper()
    if operator == "IS NULL":
        return value is None
    if operator == "IS NOT NULL":
        return value is not None

    if value is None:
        return False

    left = value
    right = expected
    try:
        left = float(value)
        right = float(expected)
    except (TypeError, ValueError):
        left = str(value)
        right = str(expected)

    if operator == "=":
        return left == right
    if operator == "<>":
        return left != right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    return True


class LocalZepStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.local_zep_db_path
        self._lock = threading.RLock()
        self._embedding_client: EmbeddingClient | None = None
        self._extractor: GraphExtractor | None = None
        self._reranker_client: RerankerClient | None = None

        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS graphs (
                    graph_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    ontology_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    uuid TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    type TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    source_description TEXT,
                    role TEXT,
                    role_type TEXT,
                    thread_id TEXT,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    uuid TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    primary_label TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    attributes_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_identity
                ON nodes(graph_id, normalized_name, primary_label);

                CREATE TABLE IF NOT EXISTS edges (
                    uuid TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    source_node_uuid TEXT NOT NULL,
                    target_node_uuid TEXT NOT NULL,
                    attributes_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    valid_at TEXT,
                    invalid_at TEXT,
                    expired_at TEXT,
                    FOREIGN KEY(graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE,
                    FOREIGN KEY(source_node_uuid) REFERENCES nodes(uuid) ON DELETE CASCADE,
                    FOREIGN KEY(target_node_uuid) REFERENCES nodes(uuid) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_identity
                ON edges(graph_id, source_node_uuid, target_node_uuid, name, fact);

                CREATE TABLE IF NOT EXISTS edge_episodes (
                    edge_uuid TEXT NOT NULL,
                    episode_uuid TEXT NOT NULL,
                    PRIMARY KEY(edge_uuid, episode_uuid),
                    FOREIGN KEY(edge_uuid) REFERENCES edges(uuid) ON DELETE CASCADE,
                    FOREIGN KEY(episode_uuid) REFERENCES episodes(uuid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS node_embeddings (
                    node_uuid TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(node_uuid) REFERENCES nodes(uuid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS edge_embeddings (
                    edge_uuid TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(edge_uuid) REFERENCES edges(uuid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS episode_embeddings (
                    episode_uuid TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(episode_uuid) REFERENCES episodes(uuid) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(conn, "episodes", "metadata_json", "TEXT DEFAULT '{}'")
            self._ensure_column(conn, "episodes", "source_description", "TEXT")
            self._ensure_column(conn, "episodes", "role", "TEXT")
            self._ensure_column(conn, "episodes", "role_type", "TEXT")
            self._ensure_column(conn, "episodes", "thread_id", "TEXT")
            self._ensure_column(conn, "episodes", "task_id", "TEXT")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _get_embedding_client(self) -> EmbeddingClient:
        if self._embedding_client is None:
            self._embedding_client = EmbeddingClient()
        return self._embedding_client

    def _get_extractor(self) -> GraphExtractor:
        if self._extractor is None:
            self._extractor = GraphExtractor()
        return self._extractor

    def _get_reranker_client(self) -> RerankerClient:
        if self._reranker_client is None:
            self._reranker_client = RerankerClient()
        return self._reranker_client

    def create_graph(self, graph_id: str, name: str, description: str = "") -> GraphRecord:
        created_at = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO graphs(graph_id, name, description, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(graph_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description
                """,
                (graph_id, name, description, created_at),
            )
        return GraphRecord(graph_id=graph_id, name=name, description=description, created_at=created_at)

    def delete_graph(self, graph_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_id,))

    def set_ontology(self, graph_id: str, ontology: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE graphs SET ontology_json = ? WHERE graph_id = ?",
                (_json_dumps(ontology or {}), graph_id),
            )

    def get_ontology(self, graph_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ontology_json FROM graphs WHERE graph_id = ?",
                (graph_id,),
            ).fetchone()
        return _json_loads(row["ontology_json"], {}) if row else {}

    def get_graph(self, graph_id: str) -> GraphRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()
        if not row:
            return None
        return GraphRecord(
            graph_id=row["graph_id"],
            name=row["name"],
            description=row["description"] or "",
            created_at=row["created_at"],
        )

    def add(
        self,
        graph_id: str,
        data: str,
        type_: str = "text",
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        source_description: str | None = None,
    ) -> GraphEpisode:
        episode_created_at = _coerce_iso(created_at)
        episode = GraphEpisode(
            uuid_=uuid.uuid4().hex,
            graph_id=graph_id,
            data=data,
            type=type_,
            processed=False,
            created_at=episode_created_at,
            metadata=metadata or {},
            source_description=source_description,
        )

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes(
                    uuid, graph_id, data, type, processed, error, metadata_json,
                    source_description, role, role_type, thread_id, task_id, created_at
                )
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    episode.uuid_,
                    graph_id,
                    data,
                    type_,
                    _json_dumps(metadata or {}),
                    source_description,
                    episode.created_at,
                ),
            )

        try:
            ontology = self.get_ontology(graph_id)
            extracted = self._get_extractor().extract(data, ontology)
            touched_nodes, touched_edges = self._apply_extraction(
                graph_id,
                episode.uuid_,
                extracted,
                ontology,
                episode.created_at or _now_iso(),
            )
            episode.processed = True
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE episodes SET processed = 1, error = NULL WHERE uuid = ?",
                    (episode.uuid_,),
                )
            self._refresh_node_embeddings(graph_id, touched_nodes)
            self._refresh_edge_embeddings(graph_id, touched_edges)
            self._refresh_episode_embeddings(graph_id, {episode.uuid_})
        except Exception as exc:
            logger.exception("Local graph episode processing failed: %s", exc)
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE episodes SET processed = 0, error = ? WHERE uuid = ?",
                    (str(exc), episode.uuid_),
                )
            episode.error = str(exc)
            raise

        return self.get_episode(episode.uuid_) or episode

    def add_batch(self, graph_id: str, episodes: list[Any]) -> list[GraphEpisode]:
        results = []
        for episode in episodes:
            data = getattr(episode, "data", "") if episode is not None else ""
            type_ = getattr(episode, "type", "text") if episode is not None else "text"
            created_at = getattr(episode, "created_at", None) if episode is not None else None
            metadata = getattr(episode, "metadata", None) if episode is not None else None
            source_description = getattr(episode, "source_description", None) if episode is not None else None
            results.append(
                self.add(
                    graph_id=graph_id,
                    data=data,
                    type_=type_,
                    created_at=created_at,
                    metadata=metadata,
                    source_description=source_description,
                )
            )
        return results

    def get_episode(self, uuid_: str) -> GraphEpisode | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE uuid = ?",
                (uuid_,),
            ).fetchone()
        return self._row_to_episode(row) if row else None

    def get_episodes_by_graph_id(self, graph_id: str, lastn: int | None = None):
        query = "SELECT * FROM episodes WHERE graph_id = ? ORDER BY created_at DESC, uuid DESC"
        params: list[Any] = [graph_id]
        if lastn:
            query += " LIMIT ?"
            params.append(lastn)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return type("EpisodeList", (), {"episodes": [self._row_to_episode(row) for row in rows]})()

    def get_nodes_page(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None) -> list[GraphNode]:
        query = "SELECT * FROM nodes WHERE graph_id = ?"
        params: list[Any] = [graph_id]
        if uuid_cursor:
            query += " AND uuid > ?"
            params.append(uuid_cursor)
        query += " ORDER BY uuid LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_node(row) for row in rows]

    def get_edges_page(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None) -> list[GraphEdge]:
        query = "SELECT * FROM edges WHERE graph_id = ?"
        params: list[Any] = [graph_id]
        if uuid_cursor:
            query += " AND uuid > ?"
            params.append(uuid_cursor)
        query += " ORDER BY uuid LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            edge_ids = [row["uuid"] for row in rows]
            episode_map = self._load_edge_episode_map(conn, edge_ids)
        return [self._row_to_edge(row, episode_map.get(row["uuid"], [])) for row in rows]

    def get_node(self, uuid_: str) -> GraphNode | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (uuid_,)).fetchone()
        return self._row_to_node(row) if row else None

    def get_edge(self, uuid_: str) -> GraphEdge | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM edges WHERE uuid = ?", (uuid_,)).fetchone()
            if not row:
                return None
            episode_map = self._load_edge_episode_map(conn, [uuid_])
        return self._row_to_edge(row, episode_map.get(uuid_, []))

    def get_entity_edges(self, node_uuid: str) -> list[GraphEdge]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM edges
                WHERE source_node_uuid = ? OR target_node_uuid = ?
                ORDER BY created_at DESC, uuid
                """,
                (node_uuid, node_uuid),
            ).fetchall()
            edge_ids = [row["uuid"] for row in rows]
            episode_map = self._load_edge_episode_map(conn, edge_ids)
        return [self._row_to_edge(row, episode_map.get(row["uuid"], [])) for row in rows]

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "rrf",
        mmr_lambda: float | None = None,
        center_node_uuid: str | None = None,
        search_filters: Any = None,
        bfs_origin_node_uuids: list[str] | None = None,
    ) -> GraphSearchResults:
        results = GraphSearchResults()
        query = (query or "").strip()[:400]
        if not query:
            return results

        query_embedding: list[float] = []
        try:
            query_embedding = self._get_embedding_client().embed_text(query)
        except Exception as exc:
            logger.warning("Embedding lookup failed, falling back to lexical search: %s", exc)

        with self._connect() as conn:
            candidates = self._build_search_candidates(
                conn=conn,
                graph_id=graph_id,
                query=query,
                query_embedding=query_embedding,
                scope=(scope or "edges").lower(),
                search_filters=search_filters,
            )
            if not candidates:
                return results

            if bfs_origin_node_uuids:
                distances = self._graph_distances(conn, graph_id, bfs_origin_node_uuids)
                self._apply_distances(conn, candidates, distances)

            self._rank_candidates(
                conn=conn,
                graph_id=graph_id,
                query=query,
                query_embedding=query_embedding,
                candidates=candidates,
                reranker=reranker or "rrf",
                mmr_lambda=mmr_lambda,
                center_node_uuid=center_node_uuid,
            )

        ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[: max(limit, 0)]
        results.edges = [
            self._scored_item(candidate)
            for candidate in ranked
            if candidate.kind == "edge"
        ]
        results.nodes = [
            self._scored_item(candidate)
            for candidate in ranked
            if candidate.kind == "node"
        ]
        results.episodes = [
            self._scored_item(candidate)
            for candidate in ranked
            if candidate.kind == "episode"
        ]

        return results

    def _build_search_candidates(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        query: str,
        query_embedding: list[float],
        scope: str,
        search_filters: Any,
    ) -> list[_SearchCandidate]:
        candidates: list[_SearchCandidate] = []

        if scope in {"edges", "both"}:
            rows = conn.execute(
                """
                SELECT
                    e.*,
                    ee.embedding_json,
                    src.name AS source_name,
                    src.labels_json AS source_labels_json,
                    dst.name AS target_name,
                    dst.labels_json AS target_labels_json
                FROM edges e
                JOIN nodes src ON src.uuid = e.source_node_uuid
                JOIN nodes dst ON dst.uuid = e.target_node_uuid
                LEFT JOIN edge_embeddings ee ON ee.edge_uuid = e.uuid
                WHERE e.graph_id = ?
                """,
                (graph_id,),
            ).fetchall()
            edge_ids = [row["uuid"] for row in rows]
            episode_map = self._load_edge_episode_map(conn, edge_ids)
            for row in rows:
                if not self._edge_matches_filters(row, search_filters):
                    continue
                edge = self._row_to_edge(row, episode_map.get(row["uuid"], []))
                if not self._episode_metadata_matches_any(conn, edge.episodes, search_filters):
                    continue
                text = " ".join(filter(None, [row["name"], row["fact"], row["source_name"], row["target_name"]]))
                candidates.append(
                    _SearchCandidate(
                        kind="edge",
                        uuid=row["uuid"],
                        text=text,
                        item=edge,
                        embedding=_json_loads(row["embedding_json"], []),
                        episode_count=len(edge.episodes),
                    )
                )

        if scope in {"nodes", "both"}:
            rows = conn.execute(
                """
                SELECT n.*, ne.embedding_json
                FROM nodes n
                LEFT JOIN node_embeddings ne ON ne.node_uuid = n.uuid
                WHERE n.graph_id = ?
                """,
                (graph_id,),
            ).fetchall()
            episode_counts = self._node_episode_counts(conn, graph_id)
            node_episode_ids = self._node_episode_ids(conn, graph_id)
            for row in rows:
                if not self._node_matches_filters(row, search_filters):
                    continue
                if not self._episode_metadata_matches_any(conn, node_episode_ids.get(row["uuid"], []), search_filters):
                    continue
                labels = _json_loads(row["labels_json"], [])
                attributes = _json_loads(row["attributes_json"], {})
                text = " ".join(
                    filter(
                        None,
                        [
                            row["name"],
                            row["summary"],
                            " ".join(labels),
                            json.dumps(attributes, ensure_ascii=False),
                        ],
                    )
                )
                candidates.append(
                    _SearchCandidate(
                        kind="node",
                        uuid=row["uuid"],
                        text=text,
                        item=self._row_to_node(row),
                        embedding=_json_loads(row["embedding_json"], []),
                        episode_count=episode_counts.get(row["uuid"], 0),
                    )
                )

        if scope == "episodes":
            rows = conn.execute(
                """
                SELECT ep.*, ee.embedding_json
                FROM episodes ep
                LEFT JOIN episode_embeddings ee ON ee.episode_uuid = ep.uuid
                WHERE ep.graph_id = ?
                """,
                (graph_id,),
            ).fetchall()
            for row in rows:
                if not self._episode_metadata_matches(_json_loads(row["metadata_json"], {}), search_filters):
                    continue
                candidates.append(
                    _SearchCandidate(
                        kind="episode",
                        uuid=row["uuid"],
                        text=row["data"] or "",
                        item=self._row_to_episode(row),
                        embedding=_json_loads(row["embedding_json"], []),
                        episode_count=1,
                    )
                )

        lexical_scores = _bm25_scores(query, [candidate.text for candidate in candidates])
        for candidate, lexical_score in zip(candidates, lexical_scores):
            candidate.lexical_score = lexical_score
            if query_embedding and candidate.embedding:
                candidate.semantic_score = cosine_similarity(query_embedding, candidate.embedding)

        return candidates

    def _rank_candidates(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        query: str,
        query_embedding: list[float],
        candidates: list[_SearchCandidate],
        reranker: str,
        mmr_lambda: float | None,
        center_node_uuid: str | None,
    ) -> None:
        reranker = (reranker or "rrf").lower()
        if reranker == "cross_encoder":
            self._rank_rrf(candidates)
            pool = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[: settings.local_zep_rerank_top_k]
            scores = self._get_reranker_client().rerank(query, [candidate.text for candidate in pool])
            if scores is not None:
                for candidate, score in zip(pool, scores):
                    candidate.score = float(score) + self._distance_boost(candidate)
                    candidate.relevance = max(0.0, min(1.0, float(score)))
                pool_ids = {candidate.uuid for candidate in pool}
                for candidate in candidates:
                    if candidate.uuid not in pool_ids:
                        candidate.score *= 0.01
                return

            logger.info("Cross-encoder reranker is not configured; using local RRF fallback")
            return

        if reranker == "mmr":
            self._rank_mmr(candidates, query_embedding, mmr_lambda if mmr_lambda is not None else 0.5)
            return

        if reranker == "episode_mentions":
            self._rank_rrf(candidates)
            for candidate in candidates:
                candidate.score += math.log1p(candidate.episode_count) * 0.1
            return

        if reranker == "node_distance" and center_node_uuid:
            distances = self._graph_distances(conn, graph_id, [center_node_uuid])
            self._apply_distances(conn, candidates, distances)
            self._rank_node_distance(candidates)
            return

        self._rank_rrf(candidates)

    def _rank_rrf(self, candidates: list[_SearchCandidate]) -> None:
        semantic_ranks = _rank_positions(candidates, "semantic_score")
        lexical_ranks = _rank_positions(candidates, "lexical_score")
        for candidate in candidates:
            score = 0.0
            if candidate.uuid in semantic_ranks:
                score += 1.0 / (60.0 + semantic_ranks[candidate.uuid])
            if candidate.uuid in lexical_ranks:
                score += 1.0 / (60.0 + lexical_ranks[candidate.uuid])
            candidate.score = score + self._distance_boost(candidate)

    def _rank_mmr(self, candidates: list[_SearchCandidate], query_embedding: list[float], lambda_value: float) -> None:
        lambda_value = max(0.0, min(1.0, lambda_value))
        remaining = candidates[:]
        selected: list[_SearchCandidate] = []

        while remaining:
            best: _SearchCandidate | None = None
            best_score = -float("inf")
            for candidate in remaining:
                relevance = candidate.semantic_score + (candidate.lexical_score * 0.05)
                diversity_penalty = 0.0
                if query_embedding and candidate.embedding and selected:
                    similarities = [
                        cosine_similarity(candidate.embedding, selected_candidate.embedding)
                        for selected_candidate in selected
                        if selected_candidate.embedding
                    ]
                    diversity_penalty = max(similarities) if similarities else 0.0
                mmr_score = lambda_value * relevance - (1.0 - lambda_value) * diversity_penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = candidate

            if best is None:
                break
            remaining.remove(best)
            selected.append(best)
            best.score = best_score + self._distance_boost(best)

        rank_count = len(selected)
        for rank, candidate in enumerate(selected):
            candidate.score += (rank_count - rank) * 1e-6

    def _rank_node_distance(self, candidates: list[_SearchCandidate]) -> None:
        self._rank_rrf(candidates)
        for candidate in candidates:
            if candidate.distance is None:
                candidate.score *= 0.01
            else:
                candidate.score += 1.0 / (1.0 + candidate.distance)

    def _distance_boost(self, candidate: _SearchCandidate) -> float:
        if candidate.distance is None:
            return 0.0
        return 0.15 / (1.0 + candidate.distance)

    def _scored_item(self, candidate: _SearchCandidate):
        candidate.item.score = candidate.score
        candidate.item.relevance = candidate.relevance
        return candidate.item

    def _node_matches_filters(self, row: sqlite3.Row, search_filters: Any) -> bool:
        if not search_filters:
            return True

        labels = _json_loads(row["labels_json"], [])
        include_labels = [str(value) for value in _as_list(_get_value(search_filters, "node_labels"))]
        exclude_labels = [str(value) for value in _as_list(_get_value(search_filters, "exclude_node_labels"))]
        if not _matches_labels(labels, include_labels, exclude_labels):
            return False

        attributes = _json_loads(row["attributes_json"], {})
        return self._properties_match(attributes, search_filters)

    def _edge_matches_filters(self, row: sqlite3.Row, search_filters: Any) -> bool:
        if not search_filters:
            return True

        include_edge_types = [str(value) for value in _as_list(_get_value(search_filters, "edge_types"))]
        exclude_edge_types = [str(value) for value in _as_list(_get_value(search_filters, "exclude_edge_types"))]
        if include_edge_types and row["name"] not in include_edge_types:
            return False
        if exclude_edge_types and row["name"] in exclude_edge_types:
            return False

        source_labels = _json_loads(row["source_labels_json"], [])
        target_labels = _json_loads(row["target_labels_json"], [])
        labels = sorted({*source_labels, *target_labels})
        include_labels = [str(value) for value in _as_list(_get_value(search_filters, "node_labels"))]
        exclude_labels = [str(value) for value in _as_list(_get_value(search_filters, "exclude_node_labels"))]
        if not _matches_labels(labels, include_labels, exclude_labels):
            return False

        attributes = _json_loads(row["attributes_json"], {})
        if not self._properties_match(attributes, search_filters):
            return False

        for field_name in ("created_at", "valid_at", "invalid_at", "expired_at"):
            if not self._date_filters_match(row[field_name], _get_value(search_filters, field_name)):
                return False

        return True

    def _properties_match(self, attributes: dict[str, Any], search_filters: Any) -> bool:
        for prop_filter in _as_list(_get_value(search_filters, "property_filters")):
            property_name = _get_value(prop_filter, "property_name")
            if not property_name:
                continue
            operator = _get_value(prop_filter, "comparison_operator", "=")
            expected = _get_value(prop_filter, "property_value")
            if not _compare_value(attributes.get(str(property_name)), str(operator), expected):
                return False
        return True

    def _episode_metadata_matches_any(
        self,
        conn: sqlite3.Connection,
        episode_ids: list[str],
        search_filters: Any,
    ) -> bool:
        metadata_filter = _get_value(search_filters, "episode_metadata_filters")
        if not metadata_filter:
            return True
        if not episode_ids:
            return False

        rows = conn.execute(
            f"""
            SELECT metadata_json
            FROM episodes
            WHERE uuid IN ({",".join("?" for _ in episode_ids)})
            """,
            episode_ids,
        ).fetchall()
        return any(
            self._episode_metadata_matches(_json_loads(row["metadata_json"], {}), search_filters)
            for row in rows
        )

    def _episode_metadata_matches(self, metadata: dict[str, Any], search_filters: Any) -> bool:
        metadata_filter = _get_value(search_filters, "episode_metadata_filters")
        if not metadata_filter:
            return True
        return self._metadata_group_matches(metadata, metadata_filter)

    def _metadata_group_matches(self, metadata: dict[str, Any], group: Any) -> bool:
        group_type = str(_get_value(group, "type", "and")).lower()
        checks: list[bool] = []

        for metadata_filter in _as_list(_get_value(group, "filters")):
            property_name = _get_value(metadata_filter, "property_name")
            if not property_name:
                continue
            operator = str(_get_value(metadata_filter, "comparison_operator", "="))
            expected = _get_value(metadata_filter, "property_value")
            checks.append(_compare_value(metadata.get(str(property_name)), operator, expected))

        for nested_group in _as_list(_get_value(group, "groups")):
            checks.append(self._metadata_group_matches(metadata, nested_group))

        if not checks:
            return True
        if group_type == "or":
            return any(checks)
        return all(checks)

    def _date_filters_match(self, value: str | None, filter_groups: Any) -> bool:
        if not filter_groups:
            return True

        groups = _as_list(filter_groups)
        if groups and not isinstance(groups[0], (list, tuple, set)):
            groups = [groups]

        for group in groups:
            predicates = _as_list(group)
            if all(
                _compare_value(
                    value,
                    str(_get_value(predicate, "comparison_operator", "=")),
                    _get_value(predicate, "date"),
                )
                for predicate in predicates
            ):
                return True
        return False

    def _node_episode_counts(self, conn: sqlite3.Connection, graph_id: str) -> dict[str, int]:
        episode_ids_by_node = self._node_episode_ids(conn, graph_id)
        return {node_uuid: len(set(episode_ids)) for node_uuid, episode_ids in episode_ids_by_node.items()}

    def _node_episode_ids(self, conn: sqlite3.Connection, graph_id: str) -> dict[str, list[str]]:
        rows = conn.execute(
            """
            SELECT e.source_node_uuid AS node_uuid, ee.episode_uuid
            FROM edges e
            JOIN edge_episodes ee ON ee.edge_uuid = e.uuid
            WHERE e.graph_id = ?
            UNION ALL
            SELECT e.target_node_uuid AS node_uuid, ee.episode_uuid
            FROM edges e
            JOIN edge_episodes ee ON ee.edge_uuid = e.uuid
            WHERE e.graph_id = ?
            """,
            (graph_id, graph_id),
        ).fetchall()
        episodes_by_node: dict[str, list[str]] = {}
        for row in rows:
            episodes_by_node.setdefault(row["node_uuid"], []).append(row["episode_uuid"])
        return episodes_by_node

    def _graph_distances(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        origin_node_uuids: list[str] | None,
    ) -> dict[str, int]:
        origins = [origin for origin in (origin_node_uuids or []) if origin]
        if not origins:
            return {}

        rows = conn.execute(
            "SELECT uuid, source_node_uuid, target_node_uuid FROM edges WHERE graph_id = ?",
            (graph_id,),
        ).fetchall()
        adjacency: dict[str, set[str]] = {}
        for row in rows:
            adjacency.setdefault(row["source_node_uuid"], set()).add(row["target_node_uuid"])
            adjacency.setdefault(row["target_node_uuid"], set()).add(row["source_node_uuid"])

        placeholders = ",".join("?" for _ in origins)
        seed_rows = conn.execute(
            f"SELECT uuid FROM nodes WHERE graph_id = ? AND uuid IN ({placeholders})",
            [graph_id, *origins],
        ).fetchall()
        seed_nodes = {row["uuid"] for row in seed_rows}

        episode_rows = conn.execute(
            f"""
            SELECT e.source_node_uuid, e.target_node_uuid
            FROM edge_episodes ee
            JOIN edges e ON e.uuid = ee.edge_uuid
            WHERE e.graph_id = ? AND ee.episode_uuid IN ({placeholders})
            """,
            [graph_id, *origins],
        ).fetchall()
        for row in episode_rows:
            seed_nodes.add(row["source_node_uuid"])
            seed_nodes.add(row["target_node_uuid"])

        distances: dict[str, int] = {node_uuid: 0 for node_uuid in seed_nodes}
        queue = list(seed_nodes)
        cursor = 0
        while cursor < len(queue):
            node_uuid = queue[cursor]
            cursor += 1
            for neighbor in adjacency.get(node_uuid, set()):
                if neighbor in distances:
                    continue
                distances[neighbor] = distances[node_uuid] + 1
                queue.append(neighbor)
        return distances

    def _apply_distances(
        self,
        conn: sqlite3.Connection,
        candidates: list[_SearchCandidate],
        distances: dict[str, int],
    ) -> None:
        if not distances:
            return

        for candidate in candidates:
            if candidate.kind == "node":
                candidate.distance = distances.get(candidate.uuid)
                continue

            if candidate.kind == "edge":
                edge = candidate.item
                candidate.distance = min(
                    (
                        distance
                        for distance in [
                            distances.get(edge.source_node_uuid),
                            distances.get(edge.target_node_uuid),
                        ]
                        if distance is not None
                    ),
                    default=None,
                )
                continue

            rows = conn.execute(
                """
                SELECT e.source_node_uuid, e.target_node_uuid
                FROM edge_episodes ee
                JOIN edges e ON e.uuid = ee.edge_uuid
                WHERE ee.episode_uuid = ?
                """,
                (candidate.uuid,),
            ).fetchall()
            episode_distances = [
                distance
                for row in rows
                for distance in (distances.get(row["source_node_uuid"]), distances.get(row["target_node_uuid"]))
                if distance is not None
            ]
            candidate.distance = min(episode_distances) if episode_distances else None

    def _apply_extraction(
        self,
        graph_id: str,
        episode_uuid: str,
        extracted: dict[str, list[dict[str, Any]]],
        ontology: dict[str, Any],
        episode_created_at: str,
    ) -> tuple[set[str], set[str]]:
        touched_nodes: set[str] = set()
        touched_edges: set[str] = set()
        entity_lookup: dict[tuple[str, str], GraphNode] = {}

        with self._lock, self._connect() as conn:
            for entity in extracted.get("entities", []):
                node = self._upsert_node(conn, graph_id, entity)
                entity_lookup[(_normalize_name(node.name), _primary_label(node.labels))] = node
                entity_lookup[(_normalize_name(node.name), "Entity")] = node
                touched_nodes.add(node.uuid_)

            for edge in extracted.get("edges", []):
                source_node = self._resolve_edge_node(conn, graph_id, edge.get("source", ""), ontology, edge.get("name", ""), True, entity_lookup)
                target_node = self._resolve_edge_node(conn, graph_id, edge.get("target", ""), ontology, edge.get("name", ""), False, entity_lookup)
                touched_nodes.update({source_node.uuid_, target_node.uuid_})
                stored_edge = self._upsert_edge(
                    conn,
                    graph_id,
                    episode_uuid,
                    edge,
                    source_node,
                    target_node,
                    episode_created_at,
                )
                touched_edges.add(stored_edge.uuid_)

        return touched_nodes, touched_edges

    def _upsert_node(self, conn: sqlite3.Connection, graph_id: str, entity: dict[str, Any]) -> GraphNode:
        name = (entity.get("name") or "").strip()
        entity_type = (entity.get("type") or "Entity").strip() or "Entity"
        summary = (entity.get("summary") or "").strip()
        attributes = entity.get("attributes") or {}
        labels = ["Entity"] if entity_type == "Entity" else ["Entity", entity_type]
        normalized_name = _normalize_name(name)
        label = _primary_label(labels)
        row = conn.execute(
            """
            SELECT * FROM nodes
            WHERE graph_id = ? AND normalized_name = ? AND primary_label = ?
            """,
            (graph_id, normalized_name, label),
        ).fetchone()
        timestamp = _now_iso()

        if row:
            existing_labels = _json_loads(row["labels_json"], [])
            merged_labels = sorted({*existing_labels, *labels})
            existing_attributes = _json_loads(row["attributes_json"], {})
            merged_attributes = {**existing_attributes, **attributes}
            merged_summary = self._merge_summary(row["summary"], summary, merged_attributes)
            conn.execute(
                """
                UPDATE nodes
                SET labels_json = ?, summary = ?, attributes_json = ?, updated_at = ?
                WHERE uuid = ?
                """,
                (_json_dumps(merged_labels), merged_summary, _json_dumps(merged_attributes), timestamp, row["uuid"]),
            )
            updated_row = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (row["uuid"],)).fetchone()
            return self._row_to_node(updated_row)

        node_uuid = uuid.uuid4().hex
        summary = summary or self._fallback_summary(name, attributes)
        conn.execute(
            """
            INSERT INTO nodes(
                uuid, graph_id, name, normalized_name, primary_label, labels_json,
                summary, attributes_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_uuid,
                graph_id,
                name,
                normalized_name,
                label,
                _json_dumps(labels),
                summary,
                _json_dumps(attributes),
                timestamp,
                timestamp,
            ),
        )
        return GraphNode(
            uuid_=node_uuid,
            graph_id=graph_id,
            name=name,
            labels=labels,
            summary=summary,
            attributes=attributes,
            created_at=timestamp,
        )

    def _resolve_edge_node(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        node_name: str,
        ontology: dict[str, Any],
        edge_name: str,
        is_source: bool,
        entity_lookup: dict[tuple[str, str], GraphNode],
    ) -> GraphNode:
        normalized_name = _normalize_name(node_name)
        preferred_labels = self._allowed_labels_for_edge(ontology, edge_name, is_source)

        for preferred_label in preferred_labels + ["Entity"]:
            existing = entity_lookup.get((normalized_name, preferred_label))
            if existing:
                return existing

        row = None
        if preferred_labels:
            placeholders = ",".join("?" for _ in preferred_labels)
            row = conn.execute(
                f"""
                SELECT * FROM nodes
                WHERE graph_id = ? AND normalized_name = ? AND primary_label IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                [graph_id, normalized_name, *preferred_labels],
            ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT * FROM nodes
                WHERE graph_id = ? AND normalized_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (graph_id, normalized_name),
            ).fetchone()
        if row:
            node = self._row_to_node(row)
            entity_lookup[(normalized_name, _primary_label(node.labels))] = node
            entity_lookup[(normalized_name, "Entity")] = node
            return node

        fallback_type = preferred_labels[0] if preferred_labels else "Entity"
        node = self._upsert_node(
            conn,
            graph_id,
            {
                "name": node_name,
                "type": fallback_type,
                "summary": node_name,
                "attributes": {},
            },
        )
        entity_lookup[(normalized_name, _primary_label(node.labels))] = node
        entity_lookup[(normalized_name, "Entity")] = node
        return node

    def _allowed_labels_for_edge(self, ontology: dict[str, Any], edge_name: str, is_source: bool) -> list[str]:
        for edge in ontology.get("edge_types", []):
            if edge.get("name") != edge_name:
                continue
            labels = []
            for pair in edge.get("source_targets", []):
                label = pair.get("source") if is_source else pair.get("target")
                if label and label != "Entity" and label not in labels:
                    labels.append(label)
            return labels
        return []

    def _upsert_edge(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        episode_uuid: str,
        edge: dict[str, Any],
        source_node: GraphNode,
        target_node: GraphNode,
        episode_created_at: str,
    ) -> GraphEdge:
        name = (edge.get("name") or "RELATED_TO").strip() or "RELATED_TO"
        fact = (edge.get("fact") or f"{source_node.name} {name} {target_node.name}").strip()
        attributes = edge.get("attributes") or {}
        learned_at = _now_iso()
        valid_at = _coerce_iso(edge.get("valid_at") or episode_created_at)
        row = conn.execute(
            """
            SELECT * FROM edges
            WHERE graph_id = ? AND source_node_uuid = ? AND target_node_uuid = ? AND name = ? AND fact = ?
            """,
            (graph_id, source_node.uuid_, target_node.uuid_, name, fact),
        ).fetchone()

        if row:
            existing_attributes = _json_loads(row["attributes_json"], {})
            merged_attributes = {**existing_attributes, **attributes}
            conn.execute(
                """
                UPDATE edges
                SET attributes_json = ?, valid_at = COALESCE(valid_at, ?)
                WHERE uuid = ?
                """,
                (_json_dumps(merged_attributes), valid_at, row["uuid"]),
            )
            edge_uuid = row["uuid"]
        else:
            self._invalidate_superseded_edges(
                conn=conn,
                graph_id=graph_id,
                source_node_uuid=source_node.uuid_,
                target_node_uuid=target_node.uuid_,
                edge_name=name,
                new_fact=fact,
                invalid_at=valid_at,
                expired_at=learned_at,
            )
            edge_uuid = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO edges(
                    uuid, graph_id, name, fact, source_node_uuid, target_node_uuid,
                    attributes_json, created_at, valid_at, invalid_at, expired_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    edge_uuid,
                    graph_id,
                    name,
                    fact,
                    source_node.uuid_,
                    target_node.uuid_,
                    _json_dumps(attributes),
                    learned_at,
                    valid_at,
                ),
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO edge_episodes(edge_uuid, episode_uuid)
            VALUES (?, ?)
            """,
            (edge_uuid, episode_uuid),
        )

        row = conn.execute("SELECT * FROM edges WHERE uuid = ?", (edge_uuid,)).fetchone()
        return self._row_to_edge(row, [episode_uuid])

    def _invalidate_superseded_edges(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        source_node_uuid: str,
        target_node_uuid: str,
        edge_name: str,
        new_fact: str,
        invalid_at: str,
        expired_at: str,
    ) -> None:
        """Approximate Zep/Graphiti temporal fact invalidation.

        If a new fact uses the same source/target and either the same relation
        name or an explicitly conflicting relation name, treat the old fact as
        superseded unless it is the same normalized fact. This preserves history
        while keeping active facts current for typical single-user workflows.
        """
        conflicting_names = self._conflicting_names(edge_name)
        rows = conn.execute(
            f"""
            SELECT uuid, fact
            FROM edges
            WHERE graph_id = ?
              AND source_node_uuid = ?
              AND target_node_uuid = ?
              AND name IN ({",".join("?" for _ in conflicting_names)})
              AND invalid_at IS NULL
              AND expired_at IS NULL
            """,
            [graph_id, source_node_uuid, target_node_uuid, *conflicting_names],
        ).fetchall()
        normalized_new_fact = _normalize_fact(new_fact)
        superseded_ids = [
            row["uuid"]
            for row in rows
            if _normalize_fact(row["fact"]) != normalized_new_fact
        ]
        if not superseded_ids:
            return
        conn.execute(
            f"""
            UPDATE edges
            SET invalid_at = ?, expired_at = ?
            WHERE uuid IN ({",".join("?" for _ in superseded_ids)})
            """,
            [invalid_at, expired_at, *superseded_ids],
        )

    def _conflicting_names(self, edge_name: str) -> list[str]:
        names = {edge_name}
        names.update(_CONFLICTING_EDGE_NAMES.get(edge_name.upper(), set()))
        return sorted(names)

    def _refresh_node_embeddings(self, graph_id: str, node_ids: set[str]) -> None:
        if not node_ids:
            return
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM nodes
                WHERE graph_id = ? AND uuid IN ({",".join("?" for _ in node_ids)})
                """,
                [graph_id, *node_ids],
            ).fetchall()
        if not rows:
            return

        texts = []
        ids = []
        for row in rows:
            text = " ".join(
                filter(
                    None,
                    [
                        row["name"],
                        row["summary"],
                        " ".join(_json_loads(row["labels_json"], [])),
                        json.dumps(_json_loads(row["attributes_json"], {}), ensure_ascii=False),
                    ],
                )
            )
            ids.append(row["uuid"])
            texts.append(text)

        try:
            embeddings = self._get_embedding_client().embed_texts(texts)
        except Exception as exc:
            logger.warning("Failed to refresh node embeddings: %s", exc)
            return

        now = _now_iso()
        with self._lock, self._connect() as conn:
            for node_id, embedding in zip(ids, embeddings):
                conn.execute(
                    """
                    INSERT INTO node_embeddings(node_uuid, embedding_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(node_uuid) DO UPDATE SET
                        embedding_json = excluded.embedding_json,
                        updated_at = excluded.updated_at
                    """,
                    (node_id, _json_dumps(embedding), now),
                )

    def _refresh_edge_embeddings(self, graph_id: str, edge_ids: set[str]) -> None:
        if not edge_ids:
            return
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.*, src.name AS source_name, dst.name AS target_name
                FROM edges e
                JOIN nodes src ON src.uuid = e.source_node_uuid
                JOIN nodes dst ON dst.uuid = e.target_node_uuid
                WHERE e.graph_id = ? AND e.uuid IN ({",".join("?" for _ in edge_ids)})
                """,
                [graph_id, *edge_ids],
            ).fetchall()
        if not rows:
            return

        ids = []
        texts = []
        for row in rows:
            ids.append(row["uuid"])
            texts.append(" ".join(filter(None, [row["name"], row["fact"], row["source_name"], row["target_name"]])))

        try:
            embeddings = self._get_embedding_client().embed_texts(texts)
        except Exception as exc:
            logger.warning("Failed to refresh edge embeddings: %s", exc)
            return

        now = _now_iso()
        with self._lock, self._connect() as conn:
            for edge_id, embedding in zip(ids, embeddings):
                conn.execute(
                    """
                    INSERT INTO edge_embeddings(edge_uuid, embedding_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(edge_uuid) DO UPDATE SET
                        embedding_json = excluded.embedding_json,
                        updated_at = excluded.updated_at
                    """,
                    (edge_id, _json_dumps(embedding), now),
                )

    def _refresh_episode_embeddings(self, graph_id: str, episode_ids: set[str]) -> None:
        if not episode_ids:
            return
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM episodes
                WHERE graph_id = ? AND uuid IN ({",".join("?" for _ in episode_ids)})
                """,
                [graph_id, *episode_ids],
            ).fetchall()
        if not rows:
            return

        ids = [row["uuid"] for row in rows]
        texts = [row["data"] or "" for row in rows]

        try:
            embeddings = self._get_embedding_client().embed_texts(texts)
        except Exception as exc:
            logger.warning("Failed to refresh episode embeddings: %s", exc)
            return

        now = _now_iso()
        with self._lock, self._connect() as conn:
            for episode_id, embedding in zip(ids, embeddings):
                conn.execute(
                    """
                    INSERT INTO episode_embeddings(episode_uuid, embedding_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(episode_uuid) DO UPDATE SET
                        embedding_json = excluded.embedding_json,
                        updated_at = excluded.updated_at
                    """,
                    (episode_id, _json_dumps(embedding), now),
                )

    def _load_edge_episode_map(self, conn: sqlite3.Connection, edge_ids: list[str]) -> dict[str, list[str]]:
        if not edge_ids:
            return {}
        rows = conn.execute(
            f"""
            SELECT edge_uuid, episode_uuid
            FROM edge_episodes
            WHERE edge_uuid IN ({",".join("?" for _ in edge_ids)})
            ORDER BY episode_uuid
            """,
            edge_ids,
        ).fetchall()
        episode_map: dict[str, list[str]] = {}
        for row in rows:
            episode_map.setdefault(row["edge_uuid"], []).append(row["episode_uuid"])
        return episode_map

    def _load_edge_endpoint_names(self, conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, str]:
        source = conn.execute("SELECT name FROM nodes WHERE uuid = ?", (row["source_node_uuid"],)).fetchone()
        target = conn.execute("SELECT name FROM nodes WHERE uuid = ?", (row["target_node_uuid"],)).fetchone()
        return (source["name"] if source else "", target["name"] if target else "")

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            uuid_=row["uuid"],
            graph_id=row["graph_id"],
            name=row["name"],
            labels=_json_loads(row["labels_json"], []),
            summary=row["summary"] or "",
            attributes=_json_loads(row["attributes_json"], {}),
            created_at=row["created_at"],
        )

    def _row_to_edge(self, row: sqlite3.Row, episodes: list[str]) -> GraphEdge:
        return GraphEdge(
            uuid_=row["uuid"],
            graph_id=row["graph_id"],
            name=row["name"],
            fact=row["fact"],
            source_node_uuid=row["source_node_uuid"],
            target_node_uuid=row["target_node_uuid"],
            attributes=_json_loads(row["attributes_json"], {}),
            created_at=row["created_at"],
            valid_at=row["valid_at"],
            invalid_at=row["invalid_at"],
            expired_at=row["expired_at"],
            episodes=episodes,
        )

    def _row_to_episode(self, row: sqlite3.Row) -> GraphEpisode:
        return GraphEpisode(
            uuid_=row["uuid"],
            graph_id=row["graph_id"],
            data=row["data"],
            type=row["type"],
            processed=bool(row["processed"]),
            created_at=row["created_at"],
            error=row["error"],
            metadata=_json_loads(row["metadata_json"], {}),
            source_description=row["source_description"],
            role=row["role"],
            role_type=row["role_type"],
            thread_id=row["thread_id"],
            task_id=row["task_id"],
        )

    def _merge_summary(self, existing: str, new_value: str, attributes: dict[str, Any]) -> str:
        existing = (existing or "").strip()
        new_value = (new_value or "").strip()
        if existing and new_value:
            if new_value in existing:
                return existing
            if existing in new_value:
                return new_value
            return f"{existing} {new_value}".strip()
        if new_value:
            return new_value
        if existing:
            return existing
        return self._fallback_summary("", attributes)

    def _fallback_summary(self, name: str, attributes: dict[str, Any]) -> str:
        if attributes:
            pairs = [f"{key}: {value}" for key, value in attributes.items() if value]
            if pairs:
                prefix = f"{name} - " if name else ""
                return prefix + ", ".join(pairs[:4])
        return name or ""
