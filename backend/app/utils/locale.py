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


def resolve_locale(locale: str) -> str | None:
    """Match a language tag to an installed catalog, including Portuguese aliases."""
    tag = locale.strip().replace('_', '-').lower()
    available = {name.lower(): name for name in _translations}
    if tag in available:
        return available[tag]
    if tag.split('-')[0] == 'pt' and 'pt-br' in available:
        return available['pt-br']
    return available.get(tag.split('-')[0])


def set_locale(locale: str):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = resolve_locale(locale) or 'zh'


def get_locale() -> str:
    if has_request_context():
        for language, quality in request.accept_languages:
            if quality > 0 and (matched := resolve_locale(language)):
                return matched
        return 'zh'
    return getattr(_thread_local, 'locale', 'zh')


def t(key: str, **kwargs) -> str:
    locale = get_locale()
    messages = _translations.get(locale, _translations.get('zh', {}))

    value = messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        value = _translations.get('zh', {})
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
    lang_config = _languages.get(locale, _languages.get('zh', {}))
    return lang_config.get('llmInstruction', '请使用中文回答。')


def get_output_language() -> str:
    """Optional CAMEL output language for newly created simulation agents."""
    return _languages.get(get_locale(), {}).get('outputLanguage', '')
