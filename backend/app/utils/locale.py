import json
import os
import threading
from flask import request, has_request_context

_thread_local = threading.local()

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

# Load language registry
with open(os.path.join(_locales_dir, 'languages.json'), 'r', encoding='utf-8') as f:
    _languages = json.load(f)

# Load translation files
_translations = {}
for filename in os.listdir(_locales_dir):
    if filename.endswith('.json') and filename != 'languages.json':
        locale_name = filename[:-5]
        with open(os.path.join(_locales_dir, filename), 'r', encoding='utf-8') as f:
            _translations[locale_name] = json.load(f)


def set_locale(locale: str):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = _normalize_locale(locale)


def _normalize_locale(raw: str | None) -> str:
    if not raw:
        return 'en'
    candidates = []
    for part in raw.split(','):
        code = part.split(';')[0].strip().lower().replace('_', '-')
        if code:
            candidates.append(code)
            if '-' in code:
                candidates.append(code.split('-')[0])
    for code in candidates:
        if code in _languages or code in _translations:
            return code
    return 'en'


def get_locale() -> str:
    if has_request_context():
        return _normalize_locale(request.headers.get('Accept-Language', 'en'))
    return getattr(_thread_local, 'locale', 'en')


def t(key: str, **kwargs) -> str:
    locale = get_locale()
    messages = _translations.get(locale, _translations.get('en', _translations.get('zh', {})))

    value = messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        value = _translations.get('en', _translations.get('zh', {}))
        for part in key.split('.'):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break

    if value is None:
        return key

    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_instruction() -> str:
    locale = get_locale()
    lang_config = _languages.get(locale, _languages.get('en', {}))
    instruction = lang_config.get('llmInstruction', 'Please respond in English.')
    return (
        f"{instruction} Use this language for every natural-language field, report title, "
        f"section title, explanation, quote translation, generated social post, interview question, "
        f"interview answer, and reasoning text. Keep JSON keys, enum values, IDs, entity type names, "
        f"relationship type names, and code-like values in their required machine-readable format."
    )
