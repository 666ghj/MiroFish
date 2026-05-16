"""MiroFish Backend - Flask application factory"""
import os
import warnings
from functools import wraps

warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, verify_jwt_in_request, get_jwt_identity

from .config import Config
from .utils.logger import setup_logger, get_logger

# Rutes públiques (sense JWT requerit)
_PUBLIC_PATHS = {
    '/health',
    '/api/auth/login',
    '/api/auth/logout',
    '/api/auth/forgot-password',
    '/api/auth/reset-password',
    '/api/auth/set-password',
}
_PUBLIC_PREFIXES = (
    '/api/auth/invitation/',
    '/api/auth/reset-password/',
)


def create_app(config_class=Config):
    """Flask application factory"""
    app = Flask(__name__)
    if isinstance(config_class, dict):
        app.config.from_object(Config)
        app.config.from_mapping(config_class)
    else:
        app.config.from_object(config_class)

    # Inicialitzar BD
    from .db import init_db
    init_db(app.config['DATABASE_URL'])

    # Inicialitzar Storage
    from .storage import create_storage_service
    app.extensions['storage'] = create_storage_service()

    # flask-jwt-extended
    JWTManager(app)

    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    logger = setup_logger('mirofish')
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend starting...")
        logger.info("=" * 50)

    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()

    @app.before_request
    def require_auth():
        if app.config.get('TESTING'):
            return None
        if request.method == 'OPTIONS':
            return None
        if request.path in _PUBLIC_PATHS:
            return None
        if any(request.path.startswith(p) for p in _PUBLIC_PREFIXES):
            return None
        if not request.path.startswith('/api/'):
            return None
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    from .api import graph_bp, simulation_bp, report_bp, auth_bp, users_bp, admin_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

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


def get_storage():
    from flask import current_app
    return current_app.extensions['storage']


def get_current_user():
    """Retorna el UserModel autenticat o None (en mode TESTING)."""
    from flask import current_app
    if current_app.config.get('TESTING'):
        return None
    try:
        user_id = get_jwt_identity()
    except Exception:
        return None
    if not user_id:
        return None
    from .db import get_session
    from .models.db_models import UserModel
    with get_session() as db:
        user = db.get(UserModel, user_id)
        if user:
            db.expunge(user)
        return user


def require_admin(f):
    """Decorator: requereix role=='admin'. Saltat en mode TESTING."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import current_app
        if not current_app.config.get('TESTING'):
            user = get_current_user()
            if not user or user.role != 'admin':
                return jsonify({'success': False, 'error': 'Admin required'}), 403
        return f(*args, **kwargs)
    return decorated


def require_project_owner(f):
    """Decorator: requereix ser propietari del projecte o admin. Saltat en TESTING."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import current_app
        if not current_app.config.get('TESTING'):
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
            if user.role != 'admin':
                project_id = kwargs.get('project_id')
                if project_id:
                    from .db import get_session
                    from .models.db_models import ProjectModel
                    with get_session() as db:
                        proj = db.get(ProjectModel, project_id)
                        if proj and proj.user_id and proj.user_id != user.id:
                            return jsonify({'success': False, 'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated
