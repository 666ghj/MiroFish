"""
API routing module
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
gtm_bp = Blueprint('gtm', __name__)
idea_bp = Blueprint('idea', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import gtm  # noqa: E402, F401
from . import idea  # noqa: E402, F401

