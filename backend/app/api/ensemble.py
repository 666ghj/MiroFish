"""
集成模拟（Ensemble Simulation）相关API路由

把同一个已准备好的场景独立重复运行 N 次，并对结果做分布聚合。
详见 app.services.ensemble_runner 模块文档。
"""

import traceback

from flask import request, jsonify

from . import ensemble_bp
from ..services.ensemble_runner import EnsembleRunner
from ..services.simulation_manager import SimulationManager
from ..utils.authorization import authorize, ForbiddenError
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.ensemble')


def _authorize_simulation_access(simulation_id: str) -> None:
    """校验当前用户是否拥有该 simulation_id 对应的项目（同 api/simulation.py）。"""
    state = SimulationManager().get_simulation(simulation_id)
    if state is not None:
        authorize(state)


def _authorize_ensemble_access(ensemble_id: str):
    """校验当前用户是否拥有该集成；返回记录本身（可能为 None）。"""
    record = EnsembleRunner.get_ensemble_record(ensemble_id)
    if record is not None:
        authorize(record)
    return record


@ensemble_bp.route('/start', methods=['POST'])
def start_ensemble():
    """
    启动一次集成模拟：把某个已准备好的模拟场景独立重复运行 N 次

    请求（JSON）：
        {
            "source_simulation_id": "sim_xxxx",  // 必填，已完成 /prepare 的模拟ID
            "run_count": 20,                      // 必填，重复运行次数（2-50）
            "platform": "parallel",               // 可选：twitter / reddit / parallel
            "max_rounds": 100                     // 可选：透传给每个成员
        }

    返回：
        {
            "success": true,
            "data": {
                "ensemble_id": "ens_xxxx",
                "run_count": 20,
                "members": [{"simulation_id": "...", "index": 0, "start_error": null}, ...]
            }
        }

    注意：集成成员不支持 enable_graph_memory_update——N 个成员并发写入
    同一个 Zep 图谱没有明确语义，需要图谱记忆更新的场景请用单次模拟运行。
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            # get_json(silent=True) happily returns a decoded non-object
            # JSON value (a list, a string, a bare number/bool) without
            # raising -- the "or {}" idiom above only rescues None/falsy,
            # not e.g. `[1]`, so a plain `.get(...)` on it would otherwise
            # raise AttributeError and surface as a 500.
            return jsonify({
                "success": False,
                "error": "request body must be a JSON object",
            }), 400

        source_simulation_id = data.get('source_simulation_id')
        if not source_simulation_id:
            return jsonify({
                "success": False,
                "error": "source_simulation_id is required",
            }), 400

        run_count = data.get('run_count')
        if run_count is None:
            return jsonify({
                "success": False,
                "error": "run_count is required",
            }), 400

        platform = data.get('platform')
        if platform is not None and platform not in ('twitter', 'reddit', 'parallel'):
            return jsonify({
                "success": False,
                "error": f"Invalid platform: {platform}",
            }), 400

        max_rounds = data.get('max_rounds')
        if max_rounds is not None:
            # isinstance(True, int) is True in Python, and int(2.9) silently
            # truncates to 2 instead of rejecting a non-integer value --
            # both would otherwise let a fractional or boolean max_rounds
            # through and run a different number of rounds than requested.
            if not isinstance(max_rounds, int) or isinstance(max_rounds, bool):
                return jsonify({
                    "success": False,
                    "error": "max_rounds must be a positive integer",
                }), 400
            if max_rounds <= 0:
                return jsonify({
                    "success": False,
                    "error": "max_rounds must be a positive integer",
                }), 400

        _authorize_simulation_access(source_simulation_id)

        record = EnsembleRunner.start_ensemble(
            source_simulation_id=source_simulation_id,
            run_count=run_count,
            platform=platform,
            max_rounds=max_rounds,
        )

        return jsonify({
            "success": True,
            "data": record.to_dict(),
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 400

    except ForbiddenError:
        # 交给 app.__init__ 里注册的全局 ForbiddenError 处理器返回 403，
        # 而不是被下面的通用 Exception 分支吞成一个带 traceback 的 500。
        raise

    except Exception as e:
        logger.error(f"启动集成模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@ensemble_bp.route('/<ensemble_id>', methods=['GET'])
def get_ensemble(ensemble_id: str):
    """
    获取集成的实时状态与（若已全部完成）聚合统计

    返回的 status 是现算的：running / completed / failed。
    aggregate 只有在所有成员都到达终态、且至少一个成员成功完成时才非空。
    """
    try:
        _authorize_ensemble_access(ensemble_id)
        summary = EnsembleRunner.get_ensemble_summary(ensemble_id)
        return jsonify({
            "success": True,
            "data": summary,
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 404
    except ForbiddenError:
        raise
    except Exception as e:
        logger.error(f"获取集成状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@ensemble_bp.route('/list', methods=['GET'])
def list_ensembles():
    """列出集成（可选 ?project_id= 过滤），仅返回当前用户拥有的记录。"""
    try:
        from ..utils.authorization import is_owned_by_current_user

        project_id = request.args.get('project_id')
        records = EnsembleRunner.list_ensembles(project_id=project_id)
        records = [r for r in records if is_owned_by_current_user(r)]
        return jsonify({
            "success": True,
            "data": [r.to_dict() for r in records],
        })
    except Exception as e:
        logger.error(f"列出集成失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@ensemble_bp.route('/stop', methods=['POST'])
def stop_ensemble():
    """停止集成中所有仍处于非终态的成员（尽力而为，逐成员报告结果）。"""
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "error": "request body must be a JSON object",
            }), 400
        ensemble_id = data.get('ensemble_id')
        if not ensemble_id:
            return jsonify({
                "success": False,
                "error": "ensemble_id is required",
            }), 400

        _authorize_ensemble_access(ensemble_id)
        results = EnsembleRunner.stop_ensemble(ensemble_id)
        return jsonify({
            "success": True,
            "data": {"ensemble_id": ensemble_id, "results": results},
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 404
    except ForbiddenError:
        raise
    except Exception as e:
        logger.error(f"停止集成模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500
