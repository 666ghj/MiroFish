"""
LLM settings persisted on disk (local-only).

This module is intentionally lightweight so it can be imported by:
- Flask backend (API endpoints + services)
- simulation scripts under backend/scripts (no Flask dependency)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ..config import Config, _normalize_openai_base_url


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))


def default_llm_settings_path() -> str:
    """
    Default local settings path (ignored by git):
    - MiroFish-config/llm.json (preferred)
    """
    return os.path.join(_project_root(), "MiroFish-config", "llm.json")


def legacy_llm_settings_path() -> str:
    """
    Legacy fallback path under uploads (ignored by git).
    """
    return os.path.join(_project_root(), "backend", "uploads", "settings", "llm.json")


def resolve_llm_settings_path() -> str:
    explicit = os.environ.get("MIROFISH_LLM_CONFIG_FILE") or os.environ.get("MIROFISH_LLM_SETTINGS_FILE")
    if explicit:
        return explicit
    preferred = default_llm_settings_path()
    legacy = legacy_llm_settings_path()
    if os.path.exists(preferred):
        return preferred
    if os.path.exists(legacy):
        return legacy
    return preferred


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


# Stage 定义：用于模型路由
STAGE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "json_structure": {
        "label": "JSON 结构化输出",
        "description": "用于大纲规划、子问题生成、采访问题生成等需要严格 JSON 格式的任务",
        "recommended": ["gpt-5.2", "deepseek-v3.2-chat", "glm-4.7", "gemini-claude-sonnet-4-5"],
        "warnings": [
            {"pattern": "-thinking$", "message": "推理模型可能返回空 JSON，不建议用于此阶段", "level": "warning"},
            {"pattern": "-reasoner$", "message": "推理模型可能返回空 JSON，不建议用于此阶段", "level": "warning"},
            {"pattern": "^gemini-3-pro", "message": "已知 JSON 输出不稳定，强烈不建议", "level": "error"},
        ],
        "tip": "💡 推荐使用 GPT-5.2，JSON 输出最稳定，token 消耗小",
    },
    "content_generation": {
        "label": "报告内容生成",
        "description": "用于生成报告章节的长文本内容，需要高质量的文字表达",
        "recommended": ["gemini-claude-sonnet-4-5", "gemini-claude-opus-4-5-thinking"],
        "warnings": [],
        "tip": "💡 推荐使用 Claude Sonnet 4.5，平衡质量与成本",
    },
    "reasoning": {
        "label": "复杂推理任务",
        "description": "用于深度分析、策略规划等需要深度思考的任务",
        "recommended": ["gemini-claude-opus-4-5-thinking", "deepseek-v3.2-reasoner", "kimi-k2-thinking"],
        "warnings": [],
        "tip": "💡 推理模型擅长深度分析，但 token 消耗较高",
    },
    "profile_generation": {
        "label": "Agent 人设生成",
        "description": "用于生成模拟 Agent 的人物设定，需要创意性文本",
        "recommended": ["gemini-claude-sonnet-4-5", "deepseek-v3.2-chat"],
        "warnings": [],
        "tip": "💡 需要创意性，推荐综合能力强的模型",
    },
    "fallback": {
        "label": "默认/其他任务",
        "description": "未分类的其他任务",
        "recommended": [],
        "warnings": [],
        "tip": "使用默认模型",
    },
}

# 预设方案
MODEL_ROUTING_PRESETS: Dict[str, Dict[str, Any]] = {
    "economy": {
        "label": "经济模式",
        "description": "成本最低，适合测试",
        "routing": {
            "json_structure": "gpt-5.2",
            "content_generation": "deepseek-v3.2-chat",
            "reasoning": "deepseek-v3.2-reasoner",
            "profile_generation": "deepseek-v3.2-chat",
            "fallback": "gpt-5.2",
        },
    },
    "quality": {
        "label": "质量优先",
        "description": "质量最高，成本较高",
        "routing": {
            "json_structure": "gpt-5.2",
            "content_generation": "gemini-claude-opus-4-5-thinking",
            "reasoning": "gemini-claude-opus-4-5-thinking",
            "profile_generation": "gemini-claude-sonnet-4-5",
            "fallback": "gpt-5.2",
        },
    },
    "balanced": {
        "label": "混合推荐",
        "description": "平衡质量与成本（默认）",
        "routing": {
            "json_structure": "gpt-5.2",
            "content_generation": "gemini-claude-sonnet-4-5",
            "reasoning": "gemini-claude-opus-4-5-thinking",
            "profile_generation": "deepseek-v3.2-chat",
            "fallback": "gpt-5.2",
        },
    },
}


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: Optional[str]
    models: List[str]
    model_routing: Dict[str, str]  # stage -> model 映射
    updated_at: Optional[str] = None
    source_path: Optional[str] = None

    def normalized_base_url(self) -> str:
        return _normalize_openai_base_url(self.base_url) if self.base_url else ""

    def get_model_for_stage(self, stage: str) -> Optional[str]:
        """获取指定 stage 对应的模型，如果未配置返回 None"""
        return self.model_routing.get(stage) or self.model_routing.get("fallback")

    def public_dict(self) -> Dict[str, Any]:
        key = (self.api_key or "").strip()
        return {
            "base_url": self.normalized_base_url(),
            "models": self.models,
            "model_routing": self.model_routing,
            "api_key_set": bool(key),
            "api_key_last4": key[-4:] if len(key) >= 4 else (key if key else ""),
            "updated_at": self.updated_at,
            "source_path": self.source_path,
        }

    def create_openai_client(self) -> OpenAI:
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置（请在设置页填写或在 .env 中配置）")
        base_url = self.normalized_base_url()
        if base_url:
            return OpenAI(api_key=self.api_key, base_url=base_url)
        return OpenAI(api_key=self.api_key)


def load_llm_settings() -> LLMSettings:
    """
    Load settings from disk, falling back to environment.
    """
    path = resolve_llm_settings_path()
    data: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    base_url = (data.get("base_url") or "").strip() or (Config.LLM_BASE_URL or "").strip()
    api_key = (data.get("api_key") or "").strip() or (Config.LLM_API_KEY or "").strip() or None

    models: List[str] = []
    raw_models = data.get("models")
    if isinstance(raw_models, list):
        models = [str(m).strip() for m in raw_models if str(m).strip()]
    if not models:
        model = (data.get("model") or "").strip() or (Config.LLM_MODEL_NAME or "").strip()
        if model:
            models = [model]

    # 读取 model_routing 配置
    model_routing: Dict[str, str] = {}
    raw_routing = data.get("model_routing")
    if isinstance(raw_routing, dict):
        for stage, model_name in raw_routing.items():
            if isinstance(stage, str) and isinstance(model_name, str) and model_name.strip():
                model_routing[stage.strip()] = model_name.strip()

    updated_at = data.get("updated_at") if isinstance(data.get("updated_at"), str) else None

    return LLMSettings(
        base_url=base_url,
        api_key=api_key,
        models=models[:10],
        model_routing=model_routing,
        updated_at=updated_at,
        source_path=path,
    )


def save_llm_settings(
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    models: Optional[List[str]] = None,
    model_routing: Optional[Dict[str, str]] = None,
    clear_api_key: bool = False,
) -> LLMSettings:
    """
    Persist settings to disk.

    Notes:
    - Settings are local-only. The default path is ignored by git.
    - `api_key` is stored only when provided; use `clear_api_key=True` to remove.
    - `model_routing` maps stage names to model names.
    """
    current = load_llm_settings()
    next_base_url = (base_url if base_url is not None else current.base_url).strip()
    next_base_url = _normalize_openai_base_url(next_base_url) if next_base_url else ""

    if clear_api_key:
        next_api_key: Optional[str] = None
    elif api_key is not None:
        next_api_key = api_key.strip() or None
    else:
        next_api_key = current.api_key

    next_models = current.models
    if models is not None:
        next_models = [str(m).strip() for m in models if str(m).strip()]
        next_models = next_models[:10]

    # 处理 model_routing
    next_routing = dict(current.model_routing)
    if model_routing is not None:
        # 合并新配置（允许部分更新）
        for stage, model_name in model_routing.items():
            if isinstance(stage, str) and stage.strip():
                if model_name and isinstance(model_name, str) and model_name.strip():
                    next_routing[stage.strip()] = model_name.strip()
                elif stage.strip() in next_routing:
                    # 空值表示删除该 stage 配置
                    del next_routing[stage.strip()]

    payload: Dict[str, Any] = {
        "base_url": next_base_url,
        "api_key": next_api_key or "",
        "models": next_models,
        "model_routing": next_routing,
        "updated_at": datetime.now().isoformat(),
    }

    path = resolve_llm_settings_path()
    _atomic_write_json(path, payload)
    return load_llm_settings()
