#!/bin/sh
set -eu
cd /Users/al/Documents/CODEX/MiroFish/backend
uv run python ../integrations/mcp/mirofish_mcp_server.py --transport stdio
