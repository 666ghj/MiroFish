from types import SimpleNamespace

from app.probe import probe_runtime


class FakeCodex:
    metadata = SimpleNamespace(
        serverInfo=SimpleNamespace(name="codex-app-server"),
    )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def account(self, refresh_token=False):
        assert refresh_token is False
        return SimpleNamespace(
            account=SimpleNamespace(
                type="chatgpt",
                email="owner@example.com",
                planType="pro",
                access_token="must-not-leak",
                refresh_token="must-not-leak",
            )
        )

    def models(self):
        return SimpleNamespace(data=[SimpleNamespace(id="gpt-5.4")])


def test_probe_returns_only_safe_runtime_metadata():
    result = probe_runtime(
        codex_factory=FakeCodex,
        sdk_version="0.147.0",
    )

    assert result == {
        "sdk_version": "0.147.0",
        "server_name": "codex-app-server",
        "authenticated": True,
        "email": "o***r@example.com",
        "plan_type": "pro",
        "models": ["gpt-5.4"],
    }
    assert "must-not-leak" not in repr(result)


def test_probe_handles_logged_out_account():
    class LoggedOutCodex(FakeCodex):
        def account(self, refresh_token=False):
            return SimpleNamespace(account=None)

    result = probe_runtime(
        codex_factory=LoggedOutCodex,
        sdk_version="0.147.0",
    )

    assert result["authenticated"] is False
    assert result["email"] is None
    assert result["plan_type"] is None
