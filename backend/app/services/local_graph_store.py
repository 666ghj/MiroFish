"""
Local graph store (Neo4j)

This is a replacement for Zep Cloud graph storage to avoid rate limits.
Graph data is isolated by project_id and graph_id.
"""

from __future__ import annotations

import json
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from neo4j import GraphDatabase, Driver

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.local_graph_store")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _stable_entity_uuid(project_id: str, entity_type: str, name: str) -> str:
    normalized = (name or "").strip().lower()
    base = f"{project_id}:{entity_type}:{normalized}".encode("utf-8")
    digest = hashlib.sha1(base).hexdigest()[:16]
    return f"ent_{digest}"


@dataclass(frozen=True)
class LocalEntity:
    project_id: str
    graph_id: str
    name: str
    entity_type: str
    summary: str = ""
    attributes: Optional[Dict[str, Any]] = None
    source_entity_types: Optional[List[str]] = None
    created_at: Optional[str] = None

    @property
    def uuid(self) -> str:
        return _stable_entity_uuid(self.project_id, self.entity_type, self.name)


@dataclass(frozen=True)
class LocalRelation:
    project_id: str
    graph_id: str
    source_uuid: str
    target_uuid: str
    relation_name: str
    fact: str = ""
    attributes: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    uuid: str = ""


