"""
桌面版启动器的单元测试（不依赖 Windows / pywebview）

运行：
    python -m pytest desktop/tests -q
"""

import os
import sys

import pytest

DESKTOP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(os.path.dirname(DESKTOP_DIR), 'backend')

sys.path.insert(0, DESKTOP_DIR)
sys.path.insert(0, BACKEND_DIR)


DESKTOP_APP_PATH = os.path.join(DESKTOP_DIR, 'app.py')


def _load_desktop_module():
    """按文件路径加载 desktop/app.py（避免与后端的 app 包重名）。"""
    import importlib.util
    import uuid

    name = f'mirofish_desktop_{uuid.uuid4().hex[:8]}'
    spec = importlib.util.spec_from_file_location(name, DESKTOP_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def desktop_app(tmp_path, monkeypatch):
    """加载 desktop/app.py，并把数据目录指向临时目录。"""
    monkeypatch.setenv('MIROFISH_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('MIROFISH_DATA_DIR', raising=False)
    monkeypatch.delenv('MIROFISH_ENV_FILE', raising=False)
    yield _load_desktop_module()


def test_ensure_data_dir_creates_env_and_secret(desktop_app):
    root = desktop_app.ensure_data_dir()

    env_path = os.path.join(root, '.env')
    assert os.path.isfile(env_path)
    assert os.path.isdir(os.path.join(root, 'uploads'))

    content = open(env_path, encoding='utf-8').read()
    assert 'LLM_API_KEY=' in content
    assert 'ZEP_API_KEY=' in content
    assert 'SECRET_KEY=' in content

    # SECRET_KEY 应当是随机且足够长的
    secret = [line for line in content.splitlines() if line.startswith('SECRET_KEY=')][0]
    assert len(secret.split('=', 1)[1]) >= 32


def test_ensure_data_dir_is_idempotent(desktop_app):
    root = desktop_app.ensure_data_dir()
    env_path = os.path.join(root, '.env')

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write('LLM_API_KEY=keep-me\n')

    desktop_app.ensure_data_dir()
    assert 'keep-me' in open(env_path, encoding='utf-8').read()


def test_prepare_runtime_env_sets_isolated_paths(desktop_app, tmp_path):
    port = desktop_app.free_port(0)
    assert 1024 < port < 65536

    desktop_app.prepare_runtime_env(port)

    root = desktop_app.data_root()
    assert os.environ['MIROFISH_DATA_DIR'] == os.path.join(root, 'uploads')
    assert os.environ['MIROFISH_ENV_FILE'] == os.path.join(root, '.env')
    assert os.environ['MIROFISH_DESKTOP'] == '1'
    assert os.environ['FLASK_HOST'] == '127.0.0.1'
    assert os.environ['FLASK_PORT'] == str(port)
    assert os.environ['FLASK_DEBUG'] == 'false'
    assert os.path.isdir(desktop_app.backend_source_dir())


def test_backend_and_frontend_resolution(desktop_app):
    assert os.path.isfile(os.path.join(desktop_app.backend_source_dir(), 'app', '__init__.py'))
    dist = desktop_app.frontend_dist_dir()
    assert dist == '' or os.path.isfile(os.path.join(dist, 'index.html'))


def test_free_port_is_actually_free(desktop_app):
    import socket

    port = desktop_app.free_port(0)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', port))  # 不应抛异常


def test_spa_serves_index_and_assets(desktop_app, tmp_path, monkeypatch):
    """同一个端口既提供前端页面，也提供 /api 与 /health。"""
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html>mirofish-spa</html>', encoding='utf-8')
    (dist / 'assets' / 'app.js').write_text('console.log(1)', encoding='utf-8')

    monkeypatch.setattr(desktop_app, 'frontend_dist_dir', lambda: str(dist))
    desktop_app.prepare_runtime_env(desktop_app.free_port(0))
    client = desktop_app.start_backend(0).test_client()

    # 首页与前端路由深链接都回落到 index.html
    assert 'mirofish-spa' in client.get('/').get_data(as_text=True)
    assert 'mirofish-spa' in client.get('/simulation/abc/start').get_data(as_text=True)

    # 静态资源正常返回
    asset = client.get('/assets/app.js')
    assert asset.status_code == 200
    assert 'console.log' in asset.get_data(as_text=True)

    # API 不会被 SPA 回落吞掉
    assert client.get('/health').get_json()['status'] == 'ok'
    assert client.get('/api/desktop/status').get_json()['data']['desktop'] is True
    assert client.get('/api/not-exists').status_code == 404


def test_config_api_roundtrip(desktop_app):
    desktop_app.prepare_runtime_env(desktop_app.free_port(0))
    from app import create_app  # 后端包（backend/app）

    client = create_app().test_client()

    status = client.get('/api/desktop/status').get_json()['data']
    assert status['desktop'] is True
    assert status['configured'] is False

    payload = {
        'LLM_API_KEY': 'sk-unit-test-0001',
        'LLM_BASE_URL': 'https://api.deepseek.com/v1',
        'LLM_MODEL_NAME': 'deepseek-chat',
        'ZEP_API_KEY': 'z_unit_test_0001',
    }
    saved = client.post('/api/desktop/config', json=payload).get_json()
    assert saved['success'] is True

    env_path = os.environ['MIROFISH_ENV_FILE']
    content = open(env_path, encoding='utf-8').read()
    assert 'LLM_API_KEY=sk-unit-test-0001' in content
    assert 'ZEP_API_KEY=z_unit_test_0001' in content

    # 已知键被就地替换而不是追加
    assert content.count('LLM_API_KEY=') == 1

    status = client.get('/api/desktop/status').get_json()['data']
    assert status['configured'] is True

    # 未修改的脱敏值不应覆盖真实值
    masked = client.get('/api/desktop/config').get_json()['data']['LLM_API_KEY']['masked']
    assert masked != 'sk-unit-test-0001'
    client.post('/api/desktop/config', json={'LLM_API_KEY': masked})
    assert 'LLM_API_KEY=sk-unit-test-0001' in open(env_path, encoding='utf-8').read()


def test_config_api_rejects_unknown_keys(desktop_app):
    desktop_app.prepare_runtime_env(desktop_app.free_port(0))
    from app import create_app

    client = create_app().test_client()
    res = client.post('/api/desktop/config', json={'PATH': '/evil', 'LLM_API_KEY': 'x'})
    assert res.status_code == 200
    content = open(os.environ['MIROFISH_ENV_FILE'], encoding='utf-8').read()
    assert 'PATH=/evil' not in content


def test_icon_module_produces_valid_png_and_ico():
    sys.path.insert(0, DESKTOP_DIR)
    import icon

    png = icon.png_bytes(32)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'

    ico = icon.ico_bytes(sizes=(16, 32))
    assert ico[:4] == b'\x00\x00\x01\x00'
    count = int.from_bytes(ico[4:6], 'little')
    assert count == 2


def test_shipped_icon_is_windows_ready():
    ico_path = os.path.join(DESKTOP_DIR, 'icon.ico')
    if not os.path.exists(ico_path):
        pytest.skip('icon.ico 尚未生成（运行 desktop/fetch_sources.py）')

    data = open(ico_path, 'rb').read()
    assert data[:4] == b'\x00\x00\x01\x00'
    count = int.from_bytes(data[4:6], 'little')
    sizes = [data[6 + i * 16] or 256 for i in range(count)]
    assert 16 in sizes and 256 in sizes
