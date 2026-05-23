from __future__ import annotations
import hashlib
import json
from pathlib import Path
import yaml
from pydantic import ValidationError
from app.models.interview import (
    LikertInstrument, QSortInstrument,
)

class InstrumentValidationError(ValueError):
    pass

def _parse_yaml(path: Path) -> dict:
    if not path.exists():
        raise InstrumentValidationError(f"instrument file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InstrumentValidationError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(data, dict):
        raise InstrumentValidationError(f"top-level YAML must be a mapping in {path}")
    return data

def load_likert_instrument(path: Path) -> LikertInstrument:
    data = _parse_yaml(Path(path))
    try:
        return LikertInstrument(**data)
    except ValidationError as e:
        raise InstrumentValidationError(str(e)) from e

def load_qsort_instrument(path: Path) -> QSortInstrument:
    data = _parse_yaml(Path(path))
    try:
        return QSortInstrument(**data)
    except ValidationError as e:
        raise InstrumentValidationError(str(e)) from e

def instrument_hash(path: Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]

def freeze_snapshot(instruments: dict[str, Path], out_path: Path) -> dict:
    snapshot = {
        name: {
            "path": str(p),
            "hash": instrument_hash(p),
            "content": _parse_yaml(p),
        }
        for name, p in instruments.items()
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot
