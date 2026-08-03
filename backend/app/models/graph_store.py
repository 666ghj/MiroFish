"""
本地图谱存储
为 Claude 图谱引擎提供轻量级的 JSON 持久化存储
（Zep 引擎使用 Zep Cloud 托管图谱，Claude 引擎使用本地存储）
"""

import os
import json
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from ..config import Config


class GraphStore:
    """基于 JSON 文件的图谱存储，按 graph_id 持久化 nodes/edges/ontology"""

    GRAPHS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'graphs')
    _lock = threading.Lock()

    @classmethod
    def _ensure_dir(cls):
        os.makedirs(cls.GRAPHS_DIR, exist_ok=True)

    @classmethod
    def _path(cls, graph_id: str) -> str:
        return os.path.join(cls.GRAPHS_DIR, f"{graph_id}.json")

    @classmethod
    def create(cls, graph_id: str, name: str, description: str = "") -> Dict[str, Any]:
        cls._ensure_dir()
        data = {
            "graph_id": graph_id,
            "name": name,
            "description": description,
            "engine": "claude",
            "ontology": None,
            "nodes": {},   # uuid -> node dict
            "edges": [],   # list of edge dicts
            "created_at": datetime.now().isoformat(),
        }
        cls.save(graph_id, data)
        return data

    @classmethod
    def load(cls, graph_id: str) -> Optional[Dict[str, Any]]:
        path = cls._path(graph_id)
        if not os.path.exists(path):
            return None
        with cls._lock:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

    @classmethod
    def save(cls, graph_id: str, data: Dict[str, Any]) -> None:
        cls._ensure_dir()
        path = cls._path(graph_id)
        with cls._lock:
            tmp_path = f"{path}.tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)

    @classmethod
    def delete(cls, graph_id: str) -> bool:
        path = cls._path(graph_id)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True
