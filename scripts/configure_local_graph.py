"""Create private local-mode settings without displaying or replacing existing secrets."""
import os
from pathlib import Path
import re
import secrets

root = Path(__file__).resolve().parents[1]
path = root / '.env'
text = path.read_text() if path.exists() else (root / '.env.example').read_text()
for key, value in {'LLM_PROVIDER': 'codex', 'GRAPH_PROVIDER': 'graphiti',
                   'LOCAL_GRAPH_URL': 'http://127.0.0.1:5002',
                   'LOCAL_NEO4J_URI': 'bolt://127.0.0.1:7687',
                   'LOCAL_GRAPH_TOKEN': None, 'LOCAL_NEO4J_PASSWORD': None}.items():
    pattern = re.compile(r'^' + key + r'=([^\n]*)$', re.MULTILINE)
    match = pattern.search(text)
    if value is None:
        existing = match.group(1).strip().strip('\"\'') if match else ''
        if existing and not existing.startswith('your_'):
            continue
        value = secrets.token_hex(24)
    line = key + '=' + value
    text = pattern.sub(lambda _: line, text) if match else text.rstrip() + '\n' + line + '\n'
fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write(text)
print('Local mode configured in .env. Existing secrets preserved; no secrets displayed.')
