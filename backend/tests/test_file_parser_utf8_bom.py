import importlib.util
from pathlib import Path

_FILE_PARSER = Path(__file__).resolve().parents[1] / "app" / "utils" / "file_parser.py"
_SPEC = importlib.util.spec_from_file_location("mirofish_file_parser", _FILE_PARSER)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_read_text_with_fallback = _MODULE._read_text_with_fallback


def test_read_text_with_fallback_strips_utf8_bom(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"\xef\xbb\xbfhello")

    assert _read_text_with_fallback(str(path)) == "hello"


def test_read_text_with_fallback_keeps_plain_utf8(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_bytes("你好".encode("utf-8"))

    assert _read_text_with_fallback(str(path)) == "你好"
