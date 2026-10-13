"""Current documented headless CLI interfaces. See docs/agent-providers.md.

These restrictions are CLI controls, not a filesystem/network sandbox. No preset
enables an unrestricted permission mode. User/managed CLI configuration may apply.
"""
import json
import os
from pathlib import Path


def _write(root: Path, name: str, value) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
    return str(path)


def build_command(provider, prompt: str, schema: dict, root: Path, env: dict):
    executable = os.environ.get('AGENT_BIN', provider.executable)
    name = provider.id
    model = os.environ.get('AGENT_MODEL', '').strip()
    model_args = ['--model', model] if model else []
    stdin = prompt
    if name == 'claude-code':
        args = [executable, '-p', '--input-format', 'text', '--output-format', 'json',
                '--safe-mode', '--restricted', '--tools', '', '--disallowedTools', '*',
                '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-session-persistence']
        output = 'result'
    elif name == 'antigravity':
        args = [executable, '--input-format', 'stream-json', '--output-format', 'stream-json']
        stdin = json.dumps({'event': 'user', 'message': {'content': prompt}}, ensure_ascii=False) + '\n'
        output = 'antigravity'
    elif name == 'cursor':
        args = [executable, '-p', prompt, '--output-format', 'json', '--mode', 'ask', '--workspace', str(root)]
        stdin, output = None, 'result'
    elif name == 'devin':
        config = _write(root, 'devin-config.json', {
            'permissions': {'deny': ['read', 'edit', 'grep', 'glob', 'exec', 'mcp__*']},
            'subagents_enabled': False,
            'read_config_from': {key: False for key in
                                 ['agents_standard', 'cursor', 'windsurf', 'claude', 'copilot', 'opencode', 'zed']},
        })
        file = _write(root, 'prompt.txt', prompt)
        args = [executable, '--config', config, '--respect-workspace-trust', 'false', '--prompt-file', file, '-p']
        stdin, output = None, 'raw'
    elif name == 'factory-droid':
        settings = _write(root, 'droid-settings.json', {'hooksDisabled': True})
        args = [executable, 'exec', '--output-format', 'json', '--settings', settings]
        output = 'result'
    elif name == 'gemini':
        policy = _write(root, 'deny-tools.toml', '[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n')
        _write(root, '.gemini/settings.json', {'hooksConfig': {'enabled': False}, 'skills': {'enabled': False}})
        args = [executable, '--output-format', 'json', '-e', 'none', '--admin-policy', policy]
        output = 'response'
    elif name == 'copilot':
        # Stdin activates programmatic mode. -p would discard piped input.
        args = [executable, '--silent', '--output-format', 'text', '--no-ask-user',
                '--disable-builtin-mcps', '--no-custom-instructions', '--no-auto-update']
        for tool in ['shell', 'write', 'read', 'url', 'memory']:
            args.extend(['--deny-tool', tool])
        output = 'raw'
    elif name == 'grok':
        args = [executable, '--no-auto-update', '-p', 'Complete the inference request supplied on stdin.',
                '--output-format', 'json', '--tools', 'read_file', '--disallowed-tools', 'read_file',
                '--deny', 'MCPTool', '--no-subagents', '--no-memory', '--disable-web-search', '--no-plan']
        model_args = ['-m', model] if model else []
        output = 'grok'
    elif name == 'kimi':
        agent = _write(root, 'inference.md', '---\nname: mirofish-inference\ndescription: Text inference only\ntools: []\nsubagents: []\n---\nReturn only the JSON requested by the supplied conversation.\n')
        skills = root / 'empty-skills'
        skills.mkdir()
        args = [executable, '-p', prompt, '--output-format', 'stream-json', '--agent-file', agent,
                '--skills-dir', str(skills)]
        stdin, output = None, 'kimi'
    elif name == 'opencode':
        _write(root, 'opencode.json', {'agents': {'mirofish-inference': {
            'mode': 'primary', 'system': 'Return only the JSON requested by the supplied conversation.',
            'permissions': [{'action': '*', 'resource': '*', 'effect': 'deny'}],
        }}})
        args = [executable, 'run', '--standalone', '--format', 'json', '--agent', 'mirofish-inference']
        output = 'opencode'
    elif name == 'pi':
        args = [executable, '--print', '--mode', 'text', '--no-session', '--no-tools',
                '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--no-approve']
        output = 'raw'
    elif name == 'qwen':
        args = [executable, '--safe-mode', '--output-format', 'json']
        output = 'qwen'
    elif name == 'hermes':
        # safe-mode also ignores model/provider config but still loads credentials;
        # preserve the selected endpoint instead of routing to Hermes defaults.
        args = [executable, 'chat', '--oneshot', '--quiet', '--ignore-rules', '--query-file', '-', '--format', 'stream-json']
        output = 'hermes'
    elif name == 'muse':
        file = _write(root, 'prompt.txt', prompt)
        args = [executable, 'exec', '--prompt-file', file, '--no-session-log']
        stdin, output = None, 'raw'
    else:
        from . import ProviderError
        raise ProviderError('No native CLI preset for this provider. Set AGENT_COMMAND_JSON.')
    return args + model_args, output, stdin
