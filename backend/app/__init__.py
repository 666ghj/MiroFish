"""
MiroFish Backend - Flask application factory
"""

import os
import warnings

# Suppress multiprocessing resource_tracker warnings (from third-party libraries like transformers)
# Must be set before all other imports
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

import jwt
from flask import Flask, request, jsonify
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger

# Rutes públiques que no requereixen token JWT
_PUBLIC_PATHS = {'/health', '/api/auth/login'}


def create_app(config_class=Config):
    """Flask application factory"""
    app = Flask(__name__)
    if isinstance(config_class, dict):
        app.config.from_object(Config)
        app.config.from_mapping(config_class)
    else:
        app.config.from_object(config_class)

    # Configure JSON encoding: ensure non-ASCII characters are output directly (not as \uXXXX)
    # Flask >= 2.3 uses app.json.ensure_ascii; older versions use JSON_AS_ASCII config
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Set up logging
    logger = setup_logger('mirofish')

    # Only log startup info in the reloader subprocess (avoids double-printing in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend starting...")
        logger.info("=" * 50)

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register simulation process cleanup (ensures all simulation processes are terminated on server shutdown)
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup handler registered")

    # Middleware d'autenticació JWT — s'executa ABANS del log_request (ordre FIFO)
    @app.before_request
    def require_auth():
        if app.config.get('TESTING'):
            return None  # skip auth in test mode
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

    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    # Register blueprints (auth first, then the rest)
    from .api import graph_bp, simulation_bp, report_bp, auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # Health check
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
        logger.info("MiroFish Backend startup complete")

    return app
