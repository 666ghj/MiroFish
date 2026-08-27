from __future__ import annotations

import sys

from .config import DirectConfig
from .oauth import DeviceCodeClient, extract_account_metadata
from .token_store import TokenStore


def main(argv=None):
    command = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else "status"
    config = DirectConfig.from_env()
    store = TokenStore(config.credentials_path)
    if command == "status":
        print(store.status())
    elif command == "logout":
        store.clear()
        print("已退出 Direct OAuth")
    elif command == "login":
        oauth = DeviceCodeClient(config=config)
        auth = oauth.start()
        print(f"请访问 {auth.verification_uri} 并输入代码 {auth.user_code}")
        tokens = oauth.poll(auth)
        metadata = extract_account_metadata(tokens.id_token, tokens.access_token)
        store.save(tokens, account_id=metadata.account_id, email=metadata.email, plan=metadata.plan, residency=metadata.residency)
        print(store.status())
    else:
        raise SystemExit("用法: python -m app.login login|status|logout")


if __name__ == "__main__":
    main()
