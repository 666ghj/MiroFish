"""Persist local provider configuration using the same .env as subprocesses."""
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import set_key

from ..config import Config, project_root_env

ENV_FILE = Path(project_root_env).resolve()
_lock = threading.Lock()
_FIELDS = {
    'llm_api_key': 'LLM_API_KEY',
    'llm_base_url': 'LLM_BASE_URL',
    'llm_model_name': 'LLM_MODEL_NAME',
    'zep_api_key': 'ZEP_API_KEY',
}


class SettingsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def public_settings():
    base = Config.LLM_BASE_URL or ''
    try:
        parsed = urlsplit(base)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            base = ''
    except ValueError:
        base = ''
    return {
        'llm_configured': bool(Config.LLM_API_KEY),
        'zep_configured': bool(Config.ZEP_API_KEY),
        'llm_base_url': base,
        'llm_model_name': Config.LLM_MODEL_NAME or '',
    }


def _validate(data):
    if not isinstance(data, dict) or set(data) - _FIELDS.keys():
        raise SettingsError('invalid')
    if any(not isinstance(value, str) or len(value) > 4096 or '${' in value or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in data.values()):
        raise SettingsError('invalid')
    values = {name: data.get(field, '').strip() for field, name in _FIELDS.items()}
    base = values['LLM_BASE_URL']
    try:
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or not parsed.port in (None, 443):
            raise ValueError()
    except ValueError:
        raise SettingsError('invalidBaseUrl') from None
    if base != Config.LLM_BASE_URL and Config.LLM_API_KEY and not values['LLM_API_KEY']:
        # Changing the destination must not silently reuse a stored credential.
        raise SettingsError('keyForNewProvider')
    values['LLM_API_KEY'] = values['LLM_API_KEY'] or Config.LLM_API_KEY or ''
    values['ZEP_API_KEY'] = values['ZEP_API_KEY'] or Config.ZEP_API_KEY or ''
    if not all(values.values()):
        raise SettingsError('required')
    return values


def save_settings(data):
    with _lock:
        values = _validate(data)
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Write a complete replacement first, with owner-only permissions. Preserve
        # unrelated .env settings/comments and dotenv quoting for special characters.
        descriptor, name = tempfile.mkstemp(prefix='.mirofish-ai-', dir=ENV_FILE.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                if ENV_FILE.exists():
                    stream.write(ENV_FILE.read_text(encoding='utf-8'))
            for key, value in values.items():
                set_key(temporary, key, value, quote_mode='always')
            os.chmod(temporary, 0o600)
            os.replace(temporary, ENV_FILE)
        finally:
            temporary.unlink(missing_ok=True)
        # New clients and newly spawned OASIS processes use the saved values.
        for key, value in values.items():
            setattr(Config, key, value)
            os.environ[key] = value
