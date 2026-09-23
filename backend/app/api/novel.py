"""小说种子摄入端点（novel-mac fork，改造 ①）。

POST /api/novel/seed
    请求体为 NovelMirofishSeed JSON（novel-agent 侧编译）；确定性建 project
    与图谱，不经 LLM。结果只描述调用本身——沙盘结论的解读与 Apply 一律在
    novel-agent 侧经提案审阅完成。
"""

from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, request

from ..models.project import ProjectManager
from ..services.novel_seed import NovelSeedValidationError, NovelSeeder
from ..utils.logger import get_logger

logger = get_logger("mirofish.novel_api")

novel_bp = Blueprint("novel", __name__, url_prefix="/api/novel")


@novel_bp.route("/seed", methods=["POST"])
def create_novel_seed():
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400

        result = NovelSeeder().seed(payload)
        return jsonify({"success": True, "data": result})
    except NovelSeedValidationError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        logger.error(f"小说种子摄入失败: {error}")
        return jsonify(
            {
                "success": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        ), 500
