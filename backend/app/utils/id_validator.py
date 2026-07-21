import os
import re

_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')


def validate_safe_id(value: str, name: str = "id") -> str:
    """Raise ValueError if value contains path-traversal characters."""
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {name}: must contain only alphanumeric characters, underscores, or hyphens")
    return value


def safe_join(base_dir: str, *parts: str) -> str:
    """Join paths and verify the result stays inside base_dir."""
    base = os.path.realpath(base_dir)
    joined = os.path.realpath(os.path.join(base_dir, *parts))
    if joined != base and not joined.startswith(base + os.sep):
        raise ValueError(f"Path traversal detected: resolved path is outside {base_dir!r}")
    return joined
