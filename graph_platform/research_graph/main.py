"""Run with uv run python -m research_graph.main."""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env', override=True)
os.environ['GRAPHITI_TELEMETRY_ENABLED'] = 'false'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

from .store import GraphStore
from .engine import GraphEngine
from .server import create_app


def main():
    import torch
    import uvicorn
    torch.set_num_threads(2)
    directory = Path(os.environ.get('LOCAL_GRAPH_DATA_DIR', ROOT / 'backend/uploads/local_graph')).expanduser().resolve()
    store = GraphStore(directory / 'journal.sqlite3')
    app = create_app(store, GraphEngine(store), os.environ.get('LOCAL_GRAPH_TOKEN'))
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('LOCAL_GRAPH_PORT', '5002')),
                log_level='info', timeout_graceful_shutdown=30)


if __name__ == '__main__':
    main()
