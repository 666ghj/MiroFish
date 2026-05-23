import pytest
from app.services.interviews.instrument_loader import (
    load_likert_instrument, InstrumentValidationError,
)

def _write(tmp_path, text):
    p = tmp_path / "inst.yaml"
    p.write_text(text, encoding="utf-8")
    return p

def test_loads_valid_likert(tmp_path):
    p = _write(tmp_path, """
name: longitudinal_v1
version: "1.0"
language_default: de
items:
  - item_id: stk_1
    de: "Der westliche Dorschbestand wird sich erholen"
    en: "Western cod stock will recover"
    scale: 5
    family: stocks
""")
    inst = load_likert_instrument(p)
    assert inst.name == "longitudinal_v1"
    assert len(inst.items) == 1

def test_rejects_duplicate_item_id(tmp_path):
    p = _write(tmp_path, """
name: x
items:
  - {item_id: a, de: d, en: e, scale: 5}
  - {item_id: a, de: d, en: e, scale: 5}
""")
    with pytest.raises(InstrumentValidationError):
        load_likert_instrument(p)

def test_rejects_missing_required_field(tmp_path):
    p = _write(tmp_path, """
name: x
items:
  - {item_id: a, de: d, scale: 5}
""")
    with pytest.raises(InstrumentValidationError):
        load_likert_instrument(p)
