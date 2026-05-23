"""
API路由模块
"""

from flask import Blueprint, Flask

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
interview_bp = Blueprint('interview', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import interview  # noqa: E402, F401


def register_blueprints(app: Flask) -> None:
    """Register all API blueprints on *app* with their canonical URL prefixes."""
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(interview_bp, url_prefix='/api/interview')
