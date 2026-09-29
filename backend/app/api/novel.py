"""小说种子摄入端点（novel-mac fork，改造 ①）。

POST /api/novel/seed
    请求体为 NovelMirofishSeed JSON（novel-agent 侧编译）；确定性建 project
    与图谱，不经 LLM。结果只描述调用本身——沙盘结论的解读与 Apply 一律在
    novel-agent 侧经提案审阅完成。
"""

from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from ..models.project import ProjectManager
from ..services.novel_counterfactual import (
    CounterfactualRunNotFound,
    CounterfactualRunRequest,
    counterfactual_runs,
)
from ..services.novel_seed import NovelSeedValidationError, NovelSeeder
from ..services.novel_world import (
    WorldReplayRequest,
    WorldSimulationError,
    WorldSnapshot,
    branch_snapshot,
    replay_actions,
)
from ..utils.logger import get_logger

logger = get_logger("mirofish.novel_api")

novel_bp = Blueprint("novel", __name__, url_prefix="/api/novel")


@novel_bp.route("/counterfactual/capabilities", methods=["GET"])
def counterfactual_capabilities():
    """Expose the experimental M0 contract without claiming product readiness."""

    return jsonify(
        {
            "success": True,
            "data": {
                "protocolVersion": "novel-counterfactual/0.1",
                "stage": "m2-experimental",
                "capabilities": [
                    "typed-snapshot",
                    "typed-action",
                    "branch",
                    "replay",
                    "snapshot-diff",
                    "async-run",
                    "stop",
                ],
                "experimentalModes": ["plot-counterfactual"],
                "productModes": [],
            },
        }
    )


@novel_bp.route("/counterfactual/branch", methods=["POST"])
def create_counterfactual_branch():
    """Create an in-memory branch from a verified frozen snapshot."""

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400
        snapshot = WorldSnapshot.model_validate(payload.get("snapshot"))
        branch_id = payload.get("branchId")
        if not isinstance(branch_id, str):
            return jsonify({"success": False, "error": "branchId 必须是字符串"}), 400
        branch = branch_snapshot(snapshot, branch_id)
        return jsonify({"success": True, "data": branch.model_dump(mode="json")})
    except (ValidationError, WorldSimulationError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        logger.error("反事实分支创建失败: %s", error)
        return jsonify({"success": False, "error": str(error)}), 500


@novel_bp.route("/counterfactual/replay", methods=["POST"])
def replay_counterfactual():
    """Replay a bounded typed action trace without OASIS, LLM or graph writes."""

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400
        replay = WorldReplayRequest.model_validate(payload)
        final, deltas = replay_actions(
            replay.baseSnapshot,
            replay.actions,
            max_actions=replay.maxActions,
        )
        return jsonify(
            {
                "success": True,
                "data": {
                    "finalSnapshot": final.model_dump(mode="json"),
                    "deltas": [delta.model_dump(mode="json") for delta in deltas],
                },
            }
        )
    except (ValidationError, WorldSimulationError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        logger.error("反事实 replay 失败: %s", error)
        return jsonify({"success": False, "error": str(error)}), 500


@novel_bp.route("/counterfactual/run", methods=["POST"])
def start_counterfactual_run():
    """Queue bounded branch/replay work in the sidecar process."""

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400
        run_request = CounterfactualRunRequest.model_validate(payload)
        summary = counterfactual_runs.create(run_request)
        return jsonify({"success": True, "data": summary.model_dump(mode="json")}), 202
    except (ValidationError, WorldSimulationError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        logger.error("反事实运行创建失败: %s", error)
        return jsonify({"success": False, "error": str(error)}), 500


@novel_bp.route("/counterfactual/run/<run_id>", methods=["GET"])
def read_counterfactual_run(run_id: str):
    try:
        summary = counterfactual_runs.summary(run_id)
        return jsonify({"success": True, "data": summary.model_dump(mode="json")})
    except CounterfactualRunNotFound as error:
        return jsonify({"success": False, "error": str(error)}), 404


@novel_bp.route("/counterfactual/run/<run_id>/branches/<branch_id>", methods=["GET"])
def read_counterfactual_branch(run_id: str, branch_id: str):
    try:
        result = counterfactual_runs.branch(run_id, branch_id)
        return jsonify({"success": True, "data": result.model_dump(mode="json")})
    except CounterfactualRunNotFound as error:
        return jsonify({"success": False, "error": str(error)}), 404


@novel_bp.route("/counterfactual/run/<run_id>/branches/<branch_id>/snapshot", methods=["GET"])
def read_counterfactual_snapshot(run_id: str, branch_id: str):
    try:
        result = counterfactual_runs.branch(run_id, branch_id)
        if result.finalSnapshot is None:
            return jsonify({"success": False, "error": "branch snapshot is not ready"}), 409
        return jsonify({"success": True, "data": result.finalSnapshot.model_dump(mode="json")})
    except CounterfactualRunNotFound as error:
        return jsonify({"success": False, "error": str(error)}), 404


@novel_bp.route("/counterfactual/run/<run_id>/branches/<branch_id>/diff", methods=["GET"])
def read_counterfactual_diff(run_id: str, branch_id: str):
    try:
        result = counterfactual_runs.branch(run_id, branch_id)
        return jsonify(
            {
                "success": True,
                "data": {"branchId": branch_id, "deltas": [delta.model_dump(mode="json") for delta in result.deltas]},
            }
        )
    except CounterfactualRunNotFound as error:
        return jsonify({"success": False, "error": str(error)}), 404


@novel_bp.route("/counterfactual/run/<run_id>/stop", methods=["POST"])
def stop_counterfactual_run(run_id: str):
    try:
        summary = counterfactual_runs.stop(run_id)
        return jsonify({"success": True, "data": summary.model_dump(mode="json")}), 202
    except CounterfactualRunNotFound as error:
        return jsonify({"success": False, "error": str(error)}), 404


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
