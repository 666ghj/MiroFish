#!/usr/bin/env python3
"""Replace persisted legacy Zep graph IDs with their v4 UUIDs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

_PROCESS_ZEP_API_KEY = os.environ.get("ZEP_API_KEY", "").strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zep_cloud import NotFoundError

from app.config import Config
from app.utils.zep import get_zep_client


def _is_zep_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return parsed.version in {4, 5} and str(parsed) == value.lower()


def _atomic_write(path: Path, content: str) -> None:
    file_stat = path.stat()
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            os.fchmod(temporary_file.fileno(), file_stat.st_mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _read_json_file(path: Path) -> tuple[Any, Any]:
    if path.suffix == ".jsonl":
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        return [json.loads(line) for line in lines if line.strip()], text.endswith("\n")
    return json.loads(path.read_text(encoding="utf-8")), None


def _serialize_json_file(path: Path, data: Any, trailing_newline: Any) -> str:
    if path.suffix == ".jsonl":
        text = "\n".join(json.dumps(row, ensure_ascii=False) for row in data)
        return f"{text}\n" if trailing_newline else text
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def backfill_graph_ids(
    storage_dir: Path,
    client: Any,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Find and optionally update legacy IDs in persisted JSON data."""

    lookup_cache: dict[str, str | None] = {}
    plans: list[dict[str, str]] = []
    not_found: set[str] = set()
    updated_files: list[str] = []
    skipped_files: list[dict[str, str]] = []

    def resolve(legacy_id: str) -> str | None:
        if legacy_id not in lookup_cache:
            try:
                graph = client.graph.lookup(graph_id=legacy_id)
            except NotFoundError:
                lookup_cache[legacy_id] = None
                not_found.add(legacy_id)
            else:
                lookup_cache[legacy_id] = graph.uuid_
        return lookup_cache[legacy_id]

    def update_graph_ids(value: Any, path: Path, pointer: str) -> bool:
        changed = False
        if isinstance(value, dict):
            legacy_id = value.get("graph_id")
            if isinstance(legacy_id, str) and legacy_id and not _is_zep_uuid(legacy_id):
                graph_uuid = resolve(legacy_id)
                if graph_uuid:
                    plans.append(
                        {
                            "file": str(path),
                            "path": pointer or "/",
                            "legacy_graph_id": legacy_id,
                            "graph_id": graph_uuid,
                        }
                    )
                    if apply:
                        value["legacy_zep_graph_id"] = legacy_id
                        value["graph_id"] = graph_uuid
                        changed = True
            for key, child in list(value.items()):
                if key in {"graph_id", "legacy_zep_graph_id"}:
                    continue
                escaped_key = str(key).replace("~", "~0").replace("/", "~1")
                changed |= update_graph_ids(
                    child,
                    path,
                    f"{pointer}/{escaped_key}",
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                changed |= update_graph_ids(child, path, f"{pointer}/{index}")
        return changed

    files = sorted(
        path
        for path in storage_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    )
    for path in files:
        try:
            data, trailing_newline = _read_json_file(path)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            skipped_files.append(
                {
                    "path": str(path),
                    "error_type": type(error).__name__,
                }
            )
            continue

        if update_graph_ids(data, path, "") and apply:
            try:
                content = _serialize_json_file(path, data, trailing_newline)
                _atomic_write(path, content)
            except OSError as error:
                skipped_files.append(
                    {
                        "path": str(path),
                        "error_type": type(error).__name__,
                    }
                )
                continue
            updated_files.append(str(path))

    return {
        "apply": apply,
        "files_scanned": len(files),
        "lookups": len(lookup_cache),
        "planned_changes": plans,
        "updated_files": updated_files,
        "not_found": sorted(not_found),
        "skipped_files": skipped_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(Config.UPLOAD_FOLDER),
        help="Storage directory to scan (defaults to the MiroFish upload directory)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write UUIDs to disk; without this option, the command only reports changes",
    )
    args = parser.parse_args()
    result = backfill_graph_ids(
        args.storage_dir,
        get_zep_client(api_key=_PROCESS_ZEP_API_KEY or None),
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
