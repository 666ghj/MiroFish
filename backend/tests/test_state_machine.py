"""
共享状态机基础设施测试：原子写入、转换合法性检查、修订号计算。
"""

import json
import os

import pytest

from app.utils.state_machine import (
    atomic_write_json,
    is_valid_transition,
    next_revision,
)


class TestIsValidTransition:
    GRAPH = {
        "a": {"b", "c"},
        "b": {"c"},
        "c": set(),
    }

    def test_no_previous_state_always_allowed(self):
        assert is_valid_transition(self.GRAPH, None, "a") is True
        assert is_valid_transition(self.GRAPH, None, "z") is True

    def test_self_loop_always_allowed(self):
        assert is_valid_transition(self.GRAPH, "a", "a") is True
        assert is_valid_transition(self.GRAPH, "c", "c") is True

    def test_allowed_transition(self):
        assert is_valid_transition(self.GRAPH, "a", "b") is True
        assert is_valid_transition(self.GRAPH, "b", "c") is True

    def test_disallowed_transition(self):
        assert is_valid_transition(self.GRAPH, "c", "a") is False
        assert is_valid_transition(self.GRAPH, "a", "z") is False


class TestNextRevision:
    def test_from_none_starts_at_one(self):
        assert next_revision(None) == 1

    def test_increments(self):
        assert next_revision(1) == 2
        assert next_revision(41) == 42

    def test_from_zero(self):
        assert next_revision(0) == 1


class TestAtomicWriteJson:
    def test_writes_readable_json(self, tmp_path):
        path = str(tmp_path / "state.json")
        atomic_write_json(path, {"hello": "world", "n": 1})
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"hello": "world", "n": 1}

    def test_no_leftover_temp_files_on_success(self, tmp_path):
        path = str(tmp_path / "state.json")
        atomic_write_json(path, {"a": 1})
        entries = os.listdir(tmp_path)
        assert entries == ["state.json"]

    def test_overwrite_replaces_content(self, tmp_path):
        path = str(tmp_path / "state.json")
        atomic_write_json(path, {"version": 1})
        atomic_write_json(path, {"version": 2})
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"version": 2}

    def test_creates_missing_parent_directory(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "state.json")
        atomic_write_json(path, {"a": 1})
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}

    def test_original_file_preserved_when_write_fails(self, tmp_path, monkeypatch):
        path = str(tmp_path / "state.json")
        atomic_write_json(path, {"version": "original"})

        def boom(*args, **kwargs):
            raise RuntimeError("simulated crash mid-write")

        monkeypatch.setattr(json, "dump", boom)
        with pytest.raises(RuntimeError):
            atomic_write_json(path, {"version": "corrupted"})

        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f) == {"version": "original"}
        # No stray temp file left behind either.
        entries = os.listdir(tmp_path)
        assert entries == ["state.json"]
