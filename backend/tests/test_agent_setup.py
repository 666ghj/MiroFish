import json
from pathlib import Path
import subprocess
import sys
import pytest
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]


def test_local_setup_preserves_provider_and_secrets(tmp_path):
    (tmp_path / 'scripts').mkdir()
    script = tmp_path / 'scripts/configure_local_graph.py'
    script.write_text((ROOT / 'scripts/configure_local_graph.py').read_text())
    env = tmp_path / '.env'
    env.write_text('LLM_PROVIDER=claude-code\nLOCAL_GRAPH_TOKEN=keep-token\nLOCAL_NEO4J_PASSWORD=keep-password\n')
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert 'LLM_PROVIDER=claude-code' in env.read_text()
    assert 'LOCAL_GRAPH_TOKEN=keep-token' in env.read_text()
    subprocess.run([sys.executable, str(script), '--provider', 'gemini'], check=True, capture_output=True)
    assert 'LLM_PROVIDER=gemini' in env.read_text()
    assert 'LOCAL_NEO4J_PASSWORD=keep-password' in env.read_text()


def test_check_agent_dry_run_does_not_execute_provider(tmp_path):
    import os
    executable = tmp_path / 'never-run'
    marker = tmp_path / 'executed'
    executable.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
    executable.chmod(0o700)
    env = {**os.environ, 'AGENT_COMMAND_JSON': json.dumps([str(executable)])}
    result = subprocess.run([sys.executable, str(ROOT / 'backend/scripts/check_agent.py'),
                             '--provider', 'claude-code'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'claude-code' in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize('source,selected', [
    ('export LLM_PROVIDER=gemini\n', 'gemini'),
    ('LLM_PROVIDER = gemini # my provider\n', 'gemini'),
    ('LLM_PROVIDER=gemini\nLLM_PROVIDER=cursor\n', 'cursor'),
    ('LLM_PROVIDER="claude-code"\n', 'claude-code'),
])
def test_local_setup_respects_dotenv_assignment_syntax(tmp_path, source, selected):
    (tmp_path / 'scripts').mkdir()
    script = tmp_path / 'scripts/configure_local_graph.py'
    script.write_text((ROOT / 'scripts/configure_local_graph.py').read_text())
    env = tmp_path / '.env'
    env.write_text(source + 'export LOCAL_GRAPH_TOKEN = "keep-token"\nLOCAL_NEO4J_PASSWORD = keep-password\n')
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    result = dotenv_values(env)
    assert result['LLM_PROVIDER'] == selected
    assert result['LOCAL_GRAPH_TOKEN'] == 'keep-token'
    assert result['LOCAL_NEO4J_PASSWORD'] == 'keep-password'
    subprocess.run([sys.executable, str(script), '--provider', 'pi'], check=True, capture_output=True)
    assert dotenv_values(env)['LLM_PROVIDER'] == 'pi'
