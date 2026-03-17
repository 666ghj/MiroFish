"""Input validation utilities for path traversal prevention."""

import os
import re

# Safe ID pattern: alphanumeric, underscores, hyphens only
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def validate_safe_id(value: str, field_name: str = "id") -> str:
    """
    Validate that a value is a safe identifier (no path traversal chars).

    Raises ValueError if the value contains slashes, dots, or other unsafe chars.
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"{field_name} 不能为空")
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"{field_name} 包含非法字符: {value}")
    return value


def validate_path_within(path: str, base_dir: str) -> str:
    """
    Validate that a resolved path is contained within base_dir.
    Resolves symlinks and normalizes both paths before comparison.

    Raises ValueError if the path escapes the base directory.
    """
    resolved = os.path.realpath(path)
    base = os.path.realpath(base_dir)
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise ValueError(f"路径越界: {path}")
    return resolved
