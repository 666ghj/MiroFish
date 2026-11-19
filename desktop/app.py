"""
MiroFish Desktop —— 桌面版启动器（Windows）

职责：
  1. 找到用户可写的数据目录（%APPDATA%\\MiroFish 或安装目录旁的 data\\），
     首次启动时写入默认 .env 模板并生成高熵 SECRET_KEY。
  2. 启动内嵌的 Flask 后端（仅监听 127.0.0.1，随机空闲端口），
     同时把前端构建产物作为静态资源挂在同一个端口上，
     因此桌面端不存在跨域 / 端口写死的问题。
  3. 用 pywebview（Windows 上是 WebView2 / Edge）打开原生窗口。
  4. 后端日志与子进程（OASIS 模拟）在退出时统一回收。

命令行参数：
  --desktop        隐藏控制台、直接进桌面模式（打包后的 MiroFish.exe 默认行为）
  --headless       只启动本地服务，不打开窗口（便于排错，输出访问地址）
  --port N         指定端口（默认自动选择空闲端口）
  --debug          打开 pywebview 的调试能力
"""

import base64
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser

APP_NAME = 'MiroFish'


def _read_version() -> str:
    root = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(root, 'version.txt'),
                      os.path.join(os.path.dirname(root), 'desktop', 'version.txt')):
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding='utf-8') as f:
                    value = f.read().strip()
                if value:
                    return value
            except OSError:
                pass
    return '0.1.0'


VERSION = _read_version()
DEFAULT_WIDTH = 1440
DEFAULT_HEIGHT = 920

