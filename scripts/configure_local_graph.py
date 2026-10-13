"""Create private local-mode settings without displaying or replacing existing secrets."""
import os
from pathlib import Path
import re
import secrets
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--provider', help='Inference provider ID; defaults to the existing selection, then codex')
args = parser.parse_args()
if args.provider and not re.fullmatch(r'[a-z][a-z0-9-]*', args.provider):
    parser.error('--provider must be a provider ID, for example claude-code or gemini')

root = Path(__file__).resolve().parents[1]
path = root / '.env'
text = path.read_text() if path.exists() else (root / '.env.example').read_text()


def assignment_pattern(key):
    return re.compile(r'^[ \t]*(?:export[ \t]+)?' + re.escape(key) +
                      r'[ \t]*=[ \t]*([^\n]*)$', re.MULTILINE)


def is_empty(raw):
    return bool(re.fullmatch(r'[ \t]*(?:\"\"|\'\')?[ \t]*(?:#.*)?', raw))


provider_matches = list(assignment_pattern('LLM_PROVIDER').finditer(text))
# Leave the original assignment(s) intact so dotenv retains quoting, interpolation,
# comments, and last-assignment-wins behavior. Only --provider replaces a selection.
provider = args.provider
if provider is None and (not provider_matches or is_empty(provider_matches[-1].group(1))):
    provider = 'codex'
settings = {'GRAPH_PROVIDER': 'graphiti',
                   'LOCAL_GRAPH_URL': 'http://127.0.0.1:5002',
                   'LOCAL_NEO4J_URI': 'bolt://127.0.0.1:7687',
                   'LOCAL_GRAPH_TOKEN': None, 'LOCAL_NEO4J_PASSWORD': None}
if provider is not None:
    settings['LLM_PROVIDER'] = provider
for key, value in settings.items():
    pattern = assignment_pattern(key)
    matches = list(pattern.finditer(text))
    match = matches[-1] if matches else None
    if value is None:
        existing = match.group(1).strip() if match else ''
        if not is_empty(existing) and not existing.lstrip('\"\'').startswith('your_'):
            continue
        value = secrets.token_hex(24)
    line = key + '=' + value
    text = pattern.sub(lambda _: line, text) if match else text.rstrip() + '\n' + line + '\n'
fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write(text)
print('Local mode configured in .env. Existing secrets preserved; no secrets displayed.')
