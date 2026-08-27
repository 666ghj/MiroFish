from types import SimpleNamespace

from app.login import login_device_code, read_account_status


class FakeHandle:
    verification_url = "https://auth.openai.com/codex/device"
    user_code = "ABCD-1234"

    def wait(self):
        return SimpleNamespace(success=True, error=None)


class FakeCodex:
    refresh_requests = []

    def login_chatgpt_device_code(self):
        return FakeHandle()

    def account(self, refresh_token=False):
        self.refresh_requests.append(refresh_token)
        return SimpleNamespace(
            account=SimpleNamespace(
                email="owner@example.com",
                planType="pro",
                access_token="must-not-leak",
            )
        )


def test_device_login_prints_only_safe_fields():
    output = []
    status = login_device_code(FakeCodex(), output=output.append)

    text = "\n".join(output)
    assert "https://auth.openai.com/codex/device" in text
    assert "ABCD-1234" in text
    assert "o***r@example.com" in text
    assert "pro" in text
    assert "must-not-leak" not in text
    assert status["authenticated"] is True
    assert FakeCodex.refresh_requests[-1] is True


def test_read_account_status_handles_logged_out_state():
    codex = FakeCodex()
    codex.account = lambda refresh_token=False: SimpleNamespace(account=None)
    assert read_account_status(codex) == {
        "authenticated": False,
        "email": None,
        "plan_type": None,
    }


def test_read_account_status_unwraps_root_model_account():
    wrapped_account = SimpleNamespace(
        root=SimpleNamespace(
            email="owner@example.com",
            plan_type=SimpleNamespace(value="pro"),
        )
    )
    codex = FakeCodex()
    codex.account = lambda refresh_token=False: SimpleNamespace(
        account=wrapped_account
    )

    assert read_account_status(codex) == {
        "authenticated": True,
        "email": "o***r@example.com",
        "plan_type": "pro",
    }
