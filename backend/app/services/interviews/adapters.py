from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Optional
from app.services.interviews.base import PersonaRecord, MemoryDigest


class FileSystemPersonaProvider:
    """Reads OASIS profiles from the simulation's `reddit_profiles.json` and/or `twitter_profiles.csv`.

    If both are present, agents from `reddit_profiles.json` take precedence; twitter-only agents are appended.
    """

    def __init__(self, reddit_path: Optional[Path], twitter_path: Optional[Path]):
        self.reddit_path = Path(reddit_path) if reddit_path else None
        self.twitter_path = Path(twitter_path) if twitter_path else None

    def _load_reddit(self) -> list[PersonaRecord]:
        if not self.reddit_path or not self.reddit_path.exists():
            return []
        data = json.loads(self.reddit_path.read_text(encoding="utf-8"))
        out = []
        for row in data:
            out.append(PersonaRecord(
                agent_id=int(row.get("user_id")),
                name=str(row.get("name") or row.get("user_name") or f"agent_{row.get('user_id')}"),
                persona=str(row.get("persona") or row.get("bio") or ""),
                profession=row.get("profession"),
                bio=row.get("bio"),
            ))
        return out

    def _load_twitter(self) -> list[PersonaRecord]:
        if not self.twitter_path or not self.twitter_path.exists():
            return []
        out = []
        with self.twitter_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if not row.get("user_id"):
                    continue
                out.append(PersonaRecord(
                    agent_id=int(row["user_id"]),
                    name=str(row.get("name") or row.get("user_name") or f"agent_{row['user_id']}"),
                    persona=str(row.get("persona") or row.get("bio") or ""),
                    profession=row.get("profession"),
                    bio=row.get("bio"),
                ))
        return out

    def all(self) -> list[PersonaRecord]:
        reddit = self._load_reddit()
        seen = {p.agent_id for p in reddit}
        twitter = [p for p in self._load_twitter() if p.agent_id not in seen]
        return reddit + twitter

    def agent_to_entity(self) -> dict[int, str]:
        """Build the ``{agent_id: zep_entity_uuid}`` map from the persisted profile files.

        Both writers (``oasis_profile_generator._save_reddit_json`` and
        ``_save_twitter_csv``) emit ``source_entity_uuid`` per agent.  Reddit takes
        precedence; rows with a missing/blank uuid are skipped.
        Returns an empty dict if neither file is present or no row has the field.
        """
        mapping: dict[int, str] = {}

        # Reddit JSON
        if self.reddit_path and self.reddit_path.exists():
            try:
                rows = json.loads(self.reddit_path.read_text(encoding="utf-8"))
                for row in rows:
                    uid = row.get("user_id")
                    uuid_ = row.get("source_entity_uuid")
                    if uid is None or not uuid_:
                        continue
                    mapping[int(uid)] = str(uuid_)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Twitter CSV (only fills agents not already mapped)
        if self.twitter_path and self.twitter_path.exists():
            try:
                with self.twitter_path.open("r", encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        uid = row.get("user_id")
                        uuid_ = row.get("source_entity_uuid")
                        if not uid or not uuid_:
                            continue
                        try:
                            uid_int = int(uid)
                        except (TypeError, ValueError):
                            continue
                        if uid_int not in mapping:
                            mapping[uid_int] = str(uuid_)
            except OSError:
                pass

        return mapping


class ZepMemoryProvider:
    """Builds a bounded memory digest per agent from Zep entity context.

    Maps `agent_id` (OASIS user_id) to a Zep entity UUID; falls back to the agent_id as a string.
    """

    def __init__(self, entity_reader, graph_id: str, agent_to_entity: dict[int, str] | None = None):
        self.reader = entity_reader
        self.graph_id = graph_id
        self.map = dict(agent_to_entity or {})

    def get_digest(self, agent_id: int, max_chars: int = 2000) -> MemoryDigest:
        entity_uuid = self.map.get(agent_id) or str(agent_id)
        try:
            ctx = self.reader.get_entity_with_context(self.graph_id, entity_uuid)
        except Exception:
            return MemoryDigest(text=f"[no memory for agent {agent_id}]", available=False)
        parts: list[str] = []
        name = getattr(ctx, "name", None)
        summary = getattr(ctx, "summary", None)
        if name:
            parts.append(f"Name: {name}")
        if summary:
            parts.append(f"Summary: {summary}")
        edges = getattr(ctx, "related_edges", []) or []
        for e in edges[:20]:
            fact = e.get("fact") if isinstance(e, dict) else getattr(e, "fact", None)
            if fact:
                parts.append(f"- {fact}")
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return MemoryDigest(text=text or f"[empty memory for agent {agent_id}]", available=True)
