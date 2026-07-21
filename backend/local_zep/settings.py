from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_ROOT.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=True)
    else:
        load_dotenv(override=True)


def _project_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((_PROJECT_ROOT / path).resolve())


@dataclass(frozen=True)
class LocalZepSettings:
    llm_api_key: str | None = os.environ.get("LLM_API_KEY")
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model_name: str = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")
    embedding_api_key: str = os.environ.get("EMBEDDING_API_KEY", "local-embedding-key")
    embedding_base_url: str | None = os.environ.get("EMBEDDING_BASE_URL")
    embedding_model_name: str | None = os.environ.get("EMBEDDING_MODEL_NAME")
    reranker_api_key: str = os.environ.get("RERANKER_API_KEY", "local-reranker-key")
    reranker_base_url: str | None = os.environ.get("RERANKER_BASE_URL")
    reranker_model_name: str | None = os.environ.get("RERANKER_MODEL_NAME")
    local_zep_rerank_top_k: int = int(os.environ.get("LOCAL_ZEP_RERANK_TOP_K", "50"))
    local_zep_extract_max_retries: int = int(os.environ.get("LOCAL_ZEP_EXTRACT_MAX_RETRIES", "2"))
    local_zep_extract_max_output_tokens: int = int(os.environ.get("LOCAL_ZEP_EXTRACT_MAX_OUTPUT_TOKENS", "2048"))
    local_zep_db_path: str = _project_path(
        os.environ.get(
            "LOCAL_ZEP_DB_PATH",
            str(_BACKEND_ROOT / "data" / "local_zep.sqlite3"),
        )
    )


settings = LocalZepSettings()
