"""
Backend Flask application factory
"""

import os
import warnings

# Suppress multiprocessing resource_tracker warnings (from third-party libraries such as transformers)
# Must be set before all other imports
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask application factory function"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configure JSON encoding: ensure non-ASCII characters are output directly (not as \uXXXX escapes)
    # Flask >= 2.3 uses app.json.ensure_ascii; older versions use the JSON_AS_ASCII config key
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Set up logging
    logger = setup_logger('mirofish')

    # Only print startup info in the reloader child process (avoids double printing in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info(f"{Config.APP_NAME} backend starting...")
        logger.info("=" * 50)

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register simulation process cleanup function (ensures all simulation processes are terminated on server shutdown)
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup function registered")

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

    # Register blueprints
    from .api import graph_bp, simulation_bp, report_bp, gtm_bp, idea_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(gtm_bp, url_prefix='/api/gtm')
    app.register_blueprint(idea_bp, url_prefix='/api/idea')

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': f'{Config.APP_NAME} backend'}

    if should_log_startup:
        logger.info(f"{Config.APP_NAME} backend started successfully")

    return app
