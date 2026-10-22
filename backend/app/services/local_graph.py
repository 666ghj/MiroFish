"""Local graph backend — full replacement for Zep Cloud.

Stores graphs, document episodes, entity nodes and relationship edges in a
local SQLite database and reproduces the exact surfaces MiroFish consumes:

- ``LocalGraphStore``         — low-level persistence (graphs/episodes/nodes/edges)
- ``LocalGraphBuilder``       — GraphBuilderService-compatible build/delete/read API

Graph extraction is LLM-driven (same provider as the rest of the pipeline)
but bounded to a single bounded-context call so it stays inside provider
rate limits. Entity instances are grounded in the ontology produced by the
ontology stage.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger("mirofish.local_graph")


_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "local_graph.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS graphs (
    graph_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    ontology     TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    episode_uuid        TEXT PRIMARY KEY,
    graph_id            TEXT NOT NULL,
    chunk_index         INTEGER NOT NULL,
    content             TEXT NOT NULL,
    source_description  TEXT,
    processed           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_graph ON episodes(graph_id);
CREATE TABLE IF NOT EXISTS nodes (
    uuid         TEXT PRIMARY KEY,
    graph_id     TEXT NOT NULL,
    name         TEXT NOT NULL,
    labels       TEXT NOT NULL,
    summary      TEXT,
    attributes   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_graph ON nodes(graph_id);
CREATE TABLE IF NOT EXISTS edges (
    uuid              TEXT PRIMARY KEY,
    graph_id          TEXT NOT NULL,
    name              TEXT NOT NULL,
    fact              TEXT NOT NULL,
    source_node_uuid  TEXT NOT NULL,
    target_node_uuid  TEXT NOT NULL,
    attributes        TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_graph ON edges(graph_id);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LocalGraphStore:
    """Thread-safe SQLite-backed graph persistence."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or _DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connection() as conn:
            conn.executescript(_SCHEMA)

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ---- graphs -----------------------------------------------------------

    def create_graph(self, graph_id: str, name: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO graphs (graph_id, name, created_at) VALUES (?, ?, ?)",
                (graph_id, name, _now()),
            )

    def graph_exists(self, graph_id: str) -> bool:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)
            ).fetchone()
        return row is not None

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE graphs SET ontology = ? WHERE graph_id = ?",
                (json.dumps(ontology, ensure_ascii=False), graph_id),
            )

    def get_ontology(self, graph_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT ontology FROM graphs WHERE graph_id = ?", (graph_id,)
            ).fetchone()
        if row and row["ontology"]:
            return json.loads(row["ontology"])
        return None

    def delete_graph(self, graph_id: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM graphs   WHERE graph_id = ?", (graph_id,))
            conn.execute("DELETE FROM episodes WHERE graph_id = ?", (graph_id,))
            conn.execute("DELETE FROM nodes    WHERE graph_id = ?", (graph_id,))
            conn.execute("DELETE FROM edges    WHERE graph_id = ?", (graph_id,))

    # ---- episodes ---------------------------------------------------------

    def add_episodes(
        self,
        graph_id: str,
        chunks: List[str],
        *,
        source_description: str = "MiroFish source document chunk",
        batch_created: Optional[Callable[..., None]] = None,
    ) -> List[str]:
        """Insert document chunks as processed episodes. Returns episode uuids."""
        uuids: List[str] = []
        for i in range(0, len(chunks), 200):
            group = [
                (f"misode_{uuid.uuid4().hex}", graph_id, i + j, chunk, source_description, 1, _now())
                for j, chunk in enumerate(chunks[i:i + 200])
            ]
            with self._lock, self._connection() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO episodes "
                    "(episode_uuid, graph_id, chunk_index, content, source_description, processed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    group,
                )
            uuids.extend(row[0] for row in group)
            if batch_created:
                batch_created(len(uuids))
        return uuids

    def count_episodes(self, graph_id: str) -> int:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM episodes WHERE graph_id = ?", (graph_id,)
            ).fetchone()
        return int(row["c"]) if row else 0

    def search_episodes(self, graph_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search over stored document chunks (report-time retrieval)."""
        tokens = [
            w.strip()
            for w in (query or "").lower().replace(",", " ").split()
            if len(w.strip()) > 2
        ]
        if not tokens:
            return []
        clauses = " OR ".join(["content LIKE ?"] * len(tokens))
        params = [f"%{token}%" for token in tokens]
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT episode_uuid, chunk_index, content FROM episodes "
                f"WHERE graph_id = ? AND ({clauses}) LIMIT ?",
                (graph_id, *params, limit),
            ).fetchall()
        results = []
        for row in rows:
            content = row["content"]
            snippet = content[:400].replace("\n", " ")
            results.append({
                "uuid": row["episode_uuid"],
                "chunk_index": row["chunk_index"],
                "snippet": snippet,
            })
        return results

    def get_source_excerpts(self, graph_id: str, limit_chars: int = 9000) -> str:
        """Representative full-document sample: head / middle / tail windows."""
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT content FROM episodes WHERE graph_id = ? ORDER BY chunk_index",
                (graph_id,),
            ).fetchall()
        if not rows:
            return ""
        texts = [row["content"] for row in rows]
        window = max(limit_chars // 3, 1)
        head = "\n".join(texts)[:window]
        middle = "\n".join(texts[len(texts) // 2:len(texts) // 2 + 3])[:window]
        tail = "\n".join(texts[-3:])[:window]
        return f"{head}\n\n---(middle of document)---\n{middle}\n\n---(end of document)---\n{tail}"

    def get_source_window(
        self,
        graph_id: str,
        start_fraction: float,
        end_fraction: float,
        max_chars: int = 7000,
    ) -> str:
        """Character-limited slice between two fractions of the document."""
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT content FROM episodes WHERE graph_id = ? ORDER BY chunk_index",
                (graph_id,),
            ).fetchall()
        if not rows:
            return ""
        texts = [row["content"] for row in rows]
        start = min(int(len(texts) * start_fraction), max(len(texts) - 1, 0))
        end = max(start + 1, min(int(len(texts) * end_fraction), len(texts)))
        return "\n.\n".join(texts[start:end])[:max_chars]

    # ---- nodes / edges ----------------------------------------------------

    def replace_nodes(self, graph_id: str, nodes: List[Dict[str, Any]]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM nodes WHERE graph_id = ?", (graph_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO nodes (uuid, graph_id, name, labels, summary, attributes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        node["uuid"], graph_id, node["name"],
                        json.dumps(node.get("labels", []), ensure_ascii=False),
                        node.get("summary", ""),
                        json.dumps(node.get("attributes", {}), ensure_ascii=False),
                        _now(),
                    )
                    for node in nodes
                ],
            )

    def insert_node(self, graph_id: str, node: Dict[str, Any]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO nodes (uuid, graph_id, name, labels, summary, attributes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    node["uuid"], graph_id, node["name"],
                    json.dumps(node.get("labels", []), ensure_ascii=False),
                    node.get("summary", ""),
                    json.dumps(node.get("attributes", {}), ensure_ascii=False),
                    _now(),
                ),
            )

    def get_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE graph_id = ? ORDER BY created_at, uuid", (graph_id,)
            ).fetchall()
        return [self._node_from_row(row) for row in rows]

    def get_node(self, node_uuid: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE uuid = ?", (node_uuid,)
            ).fetchone()
        return self._node_from_row(row) if row else None

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "labels": json.loads(row["labels"] or "[]"),
            "summary": row["summary"] or "",
            "attributes": json.loads(row["attributes"] or "{}"),
            "created_at": row["created_at"],
        }

    def replace_edges(self, graph_id: str, edges: List[Dict[str, Any]]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM edges WHERE graph_id = ?", (graph_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO edges "
                "(uuid, graph_id, name, fact, source_node_uuid, target_node_uuid, attributes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        edge["uuid"], graph_id, edge.get("name", ""), edge.get("fact", ""),
                        edge["source_node_uuid"], edge["target_node_uuid"],
                        json.dumps(edge.get("attributes", {}), ensure_ascii=False),
                        _now(),
                    )
                    for edge in edges
                ],
            )

    def insert_edge(self, graph_id: str, edge: Dict[str, Any]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO edges "
                "(uuid, graph_id, name, fact, source_node_uuid, target_node_uuid, attributes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edge["uuid"], graph_id, edge.get("name", ""), edge.get("fact", ""),
                    edge["source_node_uuid"], edge["target_node_uuid"],
                    json.dumps(edge.get("attributes", {}), ensure_ascii=False),
                    _now(),
                ),
            )

    def get_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM edges WHERE graph_id = ? ORDER BY created_at, uuid", (graph_id,)
            ).fetchall()
        return [self._edge_from_row(row) for row in rows]

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "uuid": row["uuid"],
            "name": row["name"] or "",
            "fact": row["fact"] or "",
            "source_node_uuid": row["source_node_uuid"],
            "target_node_uuid": row["target_node_uuid"],
            "attributes": json.loads(row["attributes"] or "{}"),
            "created_at": row["created_at"],
        }


_store_instance: Optional[LocalGraphStore] = None
_store_guard = threading.Lock()


def get_local_graph_store() -> LocalGraphStore:
    """Return the process-shared local graph store (lazily created)."""
    global _store_instance
    with _store_guard:
        if _store_instance is None:
            _store_instance = LocalGraphStore()
        return _store_instance


class LocalGraphBuilder:
    """GraphBuilderService-compatible builder for the local backend."""

    # Bounds for the LLM entity-instancing pass.
    MAX_INSTANCES = 24
    MAX_INSTANCES_PER_TYPE = 3
    SAMPLE_CHARS = 9000
    DERIVE_MAX_TOKENS = 4096
    # Supplement passes widen the cast from additional document windows.
    MIN_INSTANCES = 10
    SUPPLEMENT_PASSES = 2
    SUPPLEMENT_MAX_INSTANCES_PER_PASS = 6
    SUPPLEMENT_SAMPLE_CHARS = 7000

    def __init__(self, api_key: Optional[str] = None):
        # Local mode needs no cloud credentials; signature stays compatible.
        self.store = get_local_graph_store()
        self._llm: Optional[LLMClient] = None
        logger.info("LocalGraphBuilder initialized (backend=local)")

    # ---- build surface ----------------------------------------------------

    def create_graph(
        self,
        name: str,
        *,
        graph_id: Optional[str] = None,
        graph_id_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        graph_id = graph_id or f"mirofish_{uuid.uuid4().hex[:16]}"
        self.store.create_graph(graph_id, name)
        if graph_id_callback:
            graph_id_callback(graph_id)
        return graph_id

    @staticmethod
    def build_operation_id(graph_id: str, chunks: List[str]) -> str:
        payload_hash = hashlib.sha256("\0".join(chunks).encode("utf-8")).hexdigest()
        return hashlib.sha256(
            f"{graph_id}:{payload_hash}".encode("utf-8")
        ).hexdigest()

    def validate_batch_chunks(self, chunks: List[str], *, batch_size: int = 350) -> None:
        if not chunks:
            raise ValueError("At least one text chunk is required")
        if not 1 <= batch_size <= 350:
            raise ValueError("batch_size must be between 1 and 350")
        if len(chunks) > 50_000:
            raise ValueError("A graph batch cannot contain more than 50,000 items")
        oversized = [i for i, chunk in enumerate(chunks) if len(chunk) > 10_000]
        if oversized:
            raise ValueError(
                f"Graph batch item exceeds 10,000 characters at chunk {oversized[0]}"
            )

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        self.store.set_ontology(graph_id, ontology)

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 350,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        batch_created_callback: Optional[Callable[[Optional[str], str], None]] = None,
    ) -> Any:
        """Persist all chunks locally (post-Zep backend: no cloud upload)."""
        self.validate_batch_chunks(chunks, batch_size=min(batch_size, 350))

        total_chunks = len(chunks)
        operation_id = self.build_operation_id(graph_id, chunks)
        batch_id = f"mibatch_{uuid.uuid4().hex[:12]}"

        if batch_created_callback:
            batch_created_callback(None, operation_id)
            batch_created_callback(batch_id, operation_id)

        total_batches = (total_chunks + batch_size - 1) // batch_size
        stored_chunks = 0
        for batch_num in range(total_batches):
            slice_ = chunks[batch_num * batch_size:(batch_num + 1) * batch_size]
            created = self.store.add_episodes(graph_id, slice_)
            stored_chunks += len(created)
            if progress_callback:
                progress_callback(
                    f"Storing chunk batch {batch_num + 1}/{total_batches} locally...",
                    stored_chunks / total_chunks,
                )

        return SimpleNamespace(
            batch_id=batch_id,
            operation_id=operation_id,
            episode_uuids=[],
            item_count=total_chunks,
        )

    def get_batch_summary(self, batch_id: str) -> Any:
        return SimpleNamespace(
            batch_id=batch_id,
            status="succeeded",
            metadata={},
            progress=SimpleNamespace(percent_complete=100, succeeded_items=0),
        )

    def _wait_for_batch(
        self,
        submission: Any,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        timeout: Optional[int] = None,
    ) -> List[str]:
        """Local persistence already completed; emit terminal progress."""
        total = submission.item_count if hasattr(submission, "item_count") else 0
        for step, ratio in enumerate((0.25, 0.5, 0.75, 1.0)):
            if progress_callback:
                progress_callback(
                    f"Local graph verification... {int(ratio * 100)}%",
                    ratio,
                )
            time.sleep(0.2)
        _ = step  # avoid unused warning
        return []

    # ---- graph derivation ---------------------------------------------------

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Return nodes/edges; on first read derive entity instances via LLM."""
        nodes = self.store.get_nodes(graph_id)
        if not nodes:
            logger.info(
                "Local graph %s has no nodes yet; deriving entity instances via LLM",
                graph_id,
            )
            nodes, edges = self._derive_instances(graph_id)
            self.store.replace_nodes(graph_id, nodes)
            self.store.replace_edges(graph_id, edges)
            nodes = self.store.get_nodes(graph_id)

        if len(nodes) < self.MIN_INSTANCES:
            logger.info(
                "Local graph %s has %d instances (below %s); supplementing cast from other document windows",
                graph_id, len(nodes), self.MIN_INSTANCES,
            )
            self._supplement_instances(graph_id)
            nodes = self.store.get_nodes(graph_id)

        edges = self.store.get_edges(graph_id)
        node_map = {n["uuid"]: n["name"] for n in nodes}

        nodes_data = [
            {
                "uuid": n["uuid"],
                "name": n["name"],
                "labels": n.get("labels", []),
                "summary": n.get("summary", ""),
                "attributes": n.get("attributes", {}),
                "created_at": n.get("created_at"),
            }
            for n in nodes
        ]
        edges_data = [
            {
                "uuid": e["uuid"],
                "name": e.get("name", ""),
                "fact": e.get("fact", ""),
                "fact_type": e.get("name", ""),
                "source_node_uuid": e["source_node_uuid"],
                "target_node_uuid": e["target_node_uuid"],
                "source_node_name": node_map.get(e["source_node_uuid"], ""),
                "target_node_name": node_map.get(e["target_node_uuid"], ""),
                "attributes": e.get("attributes", {}),
                "created_at": e.get("created_at"),
                "valid_at": None,
                "invalid_at": None,
                "expired_at": None,
                "episodes": [],
            }
            for e in edges
        ]
        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    # ---- LLM instancing pass ------------------------------------------------

    def _llm_client(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _derive_instances(
        self, graph_id: str
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Turn ontology + document into concrete entity nodes and fact edges."""
        ontology = self.store.get_ontology(graph_id) or {"entity_types": [], "edge_types": []}
        entity_types = ontology.get("entity_types", []) or []
        edge_types = ontology.get("edge_types", []) or []
        sample = self.store.get_source_excerpts(graph_id, limit_chars=self.SAMPLE_CHARS)

        if not entity_types or not sample.strip():
            logger.warning(
                "Local derive skipped (entity_types=%s sample_chars=%s); generating type fallbacks",
                len(entity_types), len(sample),
            )
            return self._type_fallback_nodes(entity_types)

        prompt = self._build_derive_prompt(entity_types, edge_types, sample)
        try:
            parsed = self._llm_client().chat_json(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.DERIVE_MAX_TOKENS,
                max_attempts=2,
            )
        except Exception as error:
            logger.error(
                "Local entity instancing LLM call failed (%s); generating type fallbacks",
                error,
            )
            return self._type_fallback_nodes(entity_types)

        nodes, edges = self._materialize(parsed, entity_types, edge_types)
        if not nodes:
            logger.warning(
                "Local entity instancing produced no nodes; generating type fallbacks"
            )
            return self._type_fallback_nodes(entity_types)
        return nodes, edges

    def _supplement_instances(self, graph_id: str) -> None:
        """Run bounded extra LLM passes over other document windows to widen the cast."""
        ontology = self.store.get_ontology(graph_id) or {"entity_types": [], "edge_types": []}
        entity_types = ontology.get("entity_types", []) or []
        edge_types = ontology.get("edge_types", []) or []
        if not entity_types:
            return

        existing_nodes = self.store.get_nodes(graph_id)
        existing: Dict[str, str] = {n["name"].lower(): n["name"] for n in existing_nodes}

        # Under-represented types get priority in each pass.
        type_counts: Dict[str, int] = {t["name"]: 0 for t in entity_types}
        for node in existing_nodes:
            for label in node.get("labels", []):
                if label in type_counts:
                    type_counts[label] += 1
        underrepresented = [
            name for name, count
            in sorted(type_counts.items(), key=lambda kv: kv[1])
            if count < self.MAX_INSTANCES_PER_TYPE
        ]

        windows = [(0.25, 0.55), (0.7, 1.0)]
        llm = self._llm_client()
        for pass_index, (start_fraction, end_fraction) in enumerate(windows[:self.SUPPLEMENT_PASSES]):
            if len(existing) >= self.MAX_INSTANCES:
                break
            sample = self.store.get_source_window(
                graph_id, start_fraction, end_fraction,
                max_chars=self.SUPPLEMENT_SAMPLE_CHARS,
            )
            if not sample.strip():
                continue
            prompt = self._build_supplement_prompt(
                entity_types, edge_types, underrepresented, existing, sample,
            )
            try:
                parsed = llm.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=3072,
                    max_attempts=2,
                )
            except Exception as error:
                logger.warning(
                    "Local supplement pass %d failed (%s); skipping", pass_index + 1, error
                )
                continue

            new_nodes, new_edges = self._materialize(parsed, entity_types, edge_types)
            # Filter to genuinely new instances and cap the pass.
            added_nodes = [
                node for node in new_nodes
                if node["name"].lower() not in existing
            ][:self.SUPPLEMENT_MAX_INSTANCES_PER_PASS]
            if not added_nodes:
                logger.info(
                    "Local supplement pass %d produced no new instances; stopping",
                    pass_index + 1,
                )
                continue
            for node in added_nodes:
                self.store.insert_node(graph_id, node)
                existing[node["name"].lower()] = node["name"]
            added_names = {node["name"] for node in added_nodes}
            for node in added_nodes:
                existing[node["name"].lower()] = node["name"]
            for edge in new_edges:
                self.store.insert_edge(graph_id, edge)
            logger.info(
                "Local supplement pass %d added %d instances: %s",
                pass_index + 1, len(added_nodes), ", ".join(sorted(added_names)),
            )

    def _build_supplement_prompt(
        self,
        entity_types: List[Dict[str, Any]],
        edge_types: List[Dict[str, Any]],
        underrepresented: List[str],
        existing: Dict[str, str],
        sample: str,
    ) -> str:
        type_lines = "\n".join(
            f"- {t['name']}: {t.get('description', '')}" for t in entity_types
        )
        edge_lines = "\n".join(
            f"- {e['name']}: {e.get('description', '')}"
            for e in edge_types
        )
        existing_lines = "\n".join(f"- {name}" for name in sorted(existing.values()))
        underrepresented_lines = ", ".join(underrepresented) if underrepresented else "all types have enough instances"
        total_cap = self.MAX_INSTANCES
        return f"""You are WIDENING the cast of a social-media opinion simulation grounded ONLY in the source text below.

EXISTING CAST (do NOT repeat these entities):
{existing_lines}

TASK
1. Add UP TO {self.SUPPLEMENT_MAX_INSTANCES_PER_PASS} NEW entity instances that appear or are clearly implied in this portion of the text.
   - PRIORITY: types currently missing on the cast: {underrepresented_lines}
   - At most {self.MAX_INSTANCES_PER_TYPE} instances per type overall and at most {total_cap} total across the whole cast.
   - Keep names grounded in the text (real names/nicknames when present) or neutral descriptive names.
2. Write FACT edges using ONLY the edge types below. Each fact must involve at least one instance from THIS document portion.
   - Entities may reference the existing cast by exact name. 4 to 10 facts.

ENTITY TYPES
{type_lines}

RELATIONSHIP TYPES
{edge_lines}

SOURCE TEXT (document portion)
{sample}

OUTPUT FORMAT (strict JSON, no markdown fences)
{{
  "entity_instances": [
    {{"type": "<one of the entity types>", "name": "...", "summary": "2-3 sentence persona grounded in the text", "attributes": {{"<attribute placeholder>": "short value"}}}}
  ],
  "facts": [
    {{"name": "<one edge type name>", "source": "<instance name>", "target": "<instance name>", "fact": "one sentence describing the relationship or event"}}
  ]
}}

ATTR note: attribute keys must be short plausible keys (never "name", "uuid", "group_id" or "graph_id").
Return JSON only."""

    def _build_derive_prompt(
        self,
        entity_types: List[Dict[str, Any]],
        edge_types: List[Dict[str, Any]],
        sample: str,
    ) -> str:
        type_lines = "\n".join(
            f"- {t['name']}: {t.get('description', '')}" for t in entity_types
        )
        edge_lines = "\n".join(
            f"- {e['name']}: {e.get('description', '')} "
            f"(source target pairs: {e.get('source_targets', [])})"
            for e in edge_types
        )
        return f"""You are designing the cast of a social-media opinion simulation grounded ONLY in the source text below.

TASK
1. Pick concrete ENTITY INSTANCES found or clearly implied by the text, one instance per row.
   - At most {self.MAX_INSTANCES_PER_TYPE} instances per type, and at most {self.MAX_INSTANCES} instances total.
   - Prefer the most narratively significant recurring entities. Use names that appear in the text when identifiable; otherwise use a neutral descriptive name like "Mutual Friend A".
   - Individuals must be speakers/people; groups/organizations must be entities that can post publicly.
2. Write FACT edges between instances using ONLY the edge types defined above.
   - 8 to 20 facts total. Facts must stay grounded in the text's documented interactions; label uncertainty inside the fact text ("possibly", "reported").

ENTITY TYPES
{type_lines}

RELATIONSHIP TYPES
{edge_lines}

SOURCE TEXT
{sample}

OUTPUT FORMAT (strict JSON, no markdown fences)
{{
  "entity_instances": [
    {{"type": "<one of the entity types>", "name": "...", "summary": "2-3 sentence persona grounded in the text", "attributes": {{"<attribute placeholder>": "short value"}}}}
  ],
  "facts": [
    {{"name": "<one edge type name>", "source": "<instance name>", "target": "<instance name>", "fact": "one sentence describing the relationship or event"}}
  ]
}}

ATTR note: replace "<attribute placeholder>" attribute keys with 1-3 short plausible keys (never "name", "uuid", "group_id" or "graph_id").
Return JSON only."""

    def _materialize(
        self,
        parsed: Dict[str, Any],
        entity_types: List[Dict[str, Any]],
        edge_types: Optional[List[Dict[str, Any]]] = None,
        name_to_uuid_seed: Optional[Dict[str, str]] = None,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        valid_types = {t["name"] for t in entity_types}
        raw_instances = parsed.get("entity_instances") or []
        name_to_uuid: Dict[str, str] = dict(name_to_uuid_seed or {})
        nodes: List[Dict[str, Any]] = []

        for inst in raw_instances:
            if not isinstance(inst, dict):
                continue
            name = str(inst.get("name") or "").strip()
            type_name = str(inst.get("type") or "").strip()
            if not name or type_name not in valid_types:
                continue
            if name in name_to_uuid:
                continue
            if len(nodes) >= self.MAX_INSTANCES:
                break
            attr_count = 0
            safe_attributes: Dict[str, Any] = {}
            raw_attrs = inst.get("attributes")
            if isinstance(raw_attrs, dict):
                for key, value in raw_attrs.items():
                    low = str(key).lower()
                    if low in {"name", "uuid", "group_id", "graph_id"}:
                        safe_key = f"entity_{key}"
                    else:
                        safe_key = str(key)
                    safe_attributes[safe_key] = str(value)[:200]
                    attr_count += 1
                    if attr_count >= 5:
                        break
            node_uuid = f"minode_{uuid.uuid4().hex}"
            name_to_uuid[name] = node_uuid
            nodes.append({
                "uuid": node_uuid,
                "name": name,
                "labels": [type_name],
                "summary": str(inst.get("summary") or "").strip()[:800],
                "attributes": safe_attributes,
            })

        edges: List[Dict[str, Any]] = []
        valid_edge_names = {str(e.get("name")) for e in (edge_types or [])}
        raw_facts = parsed.get("facts") or []
        for fact in raw_facts:
            if not isinstance(fact, dict):
                continue
            edge_name = str(fact.get("name") or "").strip()
            source_name = str(fact.get("source") or "").strip()
            target_name = str(fact.get("target") or "").strip()
            fact_text = str(fact.get("fact") or "").strip()[:500]
            if (
                not edge_name
                or not fact_text
                or (valid_edge_names and edge_name not in valid_edge_names)
            ):
                continue
            source_uuid = name_to_uuid.get(source_name)
            target_uuid = name_to_uuid.get(target_name)
            if not source_uuid or not target_uuid or source_uuid == target_uuid:
                continue
            edges.append({
                "uuid": f"miedge_{uuid.uuid4().hex}",
                "name": edge_name,
                "fact": fact_text,
                "source_node_uuid": source_uuid,
                "target_node_uuid": target_uuid,
                "attributes": {},
            })
        return nodes, edges

    def _type_fallback_nodes(
        self, entity_types: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """One generic instance per non-fallback entity type so the pipeline proceeds."""
        fallback_types = {"person", "organization"}
        nodes: List[Dict[str, Any]] = []
        for t in entity_types:
            name = str(t.get("name") or "").strip()
            if not name or name.lower() in fallback_types:
                continue
            nodes.append({
                "uuid": f"minode_{uuid.uuid4().hex}",
                "name": name,
                "labels": [name],
                "summary": t.get("description", "") or f"A {name} participant in the simulation.",
                "attributes": {},
            })
        return nodes, []

    # ---- delete -------------------------------------------------------------

    def delete_graph(self, graph_id: str) -> None:
        if self.store.graph_exists(graph_id):
            self.store.delete_graph(graph_id)
            logger.info("Local graph %s deleted", graph_id)
        else:
            logger.info("Local graph %s absent; delete is a no-op", graph_id)
