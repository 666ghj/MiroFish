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
from typing import Any, Dict, Iterable, List, Optional

from neo4j import GraphDatabase, Driver

from app.config import Config
from app.utils.logger import get_logger

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
                # 从 attributes 中提取时间追踪字段
                attrs = rel.attributes or {}
                valid_at = attrs.pop("valid_at", None) or rel.created_at or _now_iso()
                episodes = attrs.pop("episodes", None) or []
                
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
                        r.created_at = COALESCE(r.created_at, $created_at),
                        r.valid_at = COALESCE(r.valid_at, $valid_at),
                        r.episodes = CASE
                            WHEN r.episodes IS NULL THEN $episodes
                            ELSE r.episodes + [ep IN $episodes WHERE NOT ep IN r.episodes]
                        END
                    """,
                    uuid=rel_uuid,
                    project_id=rel.project_id,
                    graph_id=rel.graph_id,
                    source_uuid=rel.source_uuid,
                    target_uuid=rel.target_uuid,
                    relation_name=rel.relation_name,
                    fact=rel.fact or "",
                    attributes_json=json.dumps(attrs, ensure_ascii=False),
                    created_at=rel.created_at or _now_iso(),
                    valid_at=valid_at,
                    episodes=episodes,
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
                       r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                       r.episodes AS episodes,
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
                        "valid_at": r.get("valid_at"),
                        "invalid_at": r.get("invalid_at"),
                        "expired_at": r.get("expired_at"),
                        "episodes": r.get("episodes") or [],
                    }
                )

        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    # ==================== 新增：图谱记忆更新相关方法 ====================

    def find_similar_entities(
        self, graph_id: str, name: str, entity_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        查找相似实体（用于实体去重）
        
        策略：
        1. 精确匹配（大小写不敏感）
        2. 可选按实体类型过滤
        
        Args:
            graph_id: 图谱ID
            name: 实体名称
            entity_type: 可选的实体类型过滤
            
        Returns:
            相似实体列表
        """
        normalized_name = (name or "").strip().lower()
        
        with self._driver.session(database=self._database) as session:
            if entity_type:
                result = session.run(
                    """
                    MATCH (e:Entity {graph_id: $graph_id})
                    WHERE toLower(e.name) = $normalized_name
                      AND e.entity_type = $entity_type
                    RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type,
                           e.summary AS summary, e.created_at AS created_at
                    """,
                    graph_id=graph_id,
                    normalized_name=normalized_name,
                    entity_type=entity_type,
                )
            else:
                result = session.run(
                    """
                    MATCH (e:Entity {graph_id: $graph_id})
                    WHERE toLower(e.name) = $normalized_name
                    RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type,
                           e.summary AS summary, e.created_at AS created_at
                    """,
                    graph_id=graph_id,
                    normalized_name=normalized_name,
                )
            
            entities = []
            for record in result:
                entities.append({
                    "uuid": record.get("uuid"),
                    "name": record.get("name"),
                    "entity_type": record.get("entity_type"),
                    "summary": record.get("summary"),
                    "created_at": record.get("created_at"),
                })
            return entities

    def search_similar_entities(
        self, graph_id: str, name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        搜索所有可能相似的实体（用于实体去重的候选召回）
        
        与 find_similar_entities 不同，此方法：
        1. 不限制实体类型
        2. 返回更多候选（包括部分匹配）
        3. 用于后续的模糊匹配处理
        
        搜索策略：
        1. 精确匹配（名称完全相同，忽略大小写）
        2. 前缀匹配（名称以搜索词开头）
        3. 包含匹配（名称包含搜索词）
        
        Args:
            graph_id: 图谱ID
            name: 实体名称
            limit: 返回的最大候选数量
            
        Returns:
            候选实体列表
        """
        if not name:
            return []
        
        normalized_name = (name or "").strip().lower()
        
        # 提取关键词用于包含搜索（取前几个字符或整个名称）
        search_prefix = normalized_name[:3] if len(normalized_name) > 3 else normalized_name
        
        with self._driver.session(database=self._database) as session:
            # 使用一个综合查询，按匹配程度排序
            result = session.run(
                """
                MATCH (e:Entity {graph_id: $graph_id})
                WITH e, toLower(e.name) AS lower_name
                WHERE lower_name = $normalized_name
                   OR lower_name STARTS WITH $search_prefix
                   OR lower_name CONTAINS $search_prefix
                   OR $normalized_name CONTAINS lower_name
                WITH e, lower_name,
                     CASE 
                         WHEN lower_name = $normalized_name THEN 3
                         WHEN lower_name STARTS WITH $normalized_name THEN 2
                         WHEN lower_name CONTAINS $normalized_name THEN 1
                         ELSE 0
                     END AS match_score
                RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type,
                       e.summary AS summary, e.source_entity_types AS source_entity_types,
                       e.created_at AS created_at, match_score
                ORDER BY match_score DESC, e.name
                LIMIT $limit
                """,
                graph_id=graph_id,
                normalized_name=normalized_name,
                search_prefix=search_prefix,
                limit=limit,
            )
            
            entities = []
            for record in result:
                entities.append({
                    "uuid": record.get("uuid"),
                    "name": record.get("name"),
                    "entity_type": record.get("entity_type"),
                    "summary": record.get("summary"),
                    "source_entity_types": record.get("source_entity_types") or [],
                    "created_at": record.get("created_at"),
                    "match_score": record.get("match_score", 0),
                })
            return entities

    def update_entity_summary(
        self, uuid: str, summary: str, append_source_types: Optional[List[str]] = None
    ) -> bool:
        """
        更新实体摘要（用于实体合并时更新信息）
        
        Args:
            uuid: 实体UUID
            summary: 新的摘要（如果非空则更新）
            append_source_types: 要追加的实体类型列表
            
        Returns:
            是否更新成功
        """
        with self._driver.session(database=self._database) as session:
            if summary and append_source_types:
                result = session.run(
                    """
                    MATCH (e:Entity {uuid: $uuid})
                    SET e.summary = CASE 
                            WHEN $summary IS NOT NULL AND $summary <> "" THEN $summary
                            ELSE e.summary
                        END,
                        e.source_entity_types = CASE
                            WHEN e.source_entity_types IS NULL THEN $append_types
                            ELSE e.source_entity_types + [t IN $append_types WHERE NOT t IN e.source_entity_types]
                        END
                    RETURN e.uuid AS uuid
                    """,
                    uuid=uuid,
                    summary=summary,
                    append_types=append_source_types or [],
                )
            elif summary:
                result = session.run(
                    """
                    MATCH (e:Entity {uuid: $uuid})
                    SET e.summary = $summary
                    RETURN e.uuid AS uuid
                    """,
                    uuid=uuid,
                    summary=summary,
                )
            elif append_source_types:
                result = session.run(
                    """
                    MATCH (e:Entity {uuid: $uuid})
                    SET e.source_entity_types = CASE
                            WHEN e.source_entity_types IS NULL THEN $append_types
                            ELSE e.source_entity_types + [t IN $append_types WHERE NOT t IN e.source_entity_types]
                        END
                    RETURN e.uuid AS uuid
                    """,
                    uuid=uuid,
                    append_types=append_source_types,
                )
            else:
                return False
            
            return result.single() is not None

    def get_edges_between_entities(
        self, graph_id: str, source_uuid: str, target_uuid: str, include_invalid: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取两个实体之间的所有边
        
        Args:
            graph_id: 图谱ID
            source_uuid: 源实体UUID
            target_uuid: 目标实体UUID
            include_invalid: 是否包含已失效的边
            
        Returns:
            边列表
        """
        with self._driver.session(database=self._database) as session:
            if include_invalid:
                result = session.run(
                    """
                    MATCH (s:Entity {uuid: $source_uuid})-[r:REL {graph_id: $graph_id}]->(t:Entity {uuid: $target_uuid})
                    RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact, r.fact_type AS fact_type,
                           r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                           r.episodes AS episodes, r.attributes_json AS attributes_json,
                           r.created_at AS created_at
                    """,
                    graph_id=graph_id,
                    source_uuid=source_uuid,
                    target_uuid=target_uuid,
                )
            else:
                result = session.run(
                    """
                    MATCH (s:Entity {uuid: $source_uuid})-[r:REL {graph_id: $graph_id}]->(t:Entity {uuid: $target_uuid})
                    WHERE r.invalid_at IS NULL OR r.invalid_at = ""
                    RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact, r.fact_type AS fact_type,
                           r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.expired_at AS expired_at,
                           r.episodes AS episodes, r.attributes_json AS attributes_json,
                           r.created_at AS created_at
                    """,
                    graph_id=graph_id,
                    source_uuid=source_uuid,
                    target_uuid=target_uuid,
                )
            
            edges = []
            for record in result:
                attrs = {}
                try:
                    attrs = json.loads(record.get("attributes_json") or "{}")
                except Exception:
                    pass
                edges.append({
                    "uuid": record.get("uuid"),
                    "name": record.get("name"),
                    "fact": record.get("fact"),
                    "fact_type": record.get("fact_type"),
                    "valid_at": record.get("valid_at"),
                    "invalid_at": record.get("invalid_at"),
                    "expired_at": record.get("expired_at"),
                    "episodes": record.get("episodes") or [],
                    "attributes": attrs,
                    "created_at": record.get("created_at"),
                })
            return edges

    def invalidate_edge(self, edge_uuid: str, invalid_at: Optional[str] = None) -> bool:
        """
        标记边为失效
        
        Args:
            edge_uuid: 边UUID
            invalid_at: 失效时间，默认为当前时间
            
        Returns:
            是否成功标记
        """
        invalid_at = invalid_at or _now_iso()
        
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH ()-[r:REL {uuid: $uuid}]->()
                SET r.invalid_at = $invalid_at,
                    r.expired_at = $invalid_at
                RETURN r.uuid AS uuid
                """,
                uuid=edge_uuid,
                invalid_at=invalid_at,
            )
            return result.single() is not None

    def add_episode_to_edges(self, edge_uuids: List[str], episode_id: str) -> int:
        """
        将 episode 关联到边
        
        Args:
            edge_uuids: 边UUID列表
            episode_id: Episode ID
            
        Returns:
            更新的边数量
        """
        if not edge_uuids:
            return 0
        
        updated_count = 0
        with self._driver.session(database=self._database) as session:
            for uuid_ in edge_uuids:
                result = session.run(
                    """
                    MATCH ()-[r:REL {uuid: $uuid}]->()
                    SET r.episodes = CASE
                        WHEN r.episodes IS NULL THEN [$episode_id]
                        WHEN NOT $episode_id IN r.episodes THEN r.episodes + $episode_id
                        ELSE r.episodes
                    END
                    RETURN r.uuid AS uuid
                    """,
                    uuid=uuid_,
                    episode_id=episode_id,
                )
                if result.single():
                    updated_count += 1
        return updated_count

    def get_entity_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        根据UUID获取实体详情
        
        Args:
            uuid: 实体UUID
            
        Returns:
            实体详情字典，不存在则返回None
        """
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH (e:Entity {uuid: $uuid})
                RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type,
                       e.summary AS summary, e.attributes_json AS attributes_json,
                       e.graph_id AS graph_id, e.project_id AS project_id,
                       e.created_at AS created_at
                """,
                uuid=uuid,
            )
            record = result.single()
            if not record:
                return None
            
            attrs = {}
            try:
                attrs = json.loads(record.get("attributes_json") or "{}")
            except Exception:
                pass
            
            return {
                "uuid": record.get("uuid"),
                "name": record.get("name"),
                "entity_type": record.get("entity_type"),
                "summary": record.get("summary"),
                "attributes": attrs,
                "graph_id": record.get("graph_id"),
                "project_id": record.get("project_id"),
                "created_at": record.get("created_at"),
            }

    def get_valid_edges_for_entity(
        self, graph_id: str, entity_uuid: str, include_invalid: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取实体相关的所有有效边（入边+出边）
        
        Args:
            graph_id: 图谱ID
            entity_uuid: 实体UUID
            include_invalid: 是否包含已失效的边
            
        Returns:
            边列表
        """
        with self._driver.session(database=self._database) as session:
            if include_invalid:
                query = """
                    MATCH (e:Entity {uuid: $entity_uuid})
                    OPTIONAL MATCH (e)-[r1:REL {graph_id: $graph_id}]->(t:Entity)
                    OPTIONAL MATCH (s:Entity)-[r2:REL {graph_id: $graph_id}]->(e)
                    WITH collect(DISTINCT r1) + collect(DISTINCT r2) AS rels
                    UNWIND rels AS r
                    WITH r WHERE r IS NOT NULL
                    MATCH (source:Entity)-[r]->(target:Entity)
                    RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                           r.valid_at AS valid_at, r.invalid_at AS invalid_at,
                           source.uuid AS source_uuid, source.name AS source_name,
                           target.uuid AS target_uuid, target.name AS target_name
                """
            else:
                query = """
                    MATCH (e:Entity {uuid: $entity_uuid})
                    OPTIONAL MATCH (e)-[r1:REL {graph_id: $graph_id}]->(t:Entity)
                    WHERE r1.invalid_at IS NULL OR r1.invalid_at = ""
                    OPTIONAL MATCH (s:Entity)-[r2:REL {graph_id: $graph_id}]->(e)
                    WHERE r2.invalid_at IS NULL OR r2.invalid_at = ""
                    WITH collect(DISTINCT r1) + collect(DISTINCT r2) AS rels
                    UNWIND rels AS r
                    WITH r WHERE r IS NOT NULL
                    MATCH (source:Entity)-[r]->(target:Entity)
                    RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                           r.valid_at AS valid_at, r.invalid_at AS invalid_at,
                           source.uuid AS source_uuid, source.name AS source_name,
                           target.uuid AS target_uuid, target.name AS target_name
                """
            
            result = session.run(query, graph_id=graph_id, entity_uuid=entity_uuid)
            
            edges = []
            for record in result:
                edges.append({
                    "uuid": record.get("uuid"),
                    "name": record.get("name"),
                    "fact": record.get("fact"),
                    "valid_at": record.get("valid_at"),
                    "invalid_at": record.get("invalid_at"),
                    "source_uuid": record.get("source_uuid"),
                    "source_name": record.get("source_name"),
                    "target_uuid": record.get("target_uuid"),
                    "target_name": record.get("target_name"),
                })
            return edges
