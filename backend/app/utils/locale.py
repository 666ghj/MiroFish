import json
import os

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

# English is the only language SoSim ships. The catalogue is shared with the
# frontend, which imports the same file, so keys stay in one place.
with open(os.path.join(_locales_dir, 'en.json'), 'r', encoding='utf-8') as f:
    _messages = json.load(f)

# Appended to every LLM system prompt - ontology, agent profile, simulation
# config, report and sub-query - so the model answers in the product language.
LANGUAGE_INSTRUCTION = 'Please respond in English.'


def t(key: str, **kwargs) -> str:
    """Resolve a dotted message key, substituting {name} placeholders."""
    value = _messages
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if not isinstance(value, str):
        return key

    for name, replacement in kwargs.items():
        value = value.replace('{' + name + '}', str(replacement))

    return value


def get_language_instruction() -> str:
    """Return the language instruction appended to LLM system prompts."""
    return LANGUAGE_INSTRUCTION
