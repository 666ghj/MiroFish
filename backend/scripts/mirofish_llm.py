"""
Shared LLM config helpers for OASIS simulation scripts.

Reads local LLM settings (UI-configurable) and configures the environment
variables expected by camel-ai / openai compatible backends.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from app.utils.llm_settings import load_llm_settings

from rotating_openai_model import RotatingOpenAIModel


def _set_openai_env(api_key: str, base_url: str) -> None:
    # camel-ai expects:
    # - OPENAI_API_KEY
    # - OPENAI_API_BASE_URL
    # Some providers / libraries also use:
    # - OPENAI_BASE_URL
    # - OPENAI_API_BASE
    os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["OPENAI_API_BASE_URL"] = base_url
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_API_BASE"] = base_url


def resolve_llm_for_simulation(config: Dict[str, Any], *, use_boost: bool) -> Tuple[str, str, List[str], str]:
    """
    Returns (api_key, base_url, model_pool, label)
    """
    # Optional boost config (keeps previous behavior for parallel simulation)
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost = bool(boost_api_key)

    if use_boost and has_boost:
        model = (boost_model or os.environ.get("LLM_MODEL_NAME", "") or config.get("llm_model") or "gpt-4o-mini").strip()
        base_url = boost_base_url.strip()
        if base_url and not (base_url.rstrip("/").endswith("/v1") or "/v1/" in base_url):
            base_url = base_url.rstrip("/") + "/v1"
        return boost_api_key.strip(), base_url, [model], "[加速LLM]"

    settings = load_llm_settings()
    api_key = (settings.api_key or os.environ.get("LLM_API_KEY", "")).strip()
    base_url = (settings.normalized_base_url() or os.environ.get("LLM_BASE_URL", "")).strip()
    model_pool = list(settings.models) if settings.models else []

    if not model_pool:
        fallback = (os.environ.get("LLM_MODEL_NAME", "") or config.get("llm_model") or "gpt-4o-mini").strip()
        model_pool = [fallback]

    model_pool = [m for m in model_pool if m][:10]
    return api_key, base_url, model_pool, "[通用LLM]"


def create_oasis_model(
    config: Dict[str, Any],
    *,
    simulation_dir: str,
    use_boost: bool = False,
    stage: str = "oasis_simulation",
):
    api_key, base_url, model_pool, label = resolve_llm_for_simulation(config, use_boost=use_boost)
    if not api_key:
        raise ValueError("缺少 LLM API Key 配置，请在设置页填写或在 .env 中设置 LLM_API_KEY")

    _set_openai_env(api_key, base_url)

    usage_log_path = os.path.join(simulation_dir, "llm_usage.jsonl")
    print(f"{label} models={model_pool[:3]}{'...' if len(model_pool) > 3 else ''}, base_url={base_url[:40] if base_url else '默认'}...")

    return RotatingOpenAIModel(
        model_pool=model_pool,
        usage_log_path=usage_log_path,
        stage=stage,
    )

