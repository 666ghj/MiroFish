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
    if locale and locale in _translations:
        _thread_local.locale = locale
    elif locale and locale.lower().startswith('pt'):
        _thread_local.locale = 'pt-BR'
    elif locale and locale.lower().startswith('en'):
        _thread_local.locale = 'en'
    elif locale and locale.lower().startswith('zh'):
        _thread_local.locale = 'zh'
    else:
        _thread_local.locale = os.getenv('DEFAULT_LOCALE', 'en')


def get_locale() -> str:
    # 1. Thread-local if explicitly set
    thread_loc = getattr(_thread_local, 'locale', None)
    if thread_loc and thread_loc in _translations:
        return thread_loc

    # 2. Check request context if present
    if has_request_context():
        # Custom header (e.g. X-Locale or X-Language)
        custom_header = request.headers.get('X-Locale') or request.headers.get('X-Language')
        if custom_header:
            if custom_header in _translations:
                return custom_header
            if custom_header.lower().startswith('pt') and 'pt-BR' in _translations:
                return 'pt-BR'
            if custom_header.lower().startswith('en') and 'en' in _translations:
                return 'en'

        # Check JSON payload if available
        try:
            if request.is_json and request.json:
                req_loc = request.json.get('locale') or request.json.get('language')
                if req_loc:
                    if req_loc in _translations:
                        return req_loc
                    if req_loc.lower().startswith('pt') and 'pt-BR' in _translations:
                        return 'pt-BR'
                    if req_loc.lower().startswith('en') and 'en' in _translations:
                        return 'en'
        except Exception:
            pass

        # Check Accept-Language
        accept_lang = request.headers.get('Accept-Language')
        if accept_lang:
            if accept_lang in _translations:
                return accept_lang
            for part in accept_lang.split(','):
                tag = part.split(';')[0].strip()
                if tag in _translations:
                    return tag
                tag_lower = tag.lower()
                if tag_lower.startswith('pt') and 'pt-BR' in _translations:
                    return 'pt-BR'
                if tag_lower.startswith('en') and 'en' in _translations:
                    return 'en'
                if tag_lower.startswith('zh') and 'zh' in _translations:
                    return 'zh'

    # 3. Default fallback: DEFAULT_LOCALE env or 'en'
    default_loc = os.getenv('DEFAULT_LOCALE', 'en')
    return default_loc if default_loc in _translations else 'en'


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
    lang_config = _languages.get(locale, _languages.get('en', _languages.get('zh', {})))
    return lang_config.get('llmInstruction', 'Please respond in English.')
