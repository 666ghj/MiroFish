"""
LLM Settings + Models + Usage APIs
"""

from __future__ import annotations

from flask import jsonify, request

from . import llm_bp
from ..utils.logger import get_logger
from ..utils.llm_settings import (
    load_llm_settings,
    save_llm_settings,
    STAGE_DEFINITIONS,
    MODEL_ROUTING_PRESETS,
)
from ..utils.llm_usage import aggregate_usage, find_usage_log_paths, iter_usage_records

logger = get_logger("mirofish.api.llm")


@llm_bp.route("/config", methods=["GET"])
def get_llm_config():
    try:
        settings = load_llm_settings()
        return jsonify({"success": True, "data": settings.public_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/config", methods=["POST"])
def set_llm_config():
    try:
        data = request.get_json() or {}
        base_url = data.get("base_url")
        api_key = data.get("api_key")
        models = data.get("models")
        model_routing = data.get("model_routing")
        clear_api_key = bool(data.get("clear_api_key", False))

        if models is not None and not isinstance(models, list):
            return jsonify({"success": False, "error": "models 必须为字符串数组"}), 400

        if model_routing is not None and not isinstance(model_routing, dict):
            return jsonify({"success": False, "error": "model_routing 必须为对象"}), 400

        settings = save_llm_settings(
            base_url=base_url,
            api_key=api_key,
            models=models,
            model_routing=model_routing,
            clear_api_key=clear_api_key,
        )
        return jsonify({"success": True, "data": settings.public_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/models", methods=["GET"])
def list_models():
    try:
        settings = load_llm_settings()
        client = settings.create_openai_client()
        models = client.models.list()
        ids = []
        for m in getattr(models, "data", []) or []:
            mid = getattr(m, "id", None)
            if mid:
                ids.append(str(mid))
        ids.sort()
        return jsonify({"success": True, "data": {"models": ids}})
    except Exception as e:
        logger.warning(f"list_models failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/usage", methods=["GET"])
def get_usage():
    """
    Aggregate usage logs from all `llm_usage.jsonl` files under uploads.
    Query:
      - limit: max records to read (default: 5000)
    """
    try:
        limit = request.args.get("limit", "5000")
        try:
            max_records = int(limit)
        except Exception:
            max_records = 5000
        max_records = max(1, min(max_records, 200000))

        paths = find_usage_log_paths()
        agg = aggregate_usage(iter_usage_records(paths, max_records=max_records))
        return jsonify({"success": True, "data": {"paths": paths, **agg}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/stages", methods=["GET"])
def get_stages():
    """
    获取所有可配置的 stage 定义。
    返回每个 stage 的标签、描述、推荐模型、警告规则和使用提示。
    """
    try:
        return jsonify({"success": True, "data": {"stages": STAGE_DEFINITIONS}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/presets", methods=["GET"])
def get_presets():
    """
    获取模型路由预设方案。
    返回经济模式、质量优先、混合推荐等预设配置。
    """
    try:
        return jsonify({"success": True, "data": {"presets": MODEL_ROUTING_PRESETS}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@llm_bp.route("/routing", methods=["POST"])
def set_routing():
    """
    快速设置模型路由（仅更新 model_routing，不影响其他配置）。
    支持：
    - 传入完整的 routing 对象
    - 传入 preset 名称（economy/quality/balanced）应用预设
    """
    try:
        data = request.get_json() or {}

        # 如果指定了预设
        preset_name = data.get("preset")
        if preset_name:
            if preset_name not in MODEL_ROUTING_PRESETS:
                return jsonify({
                    "success": False,
                    "error": f"未知预设: {preset_name}，可用预设: {list(MODEL_ROUTING_PRESETS.keys())}"
                }), 400
            routing = MODEL_ROUTING_PRESETS[preset_name]["routing"]
        else:
            routing = data.get("routing")
            if not routing or not isinstance(routing, dict):
                return jsonify({"success": False, "error": "需要提供 routing 对象或 preset 名称"}), 400

        settings = save_llm_settings(model_routing=routing)
        return jsonify({"success": True, "data": settings.public_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

