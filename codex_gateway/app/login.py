"""Server-terminal ChatGPT Device Code login managed by official Codex."""

from __future__ import annotations

import argparse
import os
from typing import Any, Callable

from .probe import _field, _mask_email


def read_account_status(
    codex: Any,
    *,
    refresh_token: bool = False,
) -> dict[str, object]:
    response = codex.account(refresh_token=refresh_token)
    account = _field(response, "account")
    plan_type = _field(account, "planType", "plan_type")
    plan_type = getattr(plan_type, "value", plan_type)
    return {
        "authenticated": account is not None,
        "email": _mask_email(_field(account, "email")),
        "plan_type": plan_type,
    }


def login_device_code(
    codex: Any,
    *,
    output: Callable[[str], None] = print,
) -> dict[str, object]:
    handle = codex.login_chatgpt_device_code()
    output(f"Open: {handle.verification_url}")
    output(f"Code: {handle.user_code}")
    completed = handle.wait()
    if not _field(completed, "success"):
        raise RuntimeError("ChatGPT Device Code login failed")
    status = read_account_status(codex, refresh_token=True)
    output(f"Account: {status['email'] or 'unknown'}")
    output(f"Plan: {status['plan_type'] or 'unknown'}")
    return status


def _build_codex():
    from openai_codex import Codex, CodexConfig

    return Codex(
        config=CodexConfig(
            cwd="/workspace",
            env={"CODEX_HOME": os.environ.get("CODEX_HOME", "/var/lib/codex")},
            config_overrides=(
                'approval_policy="never"',
                'sandbox_mode="read-only"',
                "mcp_servers={}",
                "hooks={}",
            ),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("login", "status", "logout"))
    args = parser.parse_args()

    with _build_codex() as codex:
        if args.command == "login":
            login_device_code(codex)
        elif args.command == "status":
            status = read_account_status(codex)
            print(f"Authenticated: {str(status['authenticated']).lower()}")
            print(f"Account: {status['email'] or 'unknown'}")
            print(f"Plan: {status['plan_type'] or 'unknown'}")
        else:
            codex.logout()
            print("Logged out")


if __name__ == "__main__":
    main()
