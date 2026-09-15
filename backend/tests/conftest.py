"""Make the backend package importable from any working directory.

The ``app`` package lives in ``backend/`` while the tests live in
``backend/tests/``. ``pytest`` inserts the test module's basedir into
``sys.path`` but not ``backend/`` itself, so running the suite from the
repository root fails with ``ModuleNotFoundError: No module named 'app'``.
Inserting the backend directory up-front keeps ``from app... import ...``
working regardless of where pytest is invoked from.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
