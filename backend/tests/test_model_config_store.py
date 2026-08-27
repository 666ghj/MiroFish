import os
import sqlite3

import pytest

from app.models.model_config import ConnectionType, ModelRole
from app.services.credential_cipher import CredentialCipher
from app.services.model_config_store import ModelConfigStore


def test_cipher_creates_private_key_and_never_returns_plaintext(tmp_path):
    key_path = tmp_path / "model-config" / "master.key"
    cipher = CredentialCipher(key_path)
    encrypted = cipher.encrypt("sk-live-secret-1234")

    assert cipher.decrypt(encrypted) == "sk-live-secret-1234"
    assert cipher.mask("sk-live-secret-1234") == "sk-***1234"
    assert "sk-live-secret-1234" not in encrypted
    assert oct(key_path.parent.stat().st_mode & 0o777) == "0o700"
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"


def test_connection_secret_is_encrypted_and_masked(tmp_path):
    store = ModelConfigStore(tmp_path / "models.db", CredentialCipher(tmp_path / "master.key"))
    connection = store.create_connection(
        name="线上模型", connection_type=ConnectionType.OPENAI_COMPATIBLE,
        base_url="https://example.com/v1", api_key="sk-live-secret-1234", is_local=False,
    )

    public = store.get_connection(connection.connection_id)
    assert public.api_key_masked == "sk-***1234"
    assert not hasattr(public, "api_key")
    assert store.get_connection_secret(connection.connection_id) == "sk-live-secret-1234"
    assert b"sk-live-secret-1234" not in (tmp_path / "models.db").read_bytes()


def test_draft_apply_creates_immutable_version_and_project_snapshot(tmp_path):
    store = ModelConfigStore(tmp_path / "models.db", CredentialCipher(tmp_path / "master.key"))
    text = store.create_connection("文本", ConnectionType.OPENAI_COMPATIBLE, "https://example.com/v1", "key", False)
    local = store.create_connection("本地", ConnectionType.LOCAL_OPENAI, "http://127.0.0.1:11434/v1", "", True)
    embedding = store.create_connection("向量", ConnectionType.EMBEDDING, "http://127.0.0.1:8080/v1", "", True)
    assignments = {
        ModelRole.HIGH_CAPABILITY: {"connection_id": text.connection_id, "model": "strong"},
        ModelRole.HIGH_THROUGHPUT: {"connection_id": local.connection_id, "model": "fast", "fallback_enabled": True},
        ModelRole.EMBEDDING: {"connection_id": embedding.connection_id, "model": "embed", "dimensions": 384},
    }
    store.save_draft(assignments)
    version = store.apply_draft()
    snapshot = store.get_or_create_project_snapshot("proj-1")

    assert version.assignments[ModelRole.HIGH_CAPABILITY]["model"] == "strong"
    assert snapshot.version_id == version.version_id
    store.save_draft({**assignments, ModelRole.HIGH_CAPABILITY: {"connection_id": text.connection_id, "model": "new"}})
    store.apply_draft()
    assert store.get_project_snapshot("proj-1").version_id == version.version_id


def test_connection_in_use_cannot_be_deleted(tmp_path):
    store = ModelConfigStore(tmp_path / "models.db", CredentialCipher(tmp_path / "master.key"))
    connection = store.create_connection("文本", ConnectionType.OPENAI_COMPATIBLE, "https://example.com/v1", "key", False)
    store.save_draft({ModelRole.HIGH_CAPABILITY: {"connection_id": connection.connection_id, "model": "strong"}})

    with pytest.raises(ValueError, match="正在被模型角色使用"):
        store.delete_connection(connection.connection_id)
