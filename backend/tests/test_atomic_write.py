import json
import os

import pytest

from app.utils import atomic_write
from app.utils.atomic_write import write_json_atomic, write_text_atomic


def test_json_round_trips_with_unicode_and_creates_parent_directories(tmp_path):
    target = tmp_path / "deep" / "er" / "data.json"
    write_json_atomic(str(target), {"name": "回音室", "n": [1, 2.5, None]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "回音室", "n": [1, 2.5, None]}
    assert "回音室" in target.read_text(encoding="utf-8")  # not escaped to \uXXXX


def test_the_target_is_replaced_and_no_temp_file_remains(tmp_path):
    target = tmp_path / "data.json"
    write_json_atomic(str(target), {"v": 1})
    write_json_atomic(str(target), {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_data_is_flushed_to_disk_before_the_rename(tmp_path, monkeypatch):
    """A crash right after the rename must not leave a zero-filled file."""
    events = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (events.append("replace"), real_replace(a, b))[1])
    write_json_atomic(str(tmp_path / "data.json"), {"v": 1})
    assert events == ["fsync", "replace"]

    events.clear()
    write_text_atomic(str(tmp_path / "note.md"), "hello\n")
    assert events == ["fsync", "replace"]


def test_a_failed_write_leaves_the_old_file_intact_and_no_temp_file(tmp_path):
    target = tmp_path / "data.json"
    write_json_atomic(str(target), {"v": 1})
    with pytest.raises(TypeError):
        write_json_atomic(str(target), {"v": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_a_transient_permission_error_on_replace_is_retried(tmp_path, monkeypatch):
    real_replace = os.replace
    attempts = []

    def flaky(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("sharing violation")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(atomic_write.time, "sleep", lambda _s: None)
    write_json_atomic(str(tmp_path / "data.json"), {"v": 1})
    assert len(attempts) == 3
    assert json.loads((tmp_path / "data.json").read_text(encoding="utf-8")) == {"v": 1}


def test_a_permanent_permission_error_is_raised_and_cleaned_up(tmp_path, monkeypatch):
    def locked(source, destination):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(atomic_write.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        write_json_atomic(str(tmp_path / "data.json"), {"v": 1})
    assert list(tmp_path.iterdir()) == []


def test_text_is_written_with_lf_newlines(tmp_path):
    write_text_atomic(str(tmp_path / "note.md"), "a\nb\n")
    assert (tmp_path / "note.md").read_bytes() == b"a\nb\n"  # never CRLF, even on Windows


def test_the_final_poll_writer_flushes_too(tmp_path, monkeypatch):
    import sim_runtime

    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(1), real_fsync(fd))[1])
    path = sim_runtime.write_final_poll(str(tmp_path), [{"agent_id": 0}])
    assert synced and json.loads(open(path, encoding="utf-8").read()) == [{"agent_id": 0}]
