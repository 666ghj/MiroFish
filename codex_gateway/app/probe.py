"""Safe Codex runtime and account metadata probe."""

from __future__ import annotations

import json
import os
from typing import Any, Callable


def _field(value: Any, *names: str) -> Any:
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
        if isinstance(value, dict) and name in value:
            return value[name]
    root = getattr(value, "root", None)
    if root is not None and root is not value:
        return _field(root, *names)
    return None


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if len(local) == 1:
        masked = local + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def probe_runtime(
    *,
    codex_factory: Callable[[], Any],
    sdk_version: str,
) -> dict[str, object]:
    with codex_factory() as codex:
        account_response = codex.account(refresh_token=False)
        account = _field(account_response, "account")
        models_response = codex.models()
        models = _field(models_response, "data") or []
        server = _field(codex.metadata, "serverInfo", "server_info")

        return {
            "sdk_version": sdk_version,
            "server_name": _field(server, "name"),
            "authenticated": account is not None,
            "email": _mask_email(_field(account, "email")),
            "plan_type": _field(account, "planType", "plan_type"),
            "models": [
                model_id
                for model in models
                if (model_id := _field(model, "id", "model"))
            ],
        }


def main() -> None:
    from openai_codex import Codex, CodexConfig, __version__

    codex_home = os.environ.get("CODEX_HOME", "/var/lib/codex")
    result = probe_runtime(
        codex_factory=lambda: Codex(
            config=CodexConfig(env={"CODEX_HOME": codex_home})
        ),
        sdk_version=__version__,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
