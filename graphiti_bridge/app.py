from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Flask, jsonify, request
from pydantic import BaseModel, Field

from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.nodes import EpisodeType

app = Flask(__name__)

FALKORDB_HOST = os.environ.get("FALKORDB_HOST", "graphiti-falkordb")
FALKORDB_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.environ.get("MODEL_NAME") or os.environ.get("GRAPHITI_MODEL_NAME", "gpt-5.4-mini")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME") or os.environ.get("GRAPHITI_EMBEDDING_MODEL_NAME", "text-embedding-3-small")

ONTOLOGIES: dict[str, dict[str, Any]] = {}
INDICES_INITIALIZED: set[str] = set()
RESERVED_NAMES = {"uuid", "name", "group_id", "name_embedding", "summary", "created_at"}


def run(coro):
    return asyncio.run(coro)


def safe_attr_name(attr_name: str) -> str:
    if attr_name.lower() in RESERVED_NAMES:
        return f"entity_{attr_name}"
    return attr_name


def build_ontology(ontology: dict[str, Any]) -> dict[str, Any]:
    entity_types: dict[str, type[BaseModel]] = {}
    entity_names: list[str] = []
    for entity_def in ontology.get("entity_types", []):
        name = entity_def["name"]
        description = entity_def.get("description", f"A {name} entity.")
        attrs: dict[str, Any] = {"__doc__": description}
        annotations: dict[str, Any] = {}
        for attr_def in entity_def.get("attributes", []):
            attr_name = safe_attr_name(attr_def["name"])
            attrs[attr_name] = Field(default=None, description=attr_def.get("description", attr_name))
            annotations[attr_name] = Optional[str]
        attrs["__annotations__"] = annotations
        entity_types[name] = type(name, (BaseModel,), attrs)
        entity_names.append(name)

    edge_types: dict[str, type[BaseModel]] = {}
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    for edge_def in ontology.get("edge_types", []):
        name = edge_def["name"]
        description = edge_def.get("description", f"A {name} relationship.")
        edge_types[name] = type(name, (BaseModel,), {"__doc__": description, "__annotations__": {}})
        for st in edge_def.get("source_targets", []):
            source = st.get("source", "Entity")
            target = st.get("target", "Entity")
            edge_type_map.setdefault((source, target), []).append(name)

    if edge_types and not edge_type_map:
        labels = entity_names + ["Entity"]
        edge_names = list(edge_types.keys())
        edge_type_map = {(source, target): edge_names for source in labels for target in labels}

    return {"entity_types": entity_types or None, "edge_types": edge_types or None, "edge_type_map": edge_type_map or None}


async def graphiti(graph_id: str) -> Graphiti:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY/LLM_API_KEY is not configured")
    os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
    os.environ.setdefault("OPENAI_BASE_URL", OPENAI_BASE_URL)
    os.environ.setdefault("MODEL_NAME", MODEL_NAME)
    os.environ.setdefault("EMBEDDING_MODEL_NAME", EMBEDDING_MODEL_NAME)
    driver = FalkorDriver(host=FALKORDB_HOST, port=FALKORDB_PORT, database=graph_id)
    return Graphiti(graph_driver=driver)


async def ensure_indices(graph_id: str) -> None:
    if graph_id in INDICES_INITIALIZED:
        return
    client = await graphiti(graph_id)
    await client.build_indices_and_constraints()
    INDICES_INITIALIZED.add(graph_id)


async def query_graph(graph_id: str, query: str, **params: Any) -> list[dict[str, Any]]:
    driver = FalkorDriver(host=FALKORDB_HOST, port=FALKORDB_PORT, database=graph_id)
    rows, _, _ = await driver.execute_query(query, **params)
    return rows


def edge_from_obj(edge: Any) -> dict[str, Any]:
    return {
        "uuid": getattr(edge, "uuid", "") or getattr(edge, "uuid_", ""),
        "name": getattr(edge, "name", ""),
        "fact": getattr(edge, "fact", ""),
        "source_node_uuid": getattr(edge, "source_node_uuid", ""),
        "target_node_uuid": getattr(edge, "target_node_uuid", ""),
        "attributes": getattr(edge, "attributes", {}) or {},
        "created_at": str(getattr(edge, "created_at", "") or "") or None,
        "valid_at": str(getattr(edge, "valid_at", "") or "") or None,
        "invalid_at": str(getattr(edge, "invalid_at", "") or "") or None,
        "expired_at": str(getattr(edge, "expired_at", "") or "") or None,
    }


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "graphiti-bridge"})


@app.post("/graphs")
def create_graph():
    payload = request.get_json(force=True)
    graph_id = payload["graph_id"]
    run(ensure_indices(graph_id))
    return jsonify({"graph_id": graph_id})


