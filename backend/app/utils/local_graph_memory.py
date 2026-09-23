"""Neo4j 本地图记忆后端（novel-mac fork）。

``GRAPH_MEMORY_BACKEND=neo4j_local`` 时由 :func:`app.utils.zep.get_zep_client`
返回本客户端，替代 Zep Cloud。只实现 MiroFish 实际调用的接口子集，方法名与
参数形式对齐 zep-cloud 3.25 SDK：

- ``graph.create / get / delete``
- ``graph.add_fact_triple``（确定性结构化写入，novel seed 端点使用）
- ``graph.node.get / get_edges``
- ``graph.node.with_raw_response.get_by_graph_id``（``.data`` + ``.headers`` 分页）
- ``graph.edge.with_raw_response.get_by_graph_id``

NotFoundError 复用 ``zep_cloud.NotFoundError``，消费方现有 except 分支不改。
Neo4j 中 ``MiroFishNode`` / ``MiroFishGraph`` 是内部标记 label，读回的
``labels`` 剔除该标记，保持 ZepEntityReader 的类型筛选语义（额外标签 =
已定义实体类型）。云端的 batch 文本抽取管线不属于本后端：结构化种子一律
走 ``add_fact_triple``。
"""

from __future__ import annotations

import json
import re
import uuid as uuidlib
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

from neo4j import GraphDatabase
from zep_cloud import NotFoundError

_MARKER_LABEL = "MiroFishNode"
_MARKER_GRAPH_LABEL = "MiroFishGraph"
_EDGE_TYPE = "MiroFishEdge"
_LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

DEFAULT_LOCAL_PAGE_SIZE = 100


def _safe_label(label: str) -> str:
    """校验动态 Neo4j label；label 无法参数化，必须严格白名单。"""

    if not isinstance(label, str) or not _LABEL_PATTERN.match(label):
        raise ValueError(f"非法实体标签: {label!r}")
    if label in (_MARKER_LABEL, _MARKER_GRAPH_LABEL):
        raise ValueError(f"保留标签不可用于实体: {label!r}")
    return f"`{label}`"


def _normalize_labels(labels: Optional[Sequence[str]]) -> List[str]:
    normalized = list(labels or [])
    if not normalized:
        normalized = ["Entity"]
    if "Entity" not in normalized:
        normalized = ["Entity", *normalized]
    return normalized


def _to_attributes_json(attributes: Optional[Dict[str, Any]]) -> str:
    return json.dumps(attributes or {}, ensure_ascii=False)


