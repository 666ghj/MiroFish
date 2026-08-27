"""模型配置中心的数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ModelRole(str, Enum):
    EMBEDDING = "embedding"
    HIGH_CAPABILITY = "high_capability"
    HIGH_THROUGHPUT = "high_throughput"


class ConnectionType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL_OPENAI = "local_openai"
    EMBEDDING = "embedding"
    CODEX_GATEWAY = "codex_gateway"
    DIRECT_OAUTH_GATEWAY = "direct_oauth_gateway"


@dataclass(frozen=True)
class ModelConnection:
    connection_id: str
    name: str
    connection_type: ConnectionType
    base_url: str
    api_key_masked: str | None
    is_local: bool
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConfigVersion:
    version_id: str
    assignments: dict[ModelRole, dict[str, Any]]
    created_at: str


@dataclass(frozen=True)
class ProjectModelSnapshot:
    project_id: str
    version_id: str
    assignments: dict[ModelRole, dict[str, Any]]
    created_at: str
