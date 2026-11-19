"""
桌面版专用接口

只在本机桌面版中启用（由启动器设置 MIROFISH_DESKTOP=1）：
  GET  /api/desktop/config        读取当前配置（Key 脱敏）
  POST /api/desktop/config        保存配置到用户数据目录的 .env
  POST /api/desktop/config/test   测试 LLM / Zep 连通性
  GET  /api/desktop/status        运行环境信息
"""

import os
import re

from flask import jsonify, request

from . import desktop_bp
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.desktop')

MANAGED_KEYS = [
    'LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL_NAME',
    'LLM_BOOST_API_KEY', 'LLM_BOOST_BASE_URL', 'LLM_BOOST_MODEL_NAME',
    'ZEP_API_KEY', 'OASIS_DEFAULT_MAX_ROUNDS',
]

# 允许通过本接口写入的键，防止任意环境变量注入
_KEY_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


def env_path() -> str:
    return os.environ.get('MIROFISH_ENV_FILE') or os.path.join(
        os.path.dirname(__file__), '../../../.env')


def mask(value: str) -> str:
    if not value:
        return ''
    if len(value) <= 8:
        return '*' * len(value)
    return f'{value[:4]}****...{value[-4:]}'


def read_env() -> dict:
    data = {}
    path = env_path()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                data[key.strip()] = value.strip()
    return data


def write_env(updates: dict) -> None:
    path = env_path()
    lines = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.partition('=')[0].strip()
            if key in remaining:
                out.append(f'{key}={remaining.pop(key)}')
                continue
        out.append(line)

    for key, value in remaining.items():
        out.append(f'{key}={value}')

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out).rstrip('\n') + '\n')


def apply_to_runtime(updates: dict) -> None:
    """让修改立即生效（不重启进程）。"""
    for key, value in updates.items():
        os.environ[key] = value
        if hasattr(Config, key):
            setattr(Config, key, value)
        # 进程内的 LLM 客户端通常会缓存在模块层，这里只更新环境变量与 Config，
        # 新建的客户端会读取新值。


@desktop_bp.route('/config', methods=['GET'])
def get_config():
    env = read_env()
    payload = {}
    for key in MANAGED_KEYS:
        value = env.get(key) or os.environ.get(key, '')
        payload[key] = {'value': value, 'masked': mask(value)}
    payload['env_file'] = env_path()
    payload['configured'] = bool(payload['LLM_API_KEY']['value'] and payload['ZEP_API_KEY']['value'])
    return jsonify({'success': True, 'data': payload})


@desktop_bp.route('/config', methods=['POST'])
def save_config():
    body = request.get_json(silent=True) or {}
    updates = {}
    for key, value in body.items():
        if key not in MANAGED_KEYS or not _KEY_RE.match(key):
            continue
        value = '' if value is None else str(value).strip()
        # 用户提交的是脱敏值（未修改）时跳过
        if value and '*' in value and '...' in value:
            continue
        updates[key] = value

    if not updates:
        return jsonify({'success': False, 'error': '没有需要保存的配置项'}), 400

    try:
        write_env(updates)
        apply_to_runtime(updates)
        logger.info(f'桌面版配置已更新: {sorted(updates)}')
        return jsonify({'success': True, 'data': {'env_file': env_path(), 'updated': sorted(updates)}})
    except Exception as exc:  # noqa: BLE001
        logger.error(f'保存配置失败: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


def _test_llm(base_url: str, api_key: str, model: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0, max_retries=0)
    resp = client.chat.completions.create(
        model=model,
        messages=[{'role': 'user', 'content': '回复两个字：可用'}],
        max_tokens=16,
    )
    text = (resp.choices[0].message.content or '').strip()
    return {'ok': True, 'detail': f'模型返回：{text[:40]}'}


def _test_zep(api_key: str) -> dict:
    from zep_cloud.client import Zep

    client = Zep(api_key=api_key)
    # 按时间列出 1 个用户即视为凭据有效（不同版本方法名不同，逐一尝试）
    last_error = None
    for call in (
        lambda: client.user.list_ordered(page_number=1, page_size=1),
        lambda: client.user.list_ordered(),
    ):
        try:
            call()
            return {'ok': True, 'detail': 'Zep 凭据有效'}
        except AttributeError as exc:
            last_error = exc
            continue
        except TypeError as exc:
            last_error = exc
            continue
    raise last_error or RuntimeError('Zep 客户端不可用')


@desktop_bp.route('/config/test', methods=['POST'])
def test_config():
    body = request.get_json(silent=True) or {}
    env = read_env()

    def pick(key, default=''):
        return (body.get(key) or env.get(key) or os.environ.get(key) or default).strip()

    results = {}

    base_url = pick('LLM_BASE_URL', 'https://api.openai.com/v1')
    model = pick('LLM_MODEL_NAME', 'gpt-4o-mini')
    llm_key = pick('LLM_API_KEY')
    if not llm_key:
        results['llm'] = {'ok': False, 'detail': '未填写 LLM_API_KEY'}
    else:
        try:
            results['llm'] = _test_llm(base_url, llm_key, model)
        except Exception as exc:  # noqa: BLE001
            results['llm'] = {'ok': False, 'detail': f'{type(exc).__name__}: {exc}'[:300]}

    zep_key = pick('ZEP_API_KEY')
    if not zep_key:
        results['zep'] = {'ok': False, 'detail': '未填写 ZEP_API_KEY'}
    else:
        try:
            results['zep'] = _test_zep(zep_key)
        except Exception as exc:  # noqa: BLE001
            results['zep'] = {'ok': False, 'detail': f'{type(exc).__name__}: {exc}'[:300]}

    return jsonify({'success': True, 'data': results})


@desktop_bp.route('/update-check', methods=['GET'])
def update_check():
    """检查是否有新版本（静默失败：离线 / 私有仓库时不影响使用）。"""
    import urllib.request
    import json

    repo = os.environ.get('MIROFISH_REPO', 'cfunkycreations-tech/MiroFish')
    current = os.environ.get('MIROFISH_VERSION', '0.1.0')
    url = f'https://api.github.com/repos/{repo}/releases/latest'

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MiroFish-Desktop'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.load(resp)
        latest = (data.get('tag_name') or '').lstrip('v')
        assets = [a.get('name', '') for a in data.get('assets', [])]
        return jsonify({
            'success': True,
            'data': {
                'current': current,
                'latest': latest,
                'update_available': bool(latest) and latest != current,
                'url': data.get('html_url', ''),
                'assets': assets,
            },
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': True, 'data': {'current': current, 'update_available': False,
                                                  'error': str(exc)[:200]}})


@desktop_bp.route('/status', methods=['GET'])
def status():
    import sys
    data_dir = Config.UPLOAD_FOLDER
    return jsonify({
        'success': True,
        'data': {
            'desktop': os.environ.get('MIROFISH_DESKTOP') == '1',
            'python': sys.version.split()[0],
            'data_dir': os.path.abspath(data_dir),
            'env_file': env_path(),
            'configured': bool(Config.LLM_API_KEY and Config.ZEP_API_KEY),
        },
    })
