"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

import jwt
from flask import Flask, request, jsonify
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger

# Rutes públiques que no requereixen token JWT
_PUBLIC_PATHS = {'/health', '/api/auth/login'}


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

    # Middleware d'autenticació JWT — s'executa ABANS del log_request (ordre FIFO)
    @app.before_request
    def require_auth():
        if request.path in _PUBLIC_PATHS or request.method == 'OPTIONS':
            return None
        if not request.path.startswith('/api/'):
            return None  # rutes estàtiques del SPA no requereixen token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'success': False, 'error': 'Missing token'}), 401
        token = auth_header[len('Bearer '):]
        try:
            jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'error': 'Invalid token'}), 401

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

    # 注册蓝图 (auth primer, luego els existents)
    from .api import graph_bp, simulation_bp, report_bp, auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    # Servir el SPA de Vue compilat (producció: quan existeix frontend/dist/)
    # La catch-all es registra al final perquè les rutes /api/* tinguin prioritat
    import os as _os
    from flask import send_from_directory, send_file as _send_file
    _dist = _os.path.join(_os.path.dirname(__file__), '../../frontend/dist')
    if _os.path.isdir(_dist):
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_spa(path):
            f = _os.path.join(_dist, path)
            if path and _os.path.isfile(f):
                return send_from_directory(_dist, path)
            return _send_file(_os.path.join(_dist, 'index.html'))

    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")

    return app
