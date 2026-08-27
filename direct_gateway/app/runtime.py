from __future__ import annotations

from .oauth import DeviceCodeClient, extract_account_metadata


class TokenManager:
    def __init__(self, store, oauth: DeviceCodeClient):
        self.store = store
        self.oauth = oauth

    def fresh(self):
        tokens, metadata = self.store.load()
        fresh = self.oauth.ensure_fresh(tokens)
        if fresh != tokens:
            derived = extract_account_metadata(fresh.id_token, fresh.access_token)
            metadata = {"account_id": derived.account_id or metadata.get("account_id"), "email": derived.email or metadata.get("email"), "plan": derived.plan or metadata.get("plan"), "residency": derived.residency or metadata.get("residency")}
            self.store.save(fresh, **metadata)
        return fresh, metadata

    def force_refresh(self):
        tokens, metadata = self.store.load()
        fresh = self.oauth.refresh(tokens.refresh_token)
        derived = extract_account_metadata(fresh.id_token, fresh.access_token)
        metadata = {"account_id": derived.account_id or metadata.get("account_id"), "email": derived.email or metadata.get("email"), "plan": derived.plan or metadata.get("plan"), "residency": derived.residency or metadata.get("residency")}
        self.store.save(fresh, **metadata)
        return fresh, metadata
