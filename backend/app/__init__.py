"""
MiroFish Backend - Flask应用工厂
"""

import hmac
import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, jsonify, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    # 配置校验（C1/C2）：在工厂内执行，确保 gunicorn（生产）路径也强制校验。
    # run.py（开发入口）也会单独校验，这里覆盖 `gunicorn app:create_app()` 这条不经过 run.py 的路径，
    # 否则 SECRET_KEY/API_KEY/LLM_API_KEY/ZEP_API_KEY 的缺省检查在生产中形同虚设。
    config_errors = config_class.validate()
    if config_errors:
        raise RuntimeError("配置错误，无法启动:\n  - " + "\n  - ".join(config_errors))

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
    
    # 启用CORS（H4）：限定来源为 Config.ALLOWED_ORIGINS（默认本地前端源），不再通配 '*'。
    CORS(app, resources={r"/api/*": {"origins": Config.ALLOWED_ORIGINS}})

    # API Key 鉴权（C2）：所有 /api/* 端点强制鉴权。
    # 客户端通过 `X-API-Key: <key>` 或 `Authorization: Bearer <key>` 传入。
    # /health 等非 /api 路径豁免；CORS 预检（OPTIONS）放行（浏览器预检不带自定义头）。
    @app.before_request
    def require_api_key():
        if not Config.AUTH_ENABLED:
            return None
        path = request.path or ''
        if not path.startswith('/api/'):
            return None
        if request.method == 'OPTIONS':
            return None
        provided = request.headers.get('X-API-Key', '')
        if not provided:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                provided = auth_header[7:]
        expected = Config.API_KEY or ''
        if not expected:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        # 常量时间比较，避免时序侧信道。两侧编码为 bytes —— compare_digest 对含非 ASCII 字符的
        # str 会抛 TypeError；编码后任何输入都安全，绝不让鉴权拒绝路径崩成 500。
        try:
            ok = hmac.compare_digest(provided.encode('utf-8'), expected.encode('utf-8'))
        except Exception:
            ok = False
        if not ok:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return None


    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")
    
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
    
    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")
    
    return app