class LocalNeo4jGraphStore:
    def __init__(self):
        self._driver: Driver = GraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD),
        )
        self._database = Config.NEO4J_DATABASE
        self._ensure_schema()

    def close(self):
        try:
            self._driver.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        statements = [
            # Graph meta
            "CREATE CONSTRAINT graph_id_unique IF NOT EXISTS FOR (g:Graph) REQUIRE g.graph_id IS UNIQUE",
            # Entity uniqueness within a project+type+name key (uuid is deterministic)
            "CREATE CONSTRAINT entity_uuid_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE",
            "CREATE INDEX entity_graph_id IF NOT EXISTS FOR (e:Entity) ON (e.graph_id)",
            "CREATE INDEX entity_project_id IF NOT EXISTS FOR (e:Entity) ON (e.project_id)",
            "CREATE INDEX relation_graph_id IF NOT EXISTS FOR ()-[r:REL]-() ON (r.graph_id)",
            "CREATE INDEX chunk_graph_id IF NOT EXISTS FOR (c:Chunk) ON (c.graph_id)",
        ]

        with self._driver.session(database=self._database) as session:
            for cypher in statements:
                try:
                    session.run(cypher)
                except Exception as e:
                    # Neo4j versions vary; log and continue to avoid hard failure.
                    logger.warning(f"Neo4j schema statement failed: {cypher} err={str(e)[:120]}")

    def create_graph(self, project_id: str, name: str, ontology: Optional[Dict[str, Any]] = None) -> str:
        graph_id = f"mirofish_local_{uuid.uuid4().hex[:16]}"
        created_at = _now_iso()
        ontology_json = json.dumps(ontology or {}, ensure_ascii=False)

        with self._driver.session(database=self._database) as session:
            session.run(
                """
                CREATE (g:Graph {
                    graph_id: $graph_id,
                    project_id: $project_id,
                    name: $name,
                    ontology_json: $ontology_json,
                    created_at: $created_at
                })
                """,
                graph_id=graph_id,
                project_id=project_id,
                name=name,
                ontology_json=ontology_json,
                created_at=created_at,
            )

        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                MATCH (g:Graph {graph_id: $graph_id})
                OPTIONAL MATCH (g)-[:HAS_CHUNK]->(c:Chunk)
                OPTIONAL MATCH (c)-[m:MENTIONS]->(e:Entity)
                OPTIONAL MATCH (e)-[r:REL]->(e2:Entity)
                DETACH DELETE g, c, e, e2
                """,
                graph_id=graph_id,
            )
            # In case there are entities not linked to graph meta (older runs)
            session.run("MATCH (e:Entity {graph_id:$graph_id}) DETACH DELETE e", graph_id=graph_id)
            session.run("MATCH (c:Chunk {graph_id:$graph_id}) DETACH DELETE c", graph_id=graph_id)

    def upsert_entities(self, entities: Iterable[LocalEntity]) -> List[str]:
        uuids: List[str] = []
        with self._driver.session(database=self._database) as session:
            for ent in entities:
                uuids.append(ent.uuid)
                session.run(
                    """
                    MERGE (e:Entity {uuid: $uuid})
                    SET e.project_id = $project_id,
                        e.graph_id = $graph_id,
                        e.name = $name,
                        e.entity_type = $entity_type,
                        e.summary = CASE
                            WHEN $summary IS NULL OR $summary = "" THEN e.summary
                            ELSE $summary
                        END,
                        e.attributes_json = CASE
                            WHEN $attributes_json IS NULL OR $attributes_json = "{}" THEN e.attributes_json
                            ELSE $attributes_json
                        END,
                        e.source_entity_types = CASE
                            WHEN e.source_entity_types IS NULL THEN $source_entity_types
                            ELSE e.source_entity_types + [t IN $source_entity_types WHERE NOT t IN e.source_entity_types]
                        END,
                        e.created_at = COALESCE(e.created_at, $created_at)
                    """,
                    uuid=ent.uuid,
                    project_id=ent.project_id,
                    graph_id=ent.graph_id,
                    name=ent.name,
                    entity_type=ent.entity_type,
                    summary=ent.summary or "",
                    attributes_json=json.dumps(ent.attributes or {}, ensure_ascii=False),
                    source_entity_types=list(dict.fromkeys([t for t in (ent.source_entity_types or []) if t])),
                    created_at=ent.created_at or _now_iso(),
                )
        return uuids

    def upsert_chunk(self, project_id: str, graph_id: str, chunk_id: str, text: str) -> None:
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                MERGE (c:Chunk {chunk_id: $chunk_id})
                SET c.project_id = $project_id,
                    c.graph_id = $graph_id,
                    c.text = $text,
                    c.created_at = COALESCE(c.created_at, $created_at)
                WITH c
                MATCH (g:Graph {graph_id: $graph_id})
                MERGE (g)-[:HAS_CHUNK]->(c)
                """,
                chunk_id=chunk_id,
                project_id=project_id,
                graph_id=graph_id,
                text=text,
                created_at=_now_iso(),
            )

    def link_mentions(self, chunk_id: str, entity_uuids: Iterable[str], graph_id: str) -> None:
        entity_uuids = list(entity_uuids)
        if not entity_uuids:
            return
        with self._driver.session(database=self._database) as session:
            session.run(
                """
                MATCH (c:Chunk {chunk_id: $chunk_id, graph_id: $graph_id})
                UNWIND $entity_uuids AS uuid
                MATCH (e:Entity {uuid: uuid, graph_id: $graph_id})
                MERGE (c)-[:MENTIONS]->(e)
                """,
                chunk_id=chunk_id,
                graph_id=graph_id,
                entity_uuids=entity_uuids,
            )

    def upsert_relations(self, relations: Iterable[LocalRelation]) -> None:
        with self._driver.session(database=self._database) as session:
            for rel in relations:
                rel_uuid = rel.uuid or f"rel_{uuid.uuid4().hex[:16]}"
                session.run(
                    """
                    MATCH (s:Entity {uuid: $source_uuid, graph_id: $graph_id})
                    MATCH (t:Entity {uuid: $target_uuid, graph_id: $graph_id})
                    MERGE (s)-[r:REL {uuid: $uuid}]->(t)
                    SET r.project_id = $project_id,
                        r.graph_id = $graph_id,
                        r.name = $relation_name,
                        r.fact = $fact,
                        r.fact_type = $relation_name,
                        r.attributes_json = $attributes_json,
                        r.created_at = COALESCE(r.created_at, $created_at)
                    """,
                    uuid=rel_uuid,
                    project_id=rel.project_id,
                    graph_id=rel.graph_id,
                    source_uuid=rel.source_uuid,
                    target_uuid=rel.target_uuid,
                    relation_name=rel.relation_name,
                    fact=rel.fact or "",
                    attributes_json=json.dumps(rel.attributes or {}, ensure_ascii=False),
                    created_at=rel.created_at or _now_iso(),
                )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        with self._driver.session(database=self._database) as session:
            node_records = session.run(
                """
                MATCH (e:Entity {graph_id: $graph_id})
                RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type,
                       e.summary AS summary, e.attributes_json AS attributes_json,
                       e.source_entity_types AS source_entity_types,
                       e.created_at AS created_at
                """,
                graph_id=graph_id,
            )

            nodes: List[Dict[str, Any]] = []
            node_name_map: Dict[str, str] = {}
            for r in node_records:
                attrs = {}
                try:
                    attrs = json.loads(r.get("attributes_json") or "{}")
                except Exception:
                    attrs = {}
                if isinstance(r.get("source_entity_types"), list):
                    attrs["source_entity_types"] = r.get("source_entity_types")
                uuid_ = r.get("uuid")
                name = r.get("name") or ""
                node_name_map[uuid_] = name
                entity_type = r.get("entity_type") or "Entity"
                nodes.append(
                    {
                        "uuid": uuid_,
                        "name": name,
                        "labels": ["Entity", entity_type],
                        "summary": r.get("summary") or "",
                        "attributes": attrs,
                        "created_at": r.get("created_at"),
                    }
                )

            edge_records = session.run(
                """
                MATCH (s:Entity {graph_id: $graph_id})-[r:REL {graph_id: $graph_id}]->(t:Entity {graph_id: $graph_id})
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact, r.fact_type AS fact_type,
                       r.attributes_json AS attributes_json, r.created_at AS created_at,
                       s.uuid AS source_uuid, t.uuid AS target_uuid
                """,
                graph_id=graph_id,
            )

            edges: List[Dict[str, Any]] = []
            for r in edge_records:
                attrs = {}
                try:
                    attrs = json.loads(r.get("attributes_json") or "{}")
                except Exception:
                    attrs = {}
                source_uuid = r.get("source_uuid")
                target_uuid = r.get("target_uuid")
                edges.append(
                    {
                        "uuid": r.get("uuid"),
                        "name": r.get("name") or "",
                        "fact": r.get("fact") or "",
                        "fact_type": r.get("fact_type") or (r.get("name") or ""),
                        "source_node_uuid": source_uuid,
                        "target_node_uuid": target_uuid,
                        "source_node_name": node_name_map.get(source_uuid, ""),
                        "target_node_name": node_name_map.get(target_uuid, ""),
                        "attributes": attrs,
                        "created_at": r.get("created_at"),
                        "valid_at": None,
                        "invalid_at": None,
                        "expired_at": None,
                        "episodes": [],
                    }
                )

        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
