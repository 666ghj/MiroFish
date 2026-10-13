"""HTTP boundary; the MCP process never imports or owns the Flask application."""
import json
import math
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp.exceptions import ToolError


class BackendClient:
    def __init__(self, base_url="http://127.0.0.1:5001", timeout=900, *, transport=None):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("MCP_BACKEND_URL must be a loopback HTTP origin, e.g. http://127.0.0.1:5001")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("MCP_REQUEST_TIMEOUT_SECONDS must be positive and finite")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def request(self, method, path, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=httpx.Timeout(self.timeout, connect=5),
                headers={"Accept-Language": "en"}, trust_env=False,
                follow_redirects=False, transport=self.transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ToolError(
                "Backend request timed out; work may still be running. Check project/task status "
                "before retrying. For create_project, reuse the same upload_id. "
                "Increase MCP_REQUEST_TIMEOUT_SECONDS and your MCP client's tool timeout if needed."
            ) from exc
        except httpx.RequestError as exc:
            raise ToolError(
                f"Cannot reach the research backend at {self.base_url}. "
                "Start it with npm run dev:agent (or npm run dev) and check MCP_BACKEND_URL."
            ) from exc
        if response.is_redirect:
            raise ToolError("Backend returned a redirect; check MCP_BACKEND_URL. Redirects are not followed.")
        try:
            result = response.json()
        except ValueError as exc:
            raise ToolError(f"Backend returned non-JSON (HTTP {response.status_code}); check the backend logs.") from exc
        if not isinstance(result, dict):
            raise ToolError("Backend returned an unexpected JSON shape; expected an object.")
        if response.is_error or result.get("success") is False:
            # Keep IDs, resumable flags, and pending status, but omit server stack traces.
            details = {key: value for key, value in result.items() if key != "traceback"}
            raise ToolError(f"Backend HTTP {response.status_code}: {json.dumps(details, ensure_ascii=False)}")
        return result
