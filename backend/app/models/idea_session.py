"""
IdeaSession - one Idea Studio conversation, stored as JSON on disk.

Layout: uploads/idea_sessions/<session_id>/session.json
No database and no accounts, matching how GTM briefs are stored.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import Config

MAX_MESSAGE_CHARS = 4000
MAX_MESSAGES = 400          # hard cap per session file
_SESSION_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def is_valid_session_id(session_id: str) -> bool:
    """Only canonical UUIDs map to a folder, so ids can never escape the sessions directory."""
    return bool(session_id) and bool(_SESSION_ID.match(session_id))


class IdeaSessionManager:

    @staticmethod
    def _base() -> str:
        return os.path.join(Config.UPLOAD_FOLDER, 'idea_sessions')

    @staticmethod
    def _path(session_id: str) -> str:
        return os.path.join(IdeaSessionManager._base(), session_id, 'session.json')

    @staticmethod
    def _write(session: Dict[str, Any]) -> None:
        path = IdeaSessionManager._path(session['session_id'])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)   # atomic, so a crash never leaves half a file

    @staticmethod
    def create(title: Optional[str] = None) -> Dict[str, Any]:
        session = {
            'session_id': str(uuid.uuid4()),
            'title': (title or '').strip()[:120] or None,
            'created_at': _now(),
            'updated_at': _now(),
            'messages': [],
            # Structured idea state for the live panel; shape is decided by the Idea Studio research
            'state': {},
            'brief_id': None,
        }
        IdeaSessionManager._write(session)
        return session

    @staticmethod
    def get(session_id: str) -> Optional[Dict[str, Any]]:
        if not is_valid_session_id(session_id):
            return None
        path = IdeaSessionManager._path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def append_message(session_id: str, role: str, content: str,
                       extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if role not in ('user', 'assistant'):
            raise ValueError(f'invalid role: {role}')
        with _lock:
            session = IdeaSessionManager.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if len(session['messages']) >= MAX_MESSAGES:
                raise ValueError('session is full; start a new one')
            message = {'role': role, 'content': content[:MAX_MESSAGE_CHARS * 4], 'at': _now(), **(extra or {})}
            session['messages'].append(message)
            if not session.get('title') and role == 'user':
                session['title'] = content.strip().split('\n')[0][:80]
            session['updated_at'] = _now()
            IdeaSessionManager._write(session)
            return message

    @staticmethod
    def update_state(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        with _lock:
            session = IdeaSessionManager.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session['state'] = state
            session['updated_at'] = _now()
            IdeaSessionManager._write(session)
            return session

    @staticmethod
    def list(limit: int = 20) -> List[Dict[str, Any]]:
        base = IdeaSessionManager._base()
        if not os.path.exists(base):
            return []
        out = []
        for sid in os.listdir(base):
            s = IdeaSessionManager.get(sid)
            if s:
                out.append({k: s[k] for k in ('session_id', 'title', 'created_at', 'updated_at')}
                           | {'message_count': len(s['messages'])})
        out.sort(key=lambda s: s['updated_at'], reverse=True)
        return out[:limit]
