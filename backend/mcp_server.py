"""Run the research MCP adapter. Stdio is the default and stdout is protocol-only."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from research_mcp.client import BackendClient
from research_mcp.server import create_server


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "4318")))
    parser.add_argument("--backend-url", default=os.environ.get(
        "MCP_BACKEND_URL", f"http://127.0.0.1:{os.environ.get('FLASK_PORT', '5001')}"))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port/MCP_PORT must be between 1 and 65535")
    try:
        client = BackendClient(args.backend_url, timeout=float(os.environ.get("MCP_REQUEST_TIMEOUT_SECONDS", "900")))
    except ValueError as exc:
        parser.error(str(exc))
    create_server(client, port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
