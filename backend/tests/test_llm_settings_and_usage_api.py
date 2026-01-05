import json

from app import create_app
from app.config import Config
from app.utils.llm_settings import load_llm_settings, save_llm_settings
from app.utils.openai_rotation import should_rotate_model


class DummyStatusError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def test_should_rotate_model_quota_and_not_auth():
    rotate, _reason = should_rotate_model(DummyStatusError("insufficient_quota", 429))
    assert rotate is True

    rotate, _reason = should_rotate_model(DummyStatusError("Unauthorized", 401))
    assert rotate is False


def test_llm_settings_save_load_roundtrip(tmp_path, monkeypatch):
    settings_path = tmp_path / "llm.json"
    monkeypatch.setenv("MIROFISH_LLM_CONFIG_FILE", str(settings_path))

    monkeypatch.setattr(Config, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-4o-mini", raising=False)

    saved = save_llm_settings(
        base_url="https://proxy.example.com:3333",
        api_key="test-key-1234",
        models=[f"m{i}" for i in range(20)],
    )
    assert saved.normalized_base_url().endswith("/v1")
    assert len(saved.models) == 10

    loaded = load_llm_settings()
    assert loaded.source_path == str(settings_path)
    assert loaded.api_key == "test-key-1234"
    assert loaded.models == saved.models


def test_llm_usage_api_aggregates_logs(tmp_path, monkeypatch):
    # Isolate uploads dir for this test
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setenv("MIROFISH_LLM_CONFIG_FILE", str(tmp_path / "llm.json"))

    sim_dir = tmp_path / "simulations" / "sim_test"
    sim_dir.mkdir(parents=True, exist_ok=True)
    log_path = sim_dir / "llm_usage.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-01-01T00:00:00",
                        "event": "success",
                        "stage": "oasis_twitter",
                        "model": "m1",
                        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-01-01T00:00:01",
                        "event": "error",
                        "stage": "oasis_twitter",
                        "model": "m1",
                        "error": {"status_code": 429, "message": "insufficient_quota"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = create_app()
    client = app.test_client()
    res = client.get("/api/llm/usage?limit=100")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["totals_by_model"]["m1"]["total_tokens"] == 5
    assert data["totals_by_model"]["m1"]["errors"] == 1
    assert data["totals_by_stage"]["oasis_twitter"]["requests"] == 2

