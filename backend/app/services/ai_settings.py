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


def misplaced_zep_key(zep_key, llm_key):
    """Catch known cross-provider mistakes without contacting either provider."""
    zep_key = (zep_key or '').strip()
    return bool(zep_key) and (zep_key == (llm_key or '').strip() or zep_key.startswith('sk-cp-'))


def public_settings():
    base = Config.LLM_BASE_URL or ''
    try:
        parsed = urlsplit(base)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            base = ''
    except ValueError:
        base = ''
        parsed = urlsplit('')
    return {
        'llm_configured': bool(Config.LLM_API_KEY),
        'zep_configured': bool(Config.ZEP_API_KEY),
        'zep_key_misplaced': misplaced_zep_key(Config.ZEP_API_KEY, Config.LLM_API_KEY),
        'llm_base_url': base,
        'llm_model_name': Config.LLM_MODEL_NAME or '',
        'minimax_key_type': ('m_plan' if (Config.LLM_API_KEY or '').startswith('sk-cp-') else 'api')
        if parsed.hostname == 'api.minimax.io' and Config.LLM_API_KEY else None,
    }


def _validate(data):
    if not isinstance(data, dict) or set(data) - (_FIELDS.keys() | {'minimax_key_type'}):
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
    key_type = data.get('minimax_key_type')
    if key_type not in (None, 'api', 'm_plan'):
        raise SettingsError('invalid')
    if parsed.hostname == 'api.minimax.io' and key_type and values['LLM_API_KEY']:
        actual_type = 'm_plan' if values['LLM_API_KEY'].startswith('sk-cp-') else 'api'
        if actual_type != key_type:
            raise SettingsError('keyTypeMismatch')
    if not all(values.values()):
        raise SettingsError('required')
    if misplaced_zep_key(values['ZEP_API_KEY'], values['LLM_API_KEY']):
        raise SettingsError('distinctZepKey')
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
