"""API routes module"""
from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
auth_bp = Blueprint('auth', __name__)
users_bp = Blueprint('users', __name__)
admin_bp = Blueprint('admin', __name__)

from . import graph      # noqa
from . import simulation # noqa
from . import report     # noqa
from . import auth       # noqa
from . import users      # noqa
from . import admin      # noqa
