"""Environment-first loading and validation for local and injected execution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


def is_unresolved_reference(value: str | None) -> bool:
    """Return whether a value is an unresolved 1Password secret address."""
    return bool(value and value.strip().startswith("op://"))


def load_environment(project_root: Path | str, backend_dir: Path | str | None = None) -> Path | None:
    """Load a local env file without replacing already-injected process values."""
    project_env = Path(project_root) / ".env"
    backend_env = Path(backend_dir) / ".env" if backend_dir else None
    env_file = project_env if project_env.exists() else backend_env if backend_env and backend_env.exists() else None
    if env_file:
        load_dotenv(env_file, override=False)
    return env_file


def environment_errors(required: Iterable[str], optional: Iterable[str] = ()) -> list[str]:
    """Describe required missing/unresolved values and optional unresolved values."""
    errors: list[str] = []
    for key in required:
        value = os.environ.get(key)
        if not value or not value.strip():
            errors.append(f"{key} is not configured")
        elif is_unresolved_reference(value):
            errors.append(f"{key} contains an unresolved 1Password reference; launch through oprun")
    for key in optional:
        if is_unresolved_reference(os.environ.get(key)):
            errors.append(f"{key} contains an unresolved 1Password reference; launch through oprun")
    return errors