@app.post("/graphs/<graph_id>/ontology")
def set_ontology(graph_id: str):
    ONTOLOGIES[graph_id] = build_ontology(request.get_json(force=True) or {})
    return jsonify({"ok": True})


@app.post("/graphs/<graph_id>/episodes")
def add_episodes(graph_id: str):
    payload = request.get_json(force=True)
    chunks = payload.get("chunks") or [payload.get("text", "")]

    async def add_all():
        await ensure_indices(graph_id)
        client = await graphiti(graph_id)
        ontology = ONTOLOGIES.get(graph_id, {})
        out = []
        for index, chunk in enumerate(chunks, 1):
            result = await client.add_episode(
                name=f"mirofish-chunk-{index}",
                episode_body=chunk,
                source_description="Mirofish text episode",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                group_id=graph_id,
                entity_types=ontology.get("entity_types"),
                edge_types=ontology.get("edge_types"),
                edge_type_map=ontology.get("edge_type_map"),
                custom_extraction_instructions="Extract actors and relationships relevant to the simulation. Prefer provided ontology labels when supported by the text.",
            )
            episode_uuid = getattr(result.episode, "uuid", None) or getattr(result.episode, "uuid_", None)
            out.append({"uuid": episode_uuid, "processed": True})
        return out

    return jsonify({"episodes": run(add_all())})


@app.get("/graphs/<graph_id>/episodes/<episode_uuid>")
def get_episode(graph_id: str, episode_uuid: str):
    return jsonify({"uuid": episode_uuid, "processed": True})


@app.get("/graphs/<graph_id>/nodes")
def get_nodes(graph_id: str):
    rows = run(query_graph(graph_id, """
        MATCH (n:Entity)
        RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.summary AS summary, n.created_at AS created_at
        LIMIT 2000
    """))
    return jsonify({"nodes": rows})


@app.get("/graphs/<graph_id>/edges")
def get_edges(graph_id: str):
    rows = run(query_graph(graph_id, """
        MATCH (a:Entity)-[r]->(b:Entity)
        RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
               a.uuid AS source_node_uuid, b.uuid AS target_node_uuid,
               r.created_at AS created_at, r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.expired_at AS expired_at
        LIMIT 5000
    """))
    return jsonify({"edges": rows})


@app.get("/nodes/<node_uuid>")
def get_node(node_uuid: str):
    graph_id = request.args.get("graph_id")
    if not graph_id:
        return jsonify({"node": None})
    rows = run(query_graph(graph_id, """
        MATCH (n:Entity {uuid: $uuid})
        RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.summary AS summary, n.created_at AS created_at
        LIMIT 1
    """, uuid=node_uuid))
    return jsonify({"node": rows[0] if rows else None})


@app.get("/nodes/<node_uuid>/edges")
def get_node_edges(node_uuid: str):
    graph_id = request.args.get("graph_id")
    if not graph_id:
        return jsonify({"edges": []})
    rows = run(query_graph(graph_id, """
        MATCH (a:Entity)-[r]->(b:Entity)
        WHERE a.uuid = $uuid OR b.uuid = $uuid
        RETURN r.uuid AS uuid, type(r) AS name, r.fact AS fact,
               a.uuid AS source_node_uuid, b.uuid AS target_node_uuid,
               r.created_at AS created_at, r.valid_at AS valid_at, r.invalid_at AS invalid_at, r.expired_at AS expired_at
        LIMIT 5000
    """, uuid=node_uuid))
    return jsonify({"edges": rows})


@app.post("/graphs/<graph_id>/search")
def search(graph_id: str):
    payload = request.get_json(force=True)
    query = payload.get("query", "")
    limit = int(payload.get("limit", 10))
    scope = payload.get("scope", "edges")

    async def do_search():
        client = await graphiti(graph_id)
        edges = [] if scope == "nodes" else [edge_from_obj(edge) for edge in await client.search(query=query, group_ids=[graph_id], num_results=limit)]
        nodes = []
        if scope in {"nodes", "both"}:
            terms = [term.lower() for term in query.split() if len(term) > 1]
            rows = await query_graph(graph_id, """
                MATCH (n:Entity)
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.summary AS summary, n.created_at AS created_at
                LIMIT 2000
            """)
            scored = []
            for row in rows:
                text = f"{row.get('name', '')} {row.get('summary', '')}".lower()
                score = sum(1 for term in terms if term in text)
                if query.lower() in text:
                    score += 10
                if score:
                    scored.append((score, row))
            scored.sort(key=lambda item: item[0], reverse=True)
            nodes = [row for _, row in scored[:limit]]
        return {"edges": edges, "nodes": nodes}

    return jsonify(run(do_search()))


@app.delete("/graphs/<graph_id>")
def delete_graph(graph_id: str):
    run(query_graph(graph_id, "MATCH (n) DETACH DELETE n"))
    ONTOLOGIES.pop(graph_id, None)
    INDICES_INITIALIZED.discard(graph_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8008")))
