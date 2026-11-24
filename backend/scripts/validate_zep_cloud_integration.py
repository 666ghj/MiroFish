#!/usr/bin/env python3
"""Run a manual, real Zep Cloud validation against a retained test graph.

This script is intentionally excluded from the automated test suite. It requires
``ZEP_API_KEY`` at runtime, never prints the key, and deletes the graph unless
``--keep-graph`` is explicitly supplied. If the activity updater cannot be
confirmed drained after a failure, the graph is retained to avoid a write/delete
race.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

# Capture the caller-supplied key before importing MiroFish modules. app.config
# deliberately loads the repository .env with override=True, which must not
# silently replace the account selected for this explicit validation process.
_PROCESS_ZEP_API_KEY = os.environ.get("ZEP_API_KEY", "").strip()

from zep_cloud import BatchAddItem
from zep_cloud.types import SearchFilters

from app.services.graph_builder import BatchSubmission, GraphBuilderService
from app.services.zep_entity_reader import ZepEntityReader
from app.services.zep_graph_memory_updater import AgentActivity, ZepGraphMemoryUpdater
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

# Keep later code that consults os.environ consistent with the captured value.
# All Cloud clients in this script also receive the key explicitly.
if _PROCESS_ZEP_API_KEY:
    os.environ["ZEP_API_KEY"] = _PROCESS_ZEP_API_KEY


@dataclass(frozen=True)
class SourceEpisode:
    created_at: str
    data: str
    phase: str
    data_type: str = "text"


BASELINE_EPISODES = [
    SourceEpisode(
        "2026-01-05T09:00:00Z",
        "澜舟科技（企业稳定标识 LZ-TECH）是一家风电智能运维公司。"
        "公司总部位于星港市，周岚自 2024 年起担任首席执行官（CEO）。",
        "baseline",
    ),
    SourceEpisode(
        "2026-01-12T10:00:00Z",
        "澜舟科技研发了产品智巡平台（产品稳定标识 ZHIXUN-01）。"
        "智巡平台当前处于试点阶段，用于识别风机叶片异常。",
        "baseline",
    ),
    SourceEpisode(
        "2026-01-20T14:00:00Z",
        "澜舟科技与海岳能源（企业稳定标识 HY-ENERGY）签署 HY-2026-01 合作协议。"
        "双方将在东湾风场联合部署智巡平台，协议有效期至 2026 年 12 月 31 日。",
        "baseline",
    ),
    SourceEpisode(
        "2026-02-02T09:30:00Z",
        "陈屿担任澜舟科技智巡平台的项目负责人，负责东湾风场部署。"
        "公司经营仍由首席执行官周岚负责。",
        "baseline",
    ),
    SourceEpisode(
        "2026-02-20T18:00:00Z",
        "东湾风场的智巡平台试点发现了 12 处叶片异常，"
        "使海岳能源的非计划停机时间降低了 18%。",
        "baseline",
    ),
    SourceEpisode(
        "2026-03-05T11:00:00Z",
        "海岳能源确认澜舟科技是智巡平台的开发方，陈屿是实施项目负责人。"
        "海岳能源计划在试点验收后成为首批商业客户。",
        "baseline",
    ),
    SourceEpisode(
        "2026-03-15T16:00:00Z",
        "澜舟科技董事会批准智巡平台在 2026 年 4 月 1 日从试点阶段转为商业发布。"
        "周岚以首席执行官身份签署了发布决议。",
        "baseline",
    ),
    SourceEpisode(
        "2026-04-01T08:00:00Z",
        "智巡平台今天正式商业发布，不再处于试点阶段。"
        "海岳能源成为智巡平台首个商业客户，陈屿继续负责交付。",
        "baseline",
    ),
    SourceEpisode(
        "2026-04-18T13:00:00Z",
        "澜舟科技在星港市总部公布运营数据：智巡平台已覆盖 60 台风机，"
        "海岳能源仍是 HY-2026-01 协议下的合作伙伴和客户。",
        "baseline",
    ),
    SourceEpisode(
        "2026-04-30T17:00:00Z",
        "截至 2026 年 4 月 30 日，周岚仍担任澜舟科技首席执行官，"
        "澜舟科技总部仍在星港市；陈屿担任智巡平台项目负责人。",
        "baseline",
    ),
]


TEMPORAL_UPDATES = [
    SourceEpisode(
        "2026-05-10T09:00:00Z",
        "澜舟科技董事会宣布，自 2026 年 5 月 10 日起，周岚不再担任首席执行官。"
        "陈屿正式接任澜舟科技首席执行官，周岚转任首席战略顾问。",
        "leadership_change",
    ),
    SourceEpisode(
        "2026-06-01T09:00:00Z",
        "自 2026 年 6 月 1 日起，澜舟科技总部已从星港市迁至海城市。"
        "星港市原总部不再是公司总部，现改为澜舟科技研发中心。",
        "headquarters_change",
    ),
    SourceEpisode(
        "2026-06-15T12:00:00Z",
        "澜舟科技与海岳能源已于 2026 年 6 月 15 日提前终止 HY-2026-01 联合部署协议。"
        "海岳能源不再是澜舟科技的联合部署合作伙伴，但仍是智巡平台客户。",
        "partnership_change",
    ),
    SourceEpisode(
        "2026-06-20T18:00:00Z",
        json.dumps(
            {
                "event": "product_metrics_update",
                "company_id": "LZ-TECH",
                "product_id": "ZHIXUN-01",
                "product_name": "智巡平台",
                "commercial_status": "commercial",
                "covered_turbines": 120,
                "active_customer": "海岳能源",
                "as_of": "2026-06-20",
            },
            ensure_ascii=False,
        ),
        "json_update",
        "json",
    ),
]


ONTOLOGY = {
    "entity_types": [
        {
            "name": "Person",
            "description": "A named person involved in company governance or delivery.",
            "attributes": [{"name": "current_role", "description": "The person's current role."}],
        },
        {
            "name": "Company",
            "description": "A company or commercial organization.",
            "attributes": [{"name": "stable_id", "description": "A stable company identifier."}],
        },
        {
            "name": "Product",
            "description": "A named software or industrial product.",
            "attributes": [{"name": "lifecycle_stage", "description": "The product lifecycle stage."}],
        },
        {
            "name": "Place",
            "description": "A city, office, wind farm, or other named location.",
            "attributes": [{"name": "place_kind", "description": "The kind of place."}],
        },
        {
            "name": "Agreement",
            "description": "A named commercial agreement or contract.",
            "attributes": [{"name": "agreement_status", "description": "The agreement status."}],
        },
    ],
    "edge_types": [
        {
            "name": "HOLDS_ROLE_AT",
            "description": "A person holds a named role at a company.",
            "attributes": [{"name": "title", "description": "The person's title."}],
            "source_targets": [{"source": "Person", "target": "Company"}],
        },
        {
            "name": "DEVELOPS",
            "description": "A company develops a product.",
            "attributes": [{"name": "product_status", "description": "The product status."}],
            "source_targets": [{"source": "Company", "target": "Product"}],
        },
        {
            "name": "HEADQUARTERED_IN",
            "description": "A company has its current headquarters in a place.",
            "attributes": [{"name": "site_status", "description": "The site's headquarters status."}],
            "source_targets": [{"source": "Company", "target": "Place"}],
        },
        {
            "name": "PARTNERS_WITH",
            "description": "A company has a commercial partnership with another company.",
            "attributes": [{"name": "agreement_id", "description": "The governing agreement identifier."}],
            "source_targets": [{"source": "Company", "target": "Company"}],
        },
        {
            "name": "CUSTOMER_OF",
            "description": "A company is a customer of a product's developer.",
            "attributes": [{"name": "customer_status", "description": "The customer status."}],
            "source_targets": [{"source": "Company", "target": "Company"}],
        },
    ],
}


def _uuid(value: Any) -> str:
    return str(getattr(value, "uuid_", None) or getattr(value, "uuid", ""))


def _status_code(error: Exception) -> int | None:
    direct = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    return direct or getattr(response, "status_code", None)


def _require_process_api_key() -> str:
    if not _PROCESS_ZEP_API_KEY:
        raise RuntimeError(
            "ZEP_API_KEY must be supplied through the process environment"
        )
    return _PROCESS_ZEP_API_KEY


def _drain_updater_after_failure(
    updater: Any,
    *,
    started: bool,
    stop_attempted: bool,
) -> tuple[bool, Exception | None]:
    """Make one safe drain attempt when the main flow did not call stop()."""

    if not started:
        return True, None
    if stop_attempted:
        return False, None
    try:
        updater.stop()
    except Exception as error:
        return False, error
    return True, None


def _cleanup_graph(
    client: Any,
    graph_id: str,
    *,
    created: bool,
    keep_graph: bool,
    updater_started: bool,
    updater_drained: bool,
) -> dict[str, Any]:
    """Delete only when no updater can still write to or ingest into the graph."""

    if not created:
        return {
            "graph_deleted": False,
            "graph_retained": False,
            "reason": "graph_not_created",
        }
    if keep_graph:
        return {
            "graph_deleted": False,
            "graph_retained": True,
            "reason": "user_requested",
        }
    if updater_started and not updater_drained:
        return {
            "graph_deleted": False,
            "graph_retained": True,
            "reason": "updater_not_confirmed_drained",
        }

    client.graph.delete(graph_id)
    return {
        "graph_deleted": True,
        "graph_retained": False,
        "reason": "validation_cleanup",
    }


def _wait_for_episode(client: Any, episode_uuid: str, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        episode = client.graph.episode.get(uuid_=episode_uuid)
        if getattr(episode, "processed", False):
            return episode
        time.sleep(3)
    raise TimeoutError(f"episode {episode_uuid} did not finish within {timeout}s")


def _list_batch_items(client: Any, batch_id: str, page_size: int = 3) -> tuple[list[Any], int]:
    items: list[Any] = []
    cursor: int | None = None
    pages = 0
    while True:
        response = client.batch.list_items(batch_id=batch_id, limit=page_size, cursor=cursor)
        pages += 1
        items.extend(response.items or [])
        next_cursor = response.next_cursor
        if next_cursor is None:
            return items, pages
        if next_cursor == cursor:
            raise RuntimeError("batch item cursor did not advance")
        cursor = next_cursor


def _raw_pages(api_call: Any, graph_id: str, page_size: int = 2) -> tuple[list[Any], int]:
    items: list[Any] = []
    cursor: str | None = None
    pages = 0
    seen: set[str] = set()
    while True:
        kwargs: dict[str, Any] = {"limit": page_size}
        if cursor:
            kwargs["cursor"] = cursor
        response = api_call(graph_id, **kwargs)
        pages += 1
        items.extend(list(response.data or []))
        next_cursor = response.headers.get("zep-next-cursor")
        if not next_cursor:
            return items, pages
        if next_cursor == cursor or next_cursor in seen:
            raise RuntimeError("artifact cursor did not advance")
        seen.add(next_cursor)
        cursor = next_cursor


def _edge_view(edge: Any, node_names: dict[str, str]) -> dict[str, Any]:
    return {
        "uuid": _uuid(edge),
        "name": edge.name,
        "fact": edge.fact,
        "source": node_names.get(edge.source_node_uuid, edge.source_node_uuid),
        "target": node_names.get(edge.target_node_uuid, edge.target_node_uuid),
        "created_at": edge.created_at,
        "valid_at": edge.valid_at,
        "invalid_at": edge.invalid_at,
        "expired_at": edge.expired_at,
        "attributes": edge.attributes or {},
    }


def _node_view(node: Any) -> dict[str, Any]:
    return {
        "uuid": _uuid(node),
        "name": node.name,
        "labels": node.labels or [],
        "summary": node.summary,
        "attributes": node.attributes or {},
    }


def _search_view(results: Any, node_names: dict[str, str]) -> dict[str, Any]:
    return {
        "context": (results.context or "")[:3000],
        "edges": [_edge_view(edge, node_names) for edge in (results.edges or [])],
        "nodes": [_node_view(node) for node in (results.nodes or [])],
        "episode_count": len(results.episodes or []),
        "observation_count": len(results.observations or []),
        "thread_summary_count": len(results.thread_summaries or []),
    }


def _episode_to_batch_item(graph_id: str, item: SourceEpisode, index: int) -> BatchAddItem:
    return BatchAddItem(
        type="graph_episode",
        graph_id=graph_id,
        data=item.data,
        data_type=item.data_type,
        created_at=item.created_at,
        source_description="MiroFish deep Zep Cloud validation corpus",
        metadata={
            "source": "mirofish_zep_deep_validation",
            "phase": item.phase,
            "sequence": index,
        },
    )


def _add_and_wait(client: Any, graph_id: str, item: SourceEpisode, timeout: int) -> str:
    episode = client.graph.add(
        graph_id=graph_id,
        type=item.data_type,
        data=item.data,
        created_at=item.created_at,
        source_description="MiroFish temporal Zep Cloud validation update",
        metadata={"source": "mirofish_zep_deep_validation", "phase": item.phase},
    )
    episode_uuid = _uuid(episode)
    if not episode_uuid:
        raise RuntimeError("graph.add returned no episode UUID")
    _wait_for_episode(client, episode_uuid, timeout)
    return episode_uuid


def _activities() -> Iterable[AgentActivity]:
    return [
        AgentActivity(
            platform="twitter",
            agent_id=101,
            agent_name="陈屿",
            action_type="CREATE_POST",
            action_args={"content": "海城市新总部今天启用，智巡平台商业服务正常运行。"},
            round_num=1,
            timestamp="2026-07-01T09:00:00Z",
        ),
        AgentActivity(
            platform="twitter",
            agent_id=102,
            agent_name="周岚",
            action_type="QUOTE_POST",
            action_args={
                "original_author_name": "陈屿",
                "original_content": "海城市新总部今天启用，智巡平台商业服务正常运行。",
                "quote_content": "作为首席战略顾问，我支持陈屿和新的管理团队。",
            },
            round_num=1,
            timestamp="2026-07-01T09:05:00Z",
        ),
        AgentActivity(
            platform="twitter",
            agent_id=201,
            agent_name="海岳能源",
            action_type="LIKE_POST",
            action_args={
                "post_author_name": "陈屿",
                "post_content": "海城市新总部今天启用，智巡平台商业服务正常运行。",
            },
            round_num=1,
            timestamp="2026-07-01T09:06:00Z",
        ),
        AgentActivity(
            platform="twitter",
            agent_id=201,
            agent_name="海岳能源",
            action_type="CREATE_COMMENT",
            action_args={
                "post_author_name": "陈屿",
                "post_content": "海城市新总部今天启用，智巡平台商业服务正常运行。",
                "content": "联合部署协议虽已终止，但我们仍是智巡平台客户。",
            },
            round_num=2,
            timestamp="2026-07-01T09:10:00Z",
        ),
        AgentActivity(
            platform="twitter",
            agent_id=101,
            agent_name="陈屿",
            action_type="FOLLOW",
            action_args={"target_user_name": "海岳能源"},
            round_num=2,
            timestamp="2026-07-01T09:12:00Z",
        ),
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = _require_process_api_key()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    graph_id = args.graph_id or f"mirofish_zep_deep_{stamp}"
    builder = GraphBuilderService(api_key=api_key)
    client = builder.client
    created = False
    updater: ZepGraphMemoryUpdater | None = None
    updater_started = False
    updater_stop_attempted = False
    updater_drained = False
    result: dict[str, Any] = {
        "graph_id": graph_id,
        "graph_retained": args.keep_graph,
        "sdk_flow": "zep-cloud 3.25 standalone graph + current Batch API",
    }

    print(f"[zep-deep] graph_id={graph_id}", flush=True)
    try:
        builder.create_graph("MiroFish Zep Cloud Deep Validation", graph_id=graph_id)
        created = True
        print("[zep-deep] graph created", flush=True)

        # Production safety net: empty LLM attributes must become a valid
        # fallback property before reaching Zep Cloud.
        ontology_probe = {"entity_types": [{"name": "ProbeEntity", "attributes": []}], "edge_types": []}
        try:
            builder.set_ontology(graph_id, ontology_probe)
            result["empty_attribute_ontology_probe"] = "accepted_after_mirofish_normalization"
        except Exception as error:
            result["empty_attribute_ontology_probe"] = {
                "error_type": type(error).__name__,
                "status_code": _status_code(error),
            }
            raise

        builder.set_ontology(graph_id, ONTOLOGY)
        print("[zep-deep] ontology set", flush=True)

        operation_id = f"deep-validation-{stamp}"
        batch = client.batch.create(
            metadata={
                "mirofish_operation_id": operation_id,
                "graph_id": graph_id,
                "suite": "zep_deep_validation",
            }
        )
        batch_id = batch.batch_id
        if not batch_id:
            raise RuntimeError("batch.create returned no batch_id")
        result["batch_id"] = batch_id

        added_details: list[Any] = []
        batch_items = [
            _episode_to_batch_item(graph_id, item, index)
            for index, item in enumerate(BASELINE_EPISODES)
        ]
        for start in range(0, len(batch_items), 4):
            added_details.extend(
                client.batch.add(batch_id=batch_id, items=batch_items[start : start + 4])
            )
        client.batch.process(batch_id=batch_id)
        print(f"[zep-deep] batch submitted items={len(batch_items)}", flush=True)

        submission = BatchSubmission(
            batch_id=batch_id,
            operation_id=operation_id,
            episode_uuids=[_uuid(item) for item in added_details if _uuid(item)],
            item_count=len(batch_items),
        )
        baseline_episode_uuids = builder._wait_for_batch(submission, timeout=args.timeout)
        listed_items, batch_pages = _list_batch_items(client, batch_id, page_size=3)
        result["batch"] = {
            "status": client.batch.get(batch_id=batch_id).status,
            "item_count": len(listed_items),
            "item_pages_at_size_3": batch_pages,
            "episode_uuids": baseline_episode_uuids,
        }
        print(f"[zep-deep] batch completed pages={batch_pages}", flush=True)

        baseline_nodes = fetch_all_nodes(client, graph_id, page_size=2)
        baseline_edges = fetch_all_edges(client, graph_id, page_size=2)
        raw_nodes, node_pages = _raw_pages(
            client.graph.node.with_raw_response.get_by_graph_id, graph_id, page_size=2
        )
        raw_edges, edge_pages = _raw_pages(
            client.graph.edge.with_raw_response.get_by_graph_id, graph_id, page_size=2
        )
        if {_uuid(item) for item in baseline_nodes} != {_uuid(item) for item in raw_nodes}:
            raise AssertionError("production node pagination did not match raw cursor traversal")
        if {_uuid(item) for item in baseline_edges} != {_uuid(item) for item in raw_edges}:
            raise AssertionError("production edge pagination did not match raw cursor traversal")
        if len(baseline_nodes) <= 2 or len(baseline_edges) <= 2:
            raise AssertionError("the corpus did not produce enough artifacts to exercise pagination")

        baseline_names = {_uuid(node): node.name for node in baseline_nodes}
        baseline_ceo = client.graph.search(
            graph_id=graph_id,
            query="截至2026年4月底，谁担任澜舟科技首席执行官？",
            scope="edges",
            reranker="cross_encoder",
            limit=10,
        )
        result["baseline"] = {
            "node_count": len(baseline_nodes),
            "edge_count": len(baseline_edges),
            "node_pages_at_size_2": node_pages,
            "edge_pages_at_size_2": edge_pages,
            "invalidated_edge_count": sum(bool(edge.invalid_at) for edge in baseline_edges),
            "ceo_search": _search_view(baseline_ceo, baseline_names),
        }
        print(
            f"[zep-deep] baseline nodes={len(baseline_nodes)} edges={len(baseline_edges)}",
            flush=True,
        )

        update_episode_uuids = [
            _add_and_wait(client, graph_id, item, args.timeout)
            for item in TEMPORAL_UPDATES
        ]
        result["temporal_update_episode_uuids"] = update_episode_uuids
        print(f"[zep-deep] temporal updates processed={len(update_episode_uuids)}", flush=True)

        updater = ZepGraphMemoryUpdater(
            graph_id=graph_id,
            api_key=api_key,
            simulation_id=f"zep-deep-{stamp}",
        )
        updater_started = True
        updater.start()
        for activity in _activities():
            updater.add_activity(activity)
        updater_stop_attempted = True
        updater.stop()
        updater_drained = True
        updater_stats = updater.get_stats()
        if updater_stats["items_sent"] != 5 or updater_stats["pending_episode_count"] != 0:
            raise AssertionError(f"unexpected MiroFish updater stats: {updater_stats}")
        result["mirofish_updater"] = updater_stats
        print("[zep-deep] MiroFish updater processed 5 mock activities", flush=True)

        final_nodes = fetch_all_nodes(client, graph_id, page_size=2)
        final_edges = fetch_all_edges(client, graph_id, page_size=2)
        final_names = {_uuid(node): node.name for node in final_nodes}
        invalidated = [edge for edge in final_edges if edge.invalid_at]
        expired = [edge for edge in final_edges if edge.expired_at]

        edge_search = client.graph.search(
            graph_id=graph_id,
            query="澜舟科技当前首席执行官、当前总部以及与海岳能源的当前合作关系是什么？",
            scope="edges",
            reranker="cross_encoder",
            limit=20,
        )
        node_search = client.graph.search(
            graph_id=graph_id,
            query="澜舟科技管理层人物",
            scope="nodes",
            reranker="rrf",
            limit=10,
            search_filters=SearchFilters(node_labels=["Person"]),
        )
        typed_edge_search = client.graph.search(
            graph_id=graph_id,
            query="公司管理职位发生了什么变化？",
            scope="edges",
            reranker="rrf",
            limit=10,
            search_filters=SearchFilters(edge_types=["HOLDS_ROLE_AT"]),
        )
        auto_search = client.graph.search(
            graph_id=graph_id,
            query="总结澜舟科技最新的管理层、总部、产品与海岳能源关系。",
            scope="auto",
            max_characters=3000,
            return_raw_results=True,
        )
        episode_search = client.graph.search(
            graph_id=graph_id,
            query="海岳能源为什么仍是客户但不再是联合部署伙伴？",
            scope="episodes",
            reranker="rrf",
            limit=10,
        )

        selected_node = next(
            (
                node
                for node in final_nodes
                if node.name == "澜舟科技" and "Company" in (node.labels or [])
            ),
            max(
                final_nodes,
                key=lambda node: sum(
                    edge.source_node_uuid == _uuid(node)
                    or edge.target_node_uuid == _uuid(node)
                    for edge in final_edges
                ),
            ),
        )
        sdk_node_edges = client.graph.node.get_edges(node_uuid=_uuid(selected_node))
        complete_node_edges = [
            edge
            for edge in final_edges
            if edge.source_node_uuid == _uuid(selected_node)
            or edge.target_node_uuid == _uuid(selected_node)
        ]
        entity_context = ZepEntityReader(api_key=api_key).get_entity_with_context(
            graph_id,
            _uuid(selected_node),
        )
        recent_episodes = client.graph.episode.get_by_graph_id(graph_id=graph_id, lastn=50)
        episode_list = getattr(recent_episodes, "episodes", None) or []

        custom_labels = sorted(
            {label for node in final_nodes for label in (node.labels or []) if label != "Entity"}
        )
        custom_edge_names = sorted(
            {edge.name for edge in final_edges if edge.name in {item["name"] for item in ONTOLOGY["edge_types"]}}
        )
        result["final"] = {
            "node_count": len(final_nodes),
            "edge_count": len(final_edges),
            "invalidated_edge_count": len(invalidated),
            "expired_edge_count": len(expired),
            "custom_labels": custom_labels,
            "custom_edge_names": custom_edge_names,
            "nodes": [_node_view(node) for node in final_nodes],
            "invalidated_facts": [_edge_view(edge, final_names) for edge in invalidated],
            "active_facts": [
                _edge_view(edge, final_names)
                for edge in final_edges
                if not edge.invalid_at and not edge.expired_at
            ],
            "selected_node": _node_view(selected_node),
            "sdk_node_edge_count": len(sdk_node_edges),
            "complete_node_edge_count": len(complete_node_edges),
            "entity_reader_context_edge_count": len(entity_context.related_edges),
            "recent_episode_count": len(episode_list),
        }
        result["searches"] = {
            "current_state_edges": _search_view(edge_search, final_names),
            "person_nodes": _search_view(node_search, final_names),
            "typed_role_edges": _search_view(typed_edge_search, final_names),
            "auto_context": _search_view(auto_search, final_names),
            "partnership_episodes": _search_view(episode_search, final_names),
        }

        if len(entity_context.related_edges) != len(complete_node_edges):
            raise AssertionError(
                "MiroFish entity context omitted incoming or outgoing node edges"
            )

        result["runtime_assertions"] = {
            "edge_search_call_completed": edge_search is not None,
            "node_search_call_completed": node_search is not None,
            "typed_edge_search_call_completed": typed_edge_search is not None,
            "auto_search_call_completed": auto_search is not None,
            "episode_search_call_completed": episode_search is not None,
            "node_detail_has_all_incoming_and_outgoing_edges": True,
            "sdk_node_endpoint_omits_incoming_edges": (
                len(sdk_node_edges) < len(complete_node_edges)
            ),
            # The following values are observations only. Zep's extraction and
            # retrieval quality are not runtime acceptance criteria.
            "search_result_counts": {
                "edges": len(edge_search.edges or []),
                "nodes": len(node_search.nodes or []),
                "typed_edges": len(typed_edge_search.edges or []),
                "episodes": len(episode_search.episodes or []),
            },
            "custom_entity_labels_observed": bool(custom_labels),
            "custom_edge_names_observed": bool(custom_edge_names),
            "temporal_invalidation_observed": bool(invalidated),
        }
        return result
    except Exception as error:
        result["failure"] = {
            "type": type(error).__name__,
            "status_code": _status_code(error),
            "message": str(error)[:500],
        }
        raise
    finally:
        if updater is not None and updater_started and not updater_stop_attempted:
            updater_stop_attempted = True
            updater_drained, updater_cleanup_error = _drain_updater_after_failure(
                updater,
                started=updater_started,
                stop_attempted=False,
            )
            if updater_cleanup_error is not None:
                result["updater_cleanup_error"] = {
                    "type": type(updater_cleanup_error).__name__,
                    "message": str(updater_cleanup_error)[:500],
                }
                print(
                    "[zep-deep] updater drain failed; graph will be retained "
                    f"type={type(updater_cleanup_error).__name__}",
                    flush=True,
                )

        had_primary_failure = "failure" in result
        try:
            cleanup = _cleanup_graph(
                client,
                graph_id,
                created=created,
                keep_graph=args.keep_graph,
                updater_started=updater_started,
                updater_drained=updater_drained,
            )
        except Exception as cleanup_error:
            result["cleanup"] = {
                "graph_deleted": False,
                "graph_retained": True,
                "reason": "graph_delete_failed",
                "error_type": type(cleanup_error).__name__,
                "status_code": _status_code(cleanup_error),
            }
            result["graph_retained"] = True
            print(
                "[zep-deep] graph cleanup failed; graph retained "
                f"graph_id={graph_id} type={type(cleanup_error).__name__}",
                flush=True,
            )
            if not had_primary_failure:
                result["failure"] = {
                    "type": type(cleanup_error).__name__,
                    "status_code": _status_code(cleanup_error),
                    "message": str(cleanup_error)[:500],
                }
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                raise
        else:
            result["cleanup"] = cleanup
            result["graph_retained"] = cleanup["graph_retained"]
            if cleanup["graph_deleted"]:
                action = "deleted"
            elif cleanup["graph_retained"]:
                action = "retained"
            else:
                action = "not-created"
            print(
                f"[zep-deep] graph {action} graph_id={graph_id} "
                f"reason={cleanup['reason']}",
                flush=True,
            )

        if had_primary_failure:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep terminal output focused on runtime/API-contract evidence."""

    baseline = result.get("baseline", {})
    final = result.get("final", {})
    return {
        "graph_id": result.get("graph_id"),
        "graph_retained": result.get("graph_retained"),
        "cleanup": result.get("cleanup"),
        "sdk_flow": result.get("sdk_flow"),
        "empty_attribute_ontology_probe": result.get(
            "empty_attribute_ontology_probe"
        ),
        "batch_id": result.get("batch_id"),
        "batch": result.get("batch"),
        "baseline": {
            key: baseline.get(key)
            for key in (
                "node_count",
                "edge_count",
                "node_pages_at_size_2",
                "edge_pages_at_size_2",
                "invalidated_edge_count",
            )
        },
        "temporal_update_episode_count": len(
            result.get("temporal_update_episode_uuids", [])
        ),
        "mirofish_updater": result.get("mirofish_updater"),
        "final": {
            key: final.get(key)
            for key in (
                "node_count",
                "edge_count",
                "invalidated_edge_count",
                "expired_edge_count",
                "custom_labels",
                "custom_edge_names",
                "sdk_node_edge_count",
                "complete_node_edge_count",
                "entity_reader_context_edge_count",
                "recent_episode_count",
            )
        },
        "runtime_assertions": result.get("runtime_assertions"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-id", help="Use an explicit standalone graph ID")
    parser.add_argument(
        "--keep-graph",
        action="store_true",
        help="Retain the graph for manual inspection after validation",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Maximum seconds to wait for each ingestion stage",
    )
    parser.add_argument(
        "--full-output",
        action="store_true",
        help="Print every node, edge, and search result instead of a runtime summary",
    )
    args = parser.parse_args()

    try:
        result = run(args)
    except Exception as error:
        print(
            f"[zep-deep] FAILED type={type(error).__name__} status={_status_code(error)}",
            file=sys.stderr,
        )
        return 1
    output = result if args.full_output else _compact_result(result)
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
