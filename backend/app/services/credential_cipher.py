"""模型 Provider 凭据的本地加密与脱敏。"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


class CredentialCipher:
    def __init__(self, key_path: str | Path):
        self.key_path = Path(key_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.key_path.parent, 0o700)
        if not self.key_path.exists():
            try:
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(Fernet.generate_key())
            except FileExistsError:
                pass
        os.chmod(self.key_path, 0o600)
        self._fernet = Fernet(self.key_path.read_bytes())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()

    @staticmethod
    def mask(value: str) -> str:
        if not value:
            return ""
        prefix = value[:3] if len(value) > 7 else value[:1]
        suffix = value[-4:] if len(value) > 4 else ""
        return f"{prefix}***{suffix}"
