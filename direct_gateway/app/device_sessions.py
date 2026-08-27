"""Device Code 登录会话状态机。"""

import threading
import time
import uuid

from .oauth import extract_account_metadata


class DeviceLoginManager:
    def __init__(self, oauth, store):
        self.oauth = oauth
        self.store = store
        self._sessions = {}
        self._lock = threading.Lock()

    def start(self):
        auth = self.oauth.start()
        login_id = f"login_{uuid.uuid4().hex[:16]}"
        session = {"login_id": login_id, "status": "waiting", "verification_uri": auth.verification_uri, "user_code": auth.user_code, "expires_at": time.time() + 900, "cancelled": False}
        with self._lock:
            for item in self._sessions.values():
                if item["status"] == "waiting": item["cancelled"] = True; item["status"] = "cancelled"
            self._sessions[login_id] = session
        threading.Thread(target=self._poll, args=(login_id, auth), daemon=True).start()
        return self._safe(session)

    def _poll(self, login_id, auth):
        try:
            tokens = self.oauth.poll(auth)
            with self._lock:
                if self._sessions[login_id]["cancelled"]: return
            metadata = extract_account_metadata(tokens.id_token, tokens.access_token)
            self.store.save(tokens, account_id=metadata.account_id, email=metadata.email, plan=metadata.plan, residency=metadata.residency)
            with self._lock: self._sessions[login_id]["status"] = "authenticated"
        except TimeoutError:
            with self._lock: self._sessions[login_id]["status"] = "expired"
        except Exception:
            with self._lock: self._sessions[login_id]["status"] = "failed"

    def status(self, login_id):
        with self._lock:
            if login_id not in self._sessions: raise KeyError(login_id)
            return {**self._safe(self._sessions[login_id]), "account": self.store.status() if self._sessions[login_id]["status"] == "authenticated" else None}

    def cancel(self, login_id):
        with self._lock:
            if login_id not in self._sessions: raise KeyError(login_id)
            self._sessions[login_id]["cancelled"] = True
            self._sessions[login_id]["status"] = "cancelled"
            return self._safe(self._sessions[login_id])

    @staticmethod
    def _safe(session):
        return {key: session[key] for key in ("login_id", "status", "verification_uri", "user_code", "expires_at")}
