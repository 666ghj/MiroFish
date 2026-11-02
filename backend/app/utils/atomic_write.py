"""Crash-safe file writes."""

import json
import os
import tempfile
import time
from typing import Any, Callable, IO, Optional


def _write_atomic(path: str, write: Callable[[IO[str]], None], newline: Optional[str] = None) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as handle:
            write(handle)
            handle.flush()
            # Without this, a crash right after the rename can leave the *new*
            # file zero-filled: the rename is committed but the data is not.
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def write_json_atomic(path: str, data: Any, *, indent: int = 2) -> None:
    """Write ``data`` as JSON so readers never observe a half-written file.

    The JSON goes to a temp file in the same directory, is flushed to disk, and
    then replaces ``path`` in one step. ``os.replace`` can fail transiently on
    Windows while another thread has the target open for reading, so a few
    short retries are made before giving up.
    """
    _write_atomic(path, lambda handle: json.dump(data, handle, ensure_ascii=False, indent=indent))


def write_text_atomic(path: str, text: str) -> None:
    """Atomically write UTF-8 text (LF newlines), flushed to disk like ``write_json_atomic``."""
    _write_atomic(path, lambda handle: handle.write(text), newline="\n")
