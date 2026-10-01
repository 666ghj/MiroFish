"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, jsonify, g
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger
from .utils.id_validation import InvalidIdentifierError, PathContainmentError
from .utils.auth import authenticate_request, AuthenticationError
from .utils.authorization import ForbiddenError

# /health 不需要认证；其余路径均为 /api/* 蓝图路由
AUTH_EXEMPT_PATHS = {'/health'}


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # 启用CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")

    if should_log_startup and not Config.API_KEYS:
        logger.warning(
            "MIROFISH_API_KEYS 未配置：API 认证已禁用，任何人都可以匿名访问所有接口。"
            "仅适用于本地单用户场景；对外或多用户部署前必须配置该变量。"
        )

    # 认证中间件：为每个请求解析 API Key 并写入 g.current_user_id，
    # 供后续基于资源所有权的授权逻辑使用
    @app.before_request
    def enforce_authentication():
        if request.method == 'OPTIONS' or request.path in AUTH_EXEMPT_PATHS:
            return None
        try:
            g.current_user_id = authenticate_request()
        except AuthenticationError as e:
            get_logger('mirofish.auth').warning(f"认证失败: {request.method} {request.path}: {e}")
            return jsonify({"error": "unauthorized", "message": str(e)}), 401
        return None

    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {request.get_json(silent=True)}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    # 统一处理非法标识符 / 路径越界异常，返回 400 而不是 500
    @app.errorhandler(InvalidIdentifierError)
    def handle_invalid_identifier(error):
        get_logger('mirofish.request').warning(f"拒绝非法标识符请求: {error}")
        return jsonify({"error": "invalid_identifier", "message": str(error)}), 400

    @app.errorhandler(PathContainmentError)
    def handle_path_containment(error):
        get_logger('mirofish.request').error(f"检测到路径越界尝试: {error}")
        return jsonify({"error": "invalid_path", "message": "Invalid resource path"}), 400

    # 统一处理资源所有权授权失败，返回 403
    @app.errorhandler(ForbiddenError)
    def handle_forbidden(error):
        get_logger('mirofish.request').warning(
            f"拒绝越权访问: {request.method} {request.path} user={getattr(g, 'current_user_id', None)}"
        )
        return jsonify({"error": "forbidden", "message": str(error)}), 403
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

