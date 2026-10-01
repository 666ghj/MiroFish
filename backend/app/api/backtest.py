"""
历史回测（Historical Backtesting）相关API路由

把"预测"（登记）与"真实结果"（打分）拆成两个独立接口，详见
app.services.backtest_runner 模块文档。
"""

import traceback

from flask import request, jsonify

from . import backtest_bp
from ..services.backtest_runner import BacktestRunner
from ..services.simulation_manager import SimulationManager
from ..services.ensemble_runner import EnsembleRunner
from ..utils.authorization import (
    authorize,
    current_user_id,
    is_owned_by_current_user,
    ForbiddenError,
)
from ..utils.id_validation import InvalidIdentifierError, PathContainmentError
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.backtest')


def _authorize_source_access(source_simulation_id, source_ensemble_id) -> None:
    """校验当前用户是否拥有本次回测引用的来源模拟/集成。"""
    if source_simulation_id:
        state = SimulationManager().get_simulation(source_simulation_id)
        if state is not None:
            authorize(state)
    if source_ensemble_id:
        record = EnsembleRunner.get_ensemble_record(source_ensemble_id)
        if record is not None:
            authorize(record)


def _authorize_backtest_access(backtest_id: str):
    """校验当前用户是否拥有该回测；返回记录本身（可能为 None）。"""
    case = BacktestRunner.get_backtest(backtest_id)
    if case is not None:
        authorize(case)
    return case


@backtest_bp.route('/create', methods=['POST'])
def create_backtest():
    """
    登记一次回测场景（预测）：绑定一个已成功完成的单次模拟或集成，与一份
    结构化预测。此接口不接受真实结果——真实结果只能之后通过 /<id>/ground-truth
    单独登记。

    请求（JSON）：
        {
            "source_simulation_id": "sim_xxxx",  // 与 source_ensemble_id 二选一
            "source_ensemble_id": "ens_xxxx",     // 与 source_simulation_id 二选一
            "scenario_description": "...",         // 必填
            "t0_cutoff": "2024-01-01",              // 必填，说明性字段
            "prediction": {                          // 必填，至少一个字段
                "occurred": true,
                "probability": 0.7,
                "direction": "up",
                "sentiment": "positive",
                "rank": 3.0,
                "distribution": {"a": 0.6, "b": 0.4}
            }
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "error": "request body must be a JSON object",
            }), 400

        source_simulation_id = data.get('source_simulation_id')
        source_ensemble_id = data.get('source_ensemble_id')
        scenario_description = data.get('scenario_description')
        t0_cutoff = data.get('t0_cutoff')
        prediction = data.get('prediction')

        if not isinstance(prediction, dict):
            return jsonify({
                "success": False,
                "error": "prediction is required and must be a JSON object",
            }), 400

        _authorize_source_access(source_simulation_id, source_ensemble_id)

        case = BacktestRunner.create_backtest(
            scenario_description=scenario_description,
            t0_cutoff=t0_cutoff,
            prediction=prediction,
            source_simulation_id=source_simulation_id,
            source_ensemble_id=source_ensemble_id,
            # 显式传当前已认证用户，而不是让 service 从来源继承 owner_id：
            # 来源可能是一个认证启用前创建的"无主"历史资源，但由它派生出
            # 的这个 backtest 必须归属于真正发起这次登记的人。
            owner_id=current_user_id(),
        )

        return jsonify({
            "success": True,
            "data": case.to_dict(),
        })

    except ForbiddenError:
        raise

    except (InvalidIdentifierError, PathContainmentError):
        # InvalidIdentifierError/PathContainmentError 都是 ValueError 的
        # 子类，必须排在下面的 except ValueError 之前——否则会先被那个
        # 更宽泛的分支捕获，永远走不到这里，交给全局处理器返回统一、
        # 经过消毒的 400（PathContainmentError 的全局处理器专门避免把
        # 原始文件系统路径回显给客户端）。
        raise

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 400

    except Exception as e:
        logger.error(f"登记回测失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@backtest_bp.route('/<backtest_id>/ground-truth', methods=['POST'])
def record_ground_truth(backtest_id: str):
    """
    登记这个回测场景真实发生的结果，并立即计算该 case 自己的指标。一旦
    登记过一次即不可变——重复调用会被拒绝。

    请求（JSON）：
        {
            "ground_truth": {
                "occurred": true,
                "direction": "up",
                "sentiment": "positive",
                "rank": 2.0,
                "distribution": {"a": 0.55, "b": 0.45}
            }
        }
    """
    try:
        _authorize_backtest_access(backtest_id)

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "error": "request body must be a JSON object",
            }), 400

        ground_truth = data.get('ground_truth')
        if not isinstance(ground_truth, dict):
            return jsonify({
                "success": False,
                "error": "ground_truth is required and must be a JSON object",
            }), 400

        case = BacktestRunner.record_ground_truth(backtest_id, ground_truth)

        return jsonify({
            "success": True,
            "data": case.to_dict(),
        })

    except ForbiddenError:
        raise

    except (InvalidIdentifierError, PathContainmentError):
        raise

    except ValueError as e:
        status_code = 404 if "不存在" in str(e) else 400
        return jsonify({
            "success": False,
            "error": str(e),
        }), status_code

    except Exception as e:
        logger.error(f"登记回测真实结果失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@backtest_bp.route('/<backtest_id>', methods=['GET'])
def get_backtest(backtest_id: str):
    """获取单个回测 case（预测、真实结果[若已登记]、指标[若已打分]）。"""
    try:
        case = _authorize_backtest_access(backtest_id)
        if case is None:
            return jsonify({
                "success": False,
                "error": f"回测不存在: {backtest_id}",
            }), 404
        return jsonify({
            "success": True,
            "data": case.to_dict(),
        })
    except ForbiddenError:
        raise
    except (InvalidIdentifierError, PathContainmentError):
        raise
    except Exception as e:
        logger.error(f"获取回测失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@backtest_bp.route('/list', methods=['GET'])
def list_backtests():
    """列出回测（可选 ?project_id= 过滤），仅返回当前用户拥有的记录。"""
    try:
        project_id = request.args.get('project_id')
        cases = BacktestRunner.list_backtests(project_id=project_id)
        cases = [c for c in cases if is_owned_by_current_user(c)]
        return jsonify({
            "success": True,
            "data": [c.to_dict() for c in cases],
        })
    except Exception as e:
        logger.error(f"列出回测失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


@backtest_bp.route('/suite-summary', methods=['GET'])
def get_suite_summary():
    """
    对一批已打分的回测 case 现算套件级别聚合指标（rank correlation、
    calibration error 等）。可选 ?project_id= 过滤；始终只在当前用户
    拥有的 case 范围内计算——多用户部署下，套件聚合和 /list 一样，先按
    project_id 过滤再按所有权二次过滤，而不是直接聚合所有用户的 case。
    """
    try:
        project_id = request.args.get('project_id')
        cases = BacktestRunner.list_backtests(project_id=project_id)
        owned_cases = [c for c in cases if is_owned_by_current_user(c)]
        summary = BacktestRunner.summarize_cases(owned_cases)
        return jsonify({
            "success": True,
            "data": summary,
        })
    except Exception as e:
        logger.error(f"获取回测套件汇总失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500
