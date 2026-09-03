"""
SoSim Backend - Flask application factory.
"""

import os
import warnings

# Silence the multiprocessing resource_tracker warning raised by third-party
# libraries such as transformers. This has to run before any other import.
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Build and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Serialize responses as UTF-8 rather than \uXXXX escapes.
    # Flask >= 2.3 exposes app.json.ensure_ascii; older versions use JSON_AS_ASCII.
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    logger = setup_logger('sosim')

    # One-shot startup work must run in exactly one process. Under the Flask
    # reloader only the child has WERKZEUG_RUN_MAIN=true; outside debug mode the
    # variable is absent and this is the only process. This is the same
    # predicate SimulationRunner.register_cleanup applies to itself.
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    is_debug_mode = (
        app.config.get('DEBUG', False)
        or os.environ.get('FLASK_DEBUG') == '1'
        or os.environ.get('WERKZEUG_RUN_MAIN') is not None
    )
    is_primary_process = is_reloader_child or not is_debug_mode

    if is_primary_process:
        logger.info("=" * 50)
        logger.info("Starting SoSim Backend")
        logger.info("=" * 50)

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Terminate every simulation process when the server shuts down.
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if is_primary_process:
        logger.info("Registered the simulation process cleanup handler")

        # Preparation and monitoring run in daemon threads, so a backend restart
        # kills them without an exception and no failure handler ever runs. This
        # pass repairs the simulations they left stranded.
        reconciled = SimulationRunner.reconcile_startup()
        logger.info(
            "Startup reconciliation checked %s interrupted preparations and %s interrupted runs",
            len(reconciled.get("preparations", [])),
            len(reconciled.get("runs", [])),
        )

    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('sosim.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('sosim.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    # Blueprints
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'SoSim Backend'}

    if is_primary_process:
        logger.info("SoSim Backend started")

    return app
