#!/usr/bin/env python3
"""
Service-level Graphiti smoke test for MiroFish.

The script creates a temporary graph, applies a small ontology, ingests a few
text chunks through GraphBuilderService, then queries through ZepToolsService.
It prints JSON output and deletes the graph by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

DEFAULT_CHUNKS = [
    "Alice works at Acme Robotics. Bob manages Alice.",
    "Acme Robotics is located in Tokyo. Alice relocated to Tokyo for work.",
]


def load_env_file(path: Path) -> None:
    """Load a simple .env file without overriding existing variables."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def prepare_environment() -> None:
    """Apply repo-local defaults that make Graphiti smoke testing predictable."""
    load_env_file(REPO_ROOT / ".env")
    load_env_file(BACKEND_ROOT / ".env")

    os.environ.setdefault("GRAPH_BACKEND", "graphiti")
    os.environ.setdefault("GRAPHITI_URI", "bolt://127.0.0.1:7687")
    os.environ.setdefault("GRAPHITI_USER", "neo4j")
    os.environ.setdefault("GRAPHITI_PASSWORD", "password123")
    os.environ.setdefault("GRAPHITI_DATABASE", "neo4j")
    os.environ.setdefault("GRAPHITI_LLM_BASE_URL", os.environ.get("LLM_BASE_URL", "http://127.0.0.1:18081/v1"))
    os.environ.setdefault("GRAPHITI_LLM_MODEL", os.environ.get("LLM_MODEL_NAME", "gpt-5.4"))
    os.environ.setdefault("GRAPHITI_LLM_CLIENT_MODE", "openai")
    os.environ.setdefault("GRAPH_SEARCH_RERANKER", "rrf")
    os.environ.setdefault("GRAPHITI_EMBEDDER_API_KEY", "ollama")
    os.environ.setdefault("GRAPHITI_EMBEDDER_BASE_URL", "http://127.0.0.1:11434/v1")
    os.environ.setdefault("GRAPHITI_EMBEDDER_MODEL", "qwen3-embedding:8b")
    os.environ.setdefault("GRAPHITI_EMBEDDER_DIM", "1024")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Graphiti service-level smoke test.")
    parser.add_argument(
        "--query",
        default="Where does Alice work?",
        help="Search query executed through ZepToolsService.",
    )
    parser.add_argument(
        "--chunk",
        action="append",
        dest="chunks",
        help="Text chunk to ingest. Repeat to add multiple chunks.",
    )
    parser.add_argument(
        "--graph-name",
        default="graphiti smoke test",
        help="Temporary graph name.",
    )
    parser.add_argument(
        "--keep-graph",
        action="store_true",
        help="Keep the temporary graph instead of deleting it on exit.",
    )
    return parser.parse_args(list(argv))


def build_sample_ontology() -> dict:
    return {
        "entity_types": [
            {"name": "Person", "description": "A human individual.", "attributes": []},
            {"name": "Organization", "description": "A company or institution.", "attributes": []},
            {"name": "Location", "description": "A place or city.", "attributes": []},
        ],
        "edge_types": [
            {
                "name": "WORKS_AT",
                "description": "A person works at an organization.",
                "attributes": [],
                "source_targets": [{"source": "Person", "target": "Organization"}],
            },
            {
                "name": "MANAGES",
                "description": "A person manages another person.",
                "attributes": [],
                "source_targets": [{"source": "Person", "target": "Person"}],
            },
            {
                "name": "LOCATED_IN",
                "description": "An organization is located in a place.",
                "attributes": [],
                "source_targets": [{"source": "Organization", "target": "Location"}],
            },
        ],
    }


def main(argv: Iterable[str]) -> int:
    prepare_environment()
    sys.path.insert(0, str(BACKEND_ROOT))

    from app.config import Config

    search_embedder = Config.get_graph_search_embedder_config()
    search_reranker = Config.get_graph_search_reranker_config()
    errors = Config.get_graph_backend_config_errors(api_key=Config.ZEP_API_KEY)
    if errors:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Graph backend config is incomplete.",
                    "backend": Config.GRAPH_BACKEND,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    from app.services.graph_builder import GraphBuilderService
    from app.services.zep_tools import ZepToolsService

    args = parse_args(argv)
    chunks = args.chunks or list(DEFAULT_CHUNKS)

    builder = GraphBuilderService()
    tools = ZepToolsService()
    graph_id = builder.create_graph(f"{args.graph_name}-{uuid.uuid4().hex[:8]}")

    try:
        builder.set_ontology(graph_id, build_sample_ontology())
        builder.add_text_batches(graph_id, chunks, batch_size=1)

        result = tools.search_graph(
            graph_id=graph_id,
            query=args.query,
            limit=5,
            scope="edges",
        )
        stats = tools.get_graph_statistics(graph_id)

        output = {
            "success": True,
            "graph_id": graph_id,
            "kept_graph": args.keep_graph,
            "backend": Config.GRAPH_BACKEND,
            "llm_base_url": Config.GRAPHITI_LLM_BASE_URL or Config.LLM_BASE_URL,
            "llm_model": Config.GRAPHITI_LLM_MODEL or Config.LLM_MODEL_NAME,
            "embedder_base_url": Config.GRAPHITI_EMBEDDER_BASE_URL,
            "embedder_model": Config.GRAPHITI_EMBEDDER_MODEL,
            "app_reranker": Config.GRAPH_SEARCH_APP_RERANKER,
            "app_embedder_base_url": search_embedder.get("base_url"),
            "app_embedder_model": search_embedder.get("model"),
            "app_reranker_base_url": search_reranker.get("base_url"),
            "app_reranker_model": search_reranker.get("model"),
            "app_reranker_provider": search_reranker.get("provider"),
            "query": args.query,
            "chunks": chunks,
            "stats": stats,
            "facts": result.facts,
            "edges": result.edges,
            "nodes": result.nodes,
            "total_count": result.total_count,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "graph_id": graph_id,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if not args.keep_graph:
            try:
                builder.backend.delete_graph(graph_id)
            except Exception:
                traceback.print_exc()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