def _from_attributes_json(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _not_found(message: str, payload: Dict[str, Any]) -> NotFoundError:
    from zep_cloud.core.api_error import ApiError

    return NotFoundError(
        body=ApiError(status_code=404, body={"message": message, **payload})
    )


def _node_namespace(record_node) -> SimpleNamespace:
    labels = [label for label in record_node["labels"] if label != _MARKER_LABEL]
    return SimpleNamespace(
        uuid_=record_node["uuid"],
        uuid=record_node["uuid"],
        name=record_node["name"] or "",
        labels=labels,
        summary=record_node["summary"] or "",
        attributes=_from_attributes_json(record_node["attributes_json"]),
    )


def _edge_namespace(record_edge, source_uuid: str, target_uuid: str) -> SimpleNamespace:
    return SimpleNamespace(
        uuid_=record_edge["uuid"],
        uuid=record_edge["uuid"],
        name=record_edge["name"] or "",
        fact=record_edge["fact"] or "",
        source_node_uuid=source_uuid,
        target_node_uuid=target_uuid,
        attributes=_from_attributes_json(record_edge["attributes_json"]),
    )


class _RawResponse(SimpleNamespace):
    """对齐 zep-cloud with_raw_response 的分页返回形状。"""


class LocalGraphMemoryClient:
    """Neo4j 驱动的本地图记忆客户端，接口对齐 zep-cloud 子集。"""

    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self.graph = _GraphApi(self._driver)

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()


class _GraphApi:
    def __init__(self, driver):
        self._driver = driver
        self.node = _NodeApi(driver)
        self.edge = _EdgeApi(driver)

    # ---- 生命周期 ----

    def create(self, *, graph_id: str, name: Optional[str] = None,
               description: Optional[str] = None, **_ignored) -> SimpleNamespace:
        with self._driver.session() as session:
            session.run(
                f"MERGE (g:{_MARKER_GRAPH_LABEL} {{graph_id: $graph_id}}) "
                "SET g.name = $name, g.description = $description, "
                "    g.created_at = coalesce(g.created_at, datetime())",
                graph_id=graph_id,
                name=name or graph_id,
                description=description or "",
            )
        return SimpleNamespace(uuid_=graph_id, name=name or graph_id)

    def get(self, *, graph_id: str, **_ignored) -> SimpleNamespace:
        with self._driver.session() as session:
            record = session.run(
                f"MATCH (g:{_MARKER_GRAPH_LABEL} {{graph_id: $graph_id}}) "
                "RETURN g.graph_id AS gid, g.name AS name, g.description AS description",
                graph_id=graph_id,
            ).single()
        if record is None:
            raise _not_found(f"graph {graph_id} not found", {"graph_id": graph_id})
        return SimpleNamespace(
            uuid_=record["gid"], name=record["name"], description=record["description"]
        )

    def delete(self, *, graph_id: str, **_ignored) -> None:
        with self._driver.session() as session:
            existing = session.run(
                f"MATCH (g:{_MARKER_GRAPH_LABEL} {{graph_id: $graph_id}}) RETURN count(g) AS c",
                graph_id=graph_id,
            ).single()
            if existing is None or existing["c"] == 0:
                raise _not_found(f"graph {graph_id} not found", {"graph_id": graph_id})
            session.run(
                f"MATCH (n:{_MARKER_LABEL} {{graph_id: $graph_id}}) DETACH DELETE n",
                graph_id=graph_id,
            )
            session.run(
                f"MATCH (g:{_MARKER_GRAPH_LABEL} {{graph_id: $graph_id}}) DELETE g",
                graph_id=graph_id,
            )

    # ---- 确定性结构化写入 ----

    def add_fact_triple(
        self,
        *,
        fact: str,
        fact_name: str,
        graph_id: Optional[str] = None,
        fact_uuid: Optional[str] = None,
        edge_attributes: Optional[Dict[str, Any]] = None,
        source_node_uuid: Optional[str] = None,
        source_node_name: Optional[str] = None,
        source_node_labels: Optional[Sequence[str]] = None,
        source_node_summary: Optional[str] = None,
        source_node_attributes: Optional[Dict[str, Any]] = None,
        target_node_uuid: Optional[str] = None,
        target_node_name: Optional[str] = None,
        target_node_labels: Optional[Sequence[str]] = None,
        target_node_summary: Optional[str] = None,
        target_node_attributes: Optional[Dict[str, Any]] = None,
        **_ignored,
    ) -> SimpleNamespace:
        if not graph_id:
            raise ValueError("add_fact_triple 需要 graph_id")
        if not source_node_name and not source_node_uuid:
            raise ValueError("source 节点需要 name 或 uuid")
        if not target_node_name and not target_node_uuid:
            raise ValueError("target 节点需要 name 或 uuid")

        with self._driver.session() as session:
            exists = session.run(
                f"MATCH (g:{_MARKER_GRAPH_LABEL} {{graph_id: $graph_id}}) RETURN count(g) AS c",
                graph_id=graph_id,
            ).single()
            if exists is None or exists["c"] == 0:
                raise _not_found(f"graph {graph_id} not found", {"graph_id": graph_id})

            source_uuid = self._upsert_node(
                session,
                graph_id=graph_id,
                node_uuid=source_node_uuid,
                node_name=source_node_name,
                node_labels=source_node_labels,
                node_summary=source_node_summary,
                node_attributes=source_node_attributes,
            )
            target_uuid = self._upsert_node(
                session,
                graph_id=graph_id,
                node_uuid=target_node_uuid,
                node_name=target_node_name,
                node_labels=target_node_labels,
                node_summary=target_node_summary,
                node_attributes=target_node_attributes,
            )

            edge_uuid = fact_uuid or uuidlib.uuid4().hex
            session.run(
                f"MATCH (s:{_MARKER_LABEL} {{uuid: $source_uuid}}), "
                f"(t:{_MARKER_LABEL} {{uuid: $target_uuid}}) "
                f"CREATE (s)-[:{_EDGE_TYPE} {{"
                "    uuid: $edge_uuid, graph_id: $graph_id, name: $fact_name, "
                "    fact: $fact, attributes_json: $attributes_json"
                "}]->(t)",
                edge_uuid=edge_uuid,
                source_uuid=source_uuid,
                target_uuid=target_uuid,
                graph_id=graph_id,
                fact_name=fact_name or "relates_to",
                fact=fact,
                attributes_json=_to_attributes_json(edge_attributes),
            )

        return SimpleNamespace(
            uuid_=edge_uuid, fact=fact, fact_name=fact_name or "relates_to"
        )

    def _upsert_node(
        self,
        session,
        *,
        graph_id: str,
        node_uuid: Optional[str],
        node_name: Optional[str],
        node_labels: Optional[Sequence[str]],
        node_summary: Optional[str],
        node_attributes: Optional[Dict[str, Any]],
    ) -> str:
        if node_uuid:
            record = session.run(
                f"MATCH (n:{_MARKER_LABEL} {{uuid: $uuid}}) RETURN n.uuid AS uuid",
                uuid=node_uuid,
            ).single()
            if record is None:
                raise _not_found(f"node {node_uuid} not found", {"uuid": node_uuid})
            return record["uuid"]

        existing = session.run(
            f"MATCH (n:{_MARKER_LABEL} {{graph_id: $graph_id, name: $name}}) "
            "RETURN n.uuid AS uuid",
            graph_id=graph_id,
            name=node_name,
        ).single()
        if existing is not None:
            target_uuid = existing["uuid"]
            self._apply_labels(session, target_uuid, node_labels)
            return target_uuid

        target_uuid = uuidlib.uuid4().hex
        labels = _normalize_labels(node_labels)
        label_fragment = "".join(":" + _safe_label(label) for label in labels)
        session.run(
            f"CREATE (n:{_MARKER_LABEL}{label_fragment} {{"
            "    uuid: $uuid, graph_id: $graph_id, name: $name, "
            "    summary: $summary, attributes_json: $attributes_json"
            "})",
            uuid=target_uuid,
            graph_id=graph_id,
            name=node_name,
            summary=node_summary or "",
            attributes_json=_to_attributes_json(node_attributes),
        )
        return target_uuid

    def _apply_labels(self, session, node_uuid: str, labels: Optional[Sequence[str]]) -> None:
        for label in _normalize_labels(labels):
            session.run(
                f"MATCH (n:{_MARKER_LABEL} {{uuid: $uuid}}) SET n:{_safe_label(label)}",
                uuid=node_uuid,
            )


class _NodeApi:
    def __init__(self, driver):
        self._driver = driver
        self.with_raw_response = SimpleNamespace(get_by_graph_id=self._get_by_graph_id)

    def get(self, uuid_: str, **_ignored) -> SimpleNamespace:
        with self._driver.session() as session:
            record = session.run(
                f"MATCH (n:{_MARKER_LABEL} {{uuid: $uuid}}) "
                "RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, "
                "       n.summary AS summary, n.attributes_json AS attributes_json",
                uuid=uuid_,
            ).single()
        if record is None:
            raise _not_found(f"node {uuid_} not found", {"uuid": uuid_})
        return _node_namespace(record)

    def get_edges(self, node_uuid: str, **_ignored) -> List[SimpleNamespace]:
        """与 Zep Cloud 同口径：仅返回该节点作为 source 的边。"""

        with self._driver.session() as session:
            result = session.run(
                f"MATCH (n:{_MARKER_LABEL} {{uuid: $uuid}})"
                f"-[r:{_EDGE_TYPE}]->(t:{_MARKER_LABEL}) "
                "RETURN r AS edge, n.uuid AS source_uuid, t.uuid AS target_uuid "
                "ORDER BY r.uuid",
                uuid=node_uuid,
            )
            return [
                _edge_namespace(record["edge"], record["source_uuid"], record["target_uuid"])
                for record in result
            ]

    def _get_by_graph_id(self, graph_id: str, *, limit: int = DEFAULT_LOCAL_PAGE_SIZE,
                         cursor: Optional[str] = None, **_ignored) -> _RawResponse:
        # 多取一行做前瞻：只有确认还有后续时才发 zep-next-cursor。
        with self._driver.session() as session:
            records = session.run(
                f"MATCH (n:{_MARKER_LABEL} {{graph_id: $graph_id}}) "
                "WHERE $cursor IS NULL OR n.uuid > $cursor "
                "RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, "
                "       n.summary AS summary, n.attributes_json AS attributes_json "
                "ORDER BY n.uuid LIMIT $page_size",
                graph_id=graph_id,
                cursor=cursor,
                page_size=int(limit) + 1,
            ).data()
        return _build_page(records, int(limit), _node_namespace)


class _EdgeApi:
    def __init__(self, driver):
        self._driver = driver
        self.with_raw_response = SimpleNamespace(get_by_graph_id=self._get_by_graph_id)

    def _get_by_graph_id(self, graph_id: str, *, limit: int = DEFAULT_LOCAL_PAGE_SIZE,
                         cursor: Optional[str] = None, **_ignored) -> _RawResponse:
        # 不用 .data()：它把关系序列化成元组；迭代 Result 拿 Relationship。
        # 与节点分页一致，多取一行做前瞻。
        with self._driver.session() as session:
            result = session.run(
                f"MATCH (s:{_MARKER_LABEL})-[r:{_EDGE_TYPE} {{graph_id: $graph_id}}]"
                f"->(t:{_MARKER_LABEL}) "
                "WHERE $cursor IS NULL OR r.uuid > $cursor "
                "RETURN r AS edge, s.uuid AS source_uuid, t.uuid AS target_uuid "
                "ORDER BY r.uuid LIMIT $page_size",
                graph_id=graph_id,
                cursor=cursor,
                page_size=int(limit) + 1,
            )
            records = [
                {
                    "edge": {
                        "uuid": record["edge"]["uuid"],
                        "name": record["edge"]["name"],
                        "fact": record["edge"]["fact"],
                        "attributes_json": record["edge"]["attributes_json"],
                    },
                    "source_uuid": record["source_uuid"],
                    "target_uuid": record["target_uuid"],
                }
                for record in result
            ]
        return _build_edge_page(records, int(limit))


def _build_page(records: List[dict], page_size: int, mapper) -> _RawResponse:
    has_more = len(records) > page_size
    page = records[:page_size]
    items = [mapper(record) for record in page]
    headers: Dict[str, str] = {}
    if has_more and page:
        headers["zep-next-cursor"] = page[-1]["uuid"]
    return _RawResponse(data=items, headers=headers)


def _build_edge_page(records: List[dict], page_size: int) -> _RawResponse:
    has_more = len(records) > page_size
    page = records[:page_size]
    items = [
        _edge_namespace(record["edge"], record["source_uuid"], record["target_uuid"])
        for record in page
    ]
    headers: Dict[str, str] = {}
    if has_more and page:
        headers["zep-next-cursor"] = page[-1]["edge"]["uuid"]
    return _RawResponse(data=items, headers=headers)
