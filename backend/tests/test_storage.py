"""Tests para la StorageService."""
import io
import pytest
import tempfile
import os
from backend.app.storage.local import LocalFSStorage


@pytest.fixture
def storage(tmp_path):
    return LocalFSStorage(str(tmp_path))


def test_upload_and_download_bytes(storage):
    storage.upload("foo/bar.txt", b"hello world", "text/plain")
    assert storage.download("foo/bar.txt") == b"hello world"


def test_upload_and_download_stream(storage):
    data = io.BytesIO(b"stream data")
    storage.upload("test/stream.bin", data)
    result = storage.download("test/stream.bin")
    assert result == b"stream data"


def test_exists(storage):
    assert not storage.exists("not/there.txt")
    storage.upload("yes.txt", b"x")
    assert storage.exists("yes.txt")


def test_delete(storage):
    storage.upload("del.txt", b"bye")
    storage.delete("del.txt")
    assert not storage.exists("del.txt")


def test_delete_prefix(storage):
    storage.upload("dir/a.txt", b"a")
    storage.upload("dir/b.txt", b"b")
    storage.delete_prefix("dir")
    assert not storage.exists("dir/a.txt")
    assert not storage.exists("dir/b.txt")


def test_list(storage):
    storage.upload("root/x.txt", b"x")
    storage.upload("root/y.txt", b"y")
    paths = storage.list("root")
    assert len(paths) == 2
    assert all("root" in p for p in paths)


def test_path_traversal_blocked(storage):
    with pytest.raises(ValueError, match="Path traversal"):
        storage._safe_path("../../etc/passwd")


def test_public_url_is_none(storage):
    storage.upload("f.txt", b"x")
    assert storage.public_url("f.txt") is None
