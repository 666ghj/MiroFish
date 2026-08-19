from __future__ import annotations

import argparse
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_BASE_URL = os.environ.get("MIROFISH_BASE_URL", "http://127.0.0.1:5001")
DEFAULT_TIMEOUT = float(os.environ.get("MIROFISH_HTTP_TIMEOUT", "60"))

mcp = FastMCP(
    name="MiroFish MCP",
    instructions=(
        "Use these tools to drive MiroFish as a prediction engine and simulation brain. "
        "Create a project graph first, then create a simulation, prepare it, start it, "
        "and generate or fetch reports."
    ),
)


def _base_url() -> str:
    return os.environ.get("MIROFISH_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _request(method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        response = client.request(method, url, params=params, json=json_body)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {"success": True, "status_code": response.status_code, "text": response.text}


@mcp.tool()
def mirofish_health() -> dict[str, Any]:
    return _request("GET", "/health")


@mcp.tool()
def mirofish_list_projects() -> dict[str, Any]:
    return _request("GET", "/api/graph/project/list")


@mcp.tool()
def mirofish_get_project(project_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/graph/project/{project_id}")


@mcp.tool()
def mirofish_build_graph(payload: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", "/api/graph/build", json_body=payload)


@mcp.tool()
def mirofish_get_graph_task(task_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/graph/task/{task_id}")


@mcp.tool()
def mirofish_create_simulation(
    project_id: str,
    graph_id: str | None = None,
    enable_twitter: bool = True,
    enable_reddit: bool = True,
) -> dict[str, Any]:
    payload = {
        "project_id": project_id,
        "enable_twitter": enable_twitter,
        "enable_reddit": enable_reddit,
    }
    if graph_id:
        payload["graph_id"] = graph_id
    return _request("POST", "/api/simulation/create", json_body=payload)


@mcp.tool()
def mirofish_prepare_simulation(
    simulation_id: str,
    entity_types: list[str] | None = None,
    use_llm_for_profiles: bool = True,
    parallel_profile_count: int = 5,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "simulation_id": simulation_id,
        "use_llm_for_profiles": use_llm_for_profiles,
        "parallel_profile_count": parallel_profile_count,
        "force_regenerate": force_regenerate,
    }
    if entity_types:
        payload["entity_types"] = entity_types
    return _request("POST", "/api/simulation/prepare", json_body=payload)


@mcp.tool()
def mirofish_prepare_status(task_id: str) -> dict[str, Any]:
    return _request("POST", "/api/simulation/prepare/status", json_body={"task_id": task_id})


@mcp.tool()
def mirofish_start_simulation(
    simulation_id: str,
    platform: str = "parallel",
    max_rounds: int | None = None,
    enable_graph_memory_update: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "simulation_id": simulation_id,
        "platform": platform,
        "enable_graph_memory_update": enable_graph_memory_update,
        "force": force,
    }
    if max_rounds is not None:
        payload["max_rounds"] = max_rounds
    return _request("POST", "/api/simulation/start", json_body=payload)


@mcp.tool()
def mirofish_stop_simulation(simulation_id: str) -> dict[str, Any]:
    return _request("POST", "/api/simulation/stop", json_body={"simulation_id": simulation_id})


@mcp.tool()
def mirofish_simulation_status(simulation_id: str, detailed: bool = False) -> dict[str, Any]:
    suffix = "/run-status/detail" if detailed else "/run-status"
    return _request("GET", f"/api/simulation/{simulation_id}{suffix}")


@mcp.tool()
def mirofish_simulation_timeline(simulation_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/simulation/{simulation_id}/timeline")


@mcp.tool()
def mirofish_interview_agents(
    simulation_id: str,
    interviews: list[dict[str, Any]],
    platform: str = "parallel",
) -> dict[str, Any]:
    return _request(
        "POST",
        "/api/simulation/interview/batch",
        json_body={
            "simulation_id": simulation_id,
            "platform": platform,
            "interviews": interviews,
        },
    )


@mcp.tool()
def mirofish_generate_report(simulation_id: str, force_regenerate: bool = False) -> dict[str, Any]:
    return _request(
        "POST",
        "/api/report/generate",
        json_body={"simulation_id": simulation_id, "force_regenerate": force_regenerate},
    )


@mcp.tool()
def mirofish_report_status(task_id: str) -> dict[str, Any]:
    return _request("POST", "/api/report/generate/status", json_body={"task_id": task_id})


@mcp.tool()
def mirofish_get_report(report_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/report/{report_id}")


@mcp.tool()
def mirofish_get_report_by_simulation(simulation_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/report/by-simulation/{simulation_id}")


@mcp.tool()
def mirofish_chat_report(
    simulation_id: str,
    message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "simulation_id": simulation_id,
        "message": message,
    }
    if chat_history:
        payload["chat_history"] = chat_history
    return _request("POST", "/api/report/chat", json_body=payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose MiroFish backend APIs over MCP.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default=os.environ.get("MIROFISH_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MIROFISH_MCP_PORT", "8000")))
    args = parser.parse_args()

    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
        return

    mcp.run()


if __name__ == "__main__":
    main()
