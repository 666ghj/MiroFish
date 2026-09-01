"""Put backend/ on sys.path so `from app import ...` works under any pytest invocation.

Without this, pytest only adds backend/tests/ to sys.path (there is no
__init__.py in tests/), so `uv run pytest` fails while
`uv run python -m pytest` happens to work because `python -m` prepends CWD.
Making it explicit means both forms work.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
