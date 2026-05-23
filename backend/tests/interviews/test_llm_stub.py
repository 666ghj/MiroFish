import json
from app.utils.llm_client import LLMClient


def test_stub_mode_returns_deterministic_canned_json(monkeypatch):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    from app.config import Config
    Config.LLM_STUB_MODE = True
    client = LLMClient(api_key="x", base_url="x", model="x")
    messages = [
        {"role": "system", "content": "You are persona_42. Return JSON."},
        {"role": "user", "content": "stub_key=longitudinal:item_001"},
    ]
    out1 = client.chat_json(messages=messages, temperature=0.0)
    out2 = client.chat_json(messages=messages, temperature=0.0)
    assert out1 == out2
    assert isinstance(out1, dict)
