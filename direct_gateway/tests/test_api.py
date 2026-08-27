from types import SimpleNamespace

from app.api import create_app
from app.responses_client import DirectProviderResult


class Router:
    def complete(self, request):
        return DirectProviderResult('{"ok":true}', "gpt-test", {"input_tokens": 1})


def test_api_auth_contract_and_provider_header():
    app = create_app(router=Router(), config=SimpleNamespace(internal_token="inside"), account_reader=lambda: {"authenticated": True, "email": "u***r@example.com"})
    client = app.test_client()
    assert client.post("/v1/chat/completions", json={"messages": []}).status_code == 401
    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer inside"}, json={"messages": [{"role": "user", "content": "x"}]})
    assert response.status_code == 200
    assert response.headers["X-MiroFish-Provider"] == "chatgpt-direct-oauth"
    assert response.json["choices"][0]["message"]["content"] == '{"ok":true}'
    assert client.post("/v1/chat/completions", headers={"Authorization": "Bearer inside"}, json={"messages": [], "stream": True}).status_code == 400