ENV_TEMPLATE = """\
# ===== MiroFish 桌面版配置文件 =====
# 这个文件保存在你的用户数据目录中，升级软件不会被覆盖。
# 修改下面的 API Key 后，重启 MiroFish 即可生效。

# ---- LLM 配置（支持任意 OpenAI 兼容接口）----
# 例如阿里百炼: https://dashscope.aliyuncs.com/compatible-mode/v1  /  qwen-plus
#     OpenAI  : https://api.openai.com/v1                          /  gpt-4o-mini
#     DeepSeek: https://api.deepseek.com/v1                        /  deepseek-chat
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# ---- Zep Cloud 记忆图谱（https://app.getzep.com/）----
ZEP_API_KEY=

# ---- 可选：加速 LLM ----
# LLM_BOOST_API_KEY=
# LLM_BOOST_BASE_URL=
# LLM_BOOST_MODEL_NAME=

# ---- 可选：模拟参数 ----
# OASIS_DEFAULT_MAX_ROUNDS=10
"""


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def app_root() -> str:
    """打包后为 exe 所在目录；源码运行时为仓库根目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_root() -> str:
    """只读资源目录（前端构建产物、内置 Python 运行时）。"""
    if is_frozen():
        # PyInstaller onedir: 资源在 _internal 目录
        return getattr(sys, '_MEIPASS', app_root())
    return app_root()


def data_root() -> str:
    """可写数据目录。"""
    if os.environ.get('MIROFISH_HOME'):
        return os.path.abspath(os.environ['MIROFISH_HOME'])

    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~\\AppData\\Roaming')
        return os.path.join(base, APP_NAME)
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    return os.path.join(base, APP_NAME)


def ensure_data_dir() -> str:
    """准备数据目录与 .env，返回数据目录。"""
    root = data_root()
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, 'uploads'), exist_ok=True)
    os.makedirs(os.path.join(root, 'logs'), exist_ok=True)

    env_path = os.path.join(root, '.env')
    if not os.path.exists(env_path):
        content = ENV_TEMPLATE + f"\nSECRET_KEY={secrets.token_hex(32)}\n"
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)

    return root


def env_file() -> str:
    return os.path.join(data_root(), '.env')


# --------------------------------------------------------------------------- #
# 后端
# --------------------------------------------------------------------------- #
def backend_source_dir() -> str:
    root = resource_root()
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(root, 'backend'),
                      os.path.join(root, 'app', 'backend'),
                      os.path.join(here, 'backend'),
                      os.path.join(root, 'resources', 'backend')):
        if os.path.isdir(candidate):
            return candidate
    raise RuntimeError('找不到后端代码目录（backend/），安装包可能不完整。')


def frontend_dist_dir() -> str:
    root = resource_root()
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(root, 'frontend', 'dist'),
                      os.path.join(root, 'app', 'frontend_dist'),
                      os.path.join(here, 'frontend_dist'),
                      os.path.join(root, 'resources', 'frontend_dist')):
        if os.path.isdir(candidate):
            return candidate
    return ''


def free_port(preferred: int = 0) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def prepare_runtime_env(port: int) -> None:
    """桌面模式下的环境变量与 sys.path 设置。"""
    root = ensure_data_dir()

    os.environ['MIROFISH_DATA_DIR'] = os.path.join(root, 'uploads')
    os.environ['MIROFISH_ENV_FILE'] = env_file()
    os.environ['MIROFISH_DESKTOP'] = '1'
    os.environ['MIROFISH_VERSION'] = VERSION
    os.environ['FLASK_HOST'] = '127.0.0.1'
    os.environ['FLASK_PORT'] = str(port)
    # 桌面版关闭 Flask debug（否则会拉起 reloader 子进程）
    os.environ['FLASK_DEBUG'] = 'false'
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

    backend_dir = backend_source_dir()
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    scripts_dir = os.path.join(backend_dir, 'scripts')
    if os.path.isdir(scripts_dir) and scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def log_file() -> str:
    os.makedirs(os.path.join(data_root(), 'logs'), exist_ok=True)
    return os.path.join(data_root(), 'logs', 'desktop.log')


class _Tee(object):
    """把输出同时写到控制台与日志文件（打包后没有控制台也不会出错）。"""

    def __init__(self, stream, fileobj):
        self.stream = stream
        self.fileobj = fileobj

    def write(self, data):
        try:
            if self.stream is not None:
                self.stream.write(data)
        except Exception:
            pass
        try:
            self.fileobj.write(data)
            self.fileobj.flush()
        except Exception:
            pass

    def flush(self):
        for target in (self.stream, self.fileobj):
            try:
                if target is not None:
                    target.flush()
            except Exception:
                pass


def start_logging() -> None:
    try:
        fh = open(log_file(), 'a', encoding='utf-8', buffering=1)
    except Exception:
        return
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)


def start_backend(port: int):
    """创建 Flask 应用并挂载前端静态文件。返回 app。"""
    from flask import Flask, send_from_directory

    from app import create_app

    app = create_app()
    dist = frontend_dist_dir()

    if dist:
        dist_abs = os.path.abspath(dist)

        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_spa(path):
            # API 与健康检查交给 Flask 自己的路由处理
            if path.startswith(('api/', 'health')):
                return {'success': False, 'error': 'Not Found'}, 404
            candidate = os.path.join(dist_abs, path)
            if path and os.path.isfile(candidate):
                return send_from_directory(dist_abs, path)
            # vue-router history 模式：其余路径回落到 index.html
            return send_from_directory(dist_abs, 'index.html')

    return app


def run_server(app, port: int) -> None:
    """使用 waitress 启动（Windows 上比 werkzeug 更稳，且不会开 reloader）。"""
    try:
        from waitress import serve
        serve(app, host='127.0.0.1', port=port, threads=16, channel_timeout=1800,
              clear_untrusted_proxy_headers=True)
    except ImportError:
        app.run(host='127.0.0.1', port=port, debug=False, threaded=True, use_reloader=False)


def wait_until_ready(port: int, timeout: float = 90.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    url = f'http://127.0.0.1:{port}/health'
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def icon_path() -> str:
    """返回窗口图标路径（可选，缺失时退回无图标）。"""
    root = resource_root()
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(root, 'app', 'icon.png'),
                      os.path.join(here, 'icon.png'),
                      os.path.join(root, 'icon.png')):
        if os.path.exists(candidate):
            return candidate

    # 兜底：用纯标准库生成一个
    try:
        from icon import png_bytes
        path = os.path.join(data_root(), 'mirofish-icon.png')
        if not os.path.exists(path):
            with open(path, 'wb') as f:
                f.write(png_bytes(256))
        return path
    except Exception:
        return ''


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run(headless: bool = False, port: int = 0, debug: bool = False) -> int:
    start_logging()
    port = free_port(port)

    print(f'[MiroFish] 版本 {VERSION}')
    print(f'[MiroFish] 数据目录: {data_root()}')

    prepare_runtime_env(port)
    app = start_backend(port)

    server_thread = threading.Thread(target=run_server, args=(app, port), daemon=True,
                                     name='mirofish-http')
    server_thread.start()

    url = f'http://127.0.0.1:{port}/'
    ready = wait_until_ready(port)
    print(f'[MiroFish] 本地服务 {"已就绪" if ready else "启动超时"}: {url}')

    if headless:
        print('[MiroFish] headless 模式，按 Ctrl+C 退出')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    def on_closed():
        print('[MiroFish] 窗口已关闭，正在退出...')
        os._exit(0)

    import webview

    window = webview.create_window(
        f'{APP_NAME} — 群体智能预测引擎',
        url,
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        min_size=(1024, 700),
        background_color='#091426',
    )
    window.events.closed += on_closed

    icon = icon_path()
    webview.start(debug=debug, private_mode=False,
                  storage_path=os.path.join(data_root(), 'webview'),
                  icon=icon if os.path.exists(icon) else None)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    headless = '--headless' in argv
    debug = '--debug' in argv
    port = 0
    for i, arg in enumerate(argv):
        if arg == '--port' and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                pass

    if '--browser' in argv:
        # 用系统默认浏览器打开（WebView2 不可用时的兜底方案）
        import webbrowser as _wb
        port = free_port(port)
        prepare_runtime_env(port)
        app = start_backend(port)
        threading.Thread(target=run_server, args=(app, port), daemon=True).start()
        wait_until_ready(port)
        _wb.open(f'http://127.0.0.1:{port}/')
        print('[MiroFish] 已在浏览器中打开，关闭此窗口即退出服务')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    try:
        return run(headless=headless, port=port, debug=debug)
    except Exception:
        import traceback
        traceback.print_exc()
        if not headless:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None,
                    'MiroFish 启动失败。\n\n详细信息见日志:\n' + log_file(),
                    'MiroFish', 0x10)
            except Exception:
                pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
