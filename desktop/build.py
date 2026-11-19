"""
MiroFish 桌面版（Windows x64）打包脚本

支持两种产物：

  --mode offline   完整离线版：内置 Python 运行时 + 全部依赖，解压即用（约 1 GB 未压缩）
  --mode setup     在线安装版：只有启动器 + 源码 + Setup.bat，首次运行自动下载依赖（约 1-2 MB）

产物结构（两种模式共用同一套目录约定）：

    MiroFish-0.1.0-windows-x64/
      MiroFish.exe            双击启动（无控制台）
      MiroFish-Console.bat    排错：带控制台 + 日志
      Setup.bat               在线版必用：初始化 Python 运行时
      README.txt / LICENSE / .env.example
      app/
        app.py                桌面启动器（Flask + pywebview）
        icon.py
        backend/              后端源码（含 requirements-desktop.txt）
        frontend_dist/        前端构建产物
      runtime/python/         [仅 offline] 内置 Python 与依赖
      runtime/venv/           [在线版首次运行后生成]

用法：
    # 1) 准备素材（Windows 依赖、embeddable Python、MiroFish.exe）
    python desktop/fetch_sources.py --build-dir build

    # 2) 打包（先构建前端）
    cd frontend && npm ci && npm run build && cd ..
    python desktop/build.py --mode offline --out dist
    python desktop/build.py --mode setup   --out dist
"""

import argparse
import os
import shutil
import sys
import zipfile

APP_NAME = 'MiroFish'
def _read_version() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'version.txt')
    try:
        with open(path, encoding='utf-8') as f:
            return f.read().strip() or '0.1.0'
    except OSError:
        return '0.1.0'


VERSION = _read_version()
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP_DIR = os.path.join(REPO_ROOT, 'desktop')

BACKEND_EXCLUDE_DIRS = {'uploads', 'logs', '__pycache__', '.pytest_cache'}
BACKEND_EXCLUDE_FILES = {'.env'}


def log(msg):
    print(f'[build] {msg}', flush=True)


def rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


def copy_tree(src, dst, ignore=None):
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def assemble_app(stage):
    app_dir = os.path.join(stage, 'app')
    os.makedirs(app_dir, exist_ok=True)
    for name in ('app.py', 'icon.py', 'version.txt'):
        src = os.path.join(DESKTOP_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(app_dir, name))
    # 应用图标（窗口图标 / 任务栏图标）
    for name in ('icon.png', 'icon.ico'):
        src = os.path.join(DESKTOP_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(app_dir, name))


def assemble_backend(stage):
    dst = os.path.join(stage, 'app', 'backend')
    log(f'复制后端源码 -> {dst}')

    def _ignore(directory, names):
        out = []
        for name in names:
            if name in BACKEND_EXCLUDE_DIRS or name in BACKEND_EXCLUDE_FILES:
                out.append(name)
            elif name.endswith('.pyc'):
                out.append(name)
        return out

    copy_tree(os.path.join(REPO_ROOT, 'backend'), dst, ignore=_ignore)


def assemble_frontend(stage):
    src = os.path.join(REPO_ROOT, 'frontend', 'dist')
    if not os.path.isdir(src):
        raise SystemExit('frontend/dist 不存在，请先运行: cd frontend && npm ci && npm run build')
    dst = os.path.join(stage, 'app', 'frontend_dist')
    log(f'复制前端产物 -> {dst}')
    copy_tree(src, dst)


def write_requirements(stage):
    src = os.path.join(DESKTOP_DIR, 'requirements-desktop.txt')
    dst = os.path.join(stage, 'app', 'backend', 'requirements-desktop.txt')
    shutil.copy2(src, dst)


def populate_runtime(stage, wheels_dir, embed_dir):
    py_dir = os.path.join(stage, 'runtime', 'python')
    log(f'复制 Python 运行时 -> {py_dir}')
    copy_tree(embed_dir, py_dir)

    for name in os.listdir(py_dir):
        if name.endswith('._pth'):
            os.remove(os.path.join(py_dir, name))
    pth_name = next((n for n in os.listdir(py_dir) if n.startswith('python3') and n.endswith('.zip')), 'python312.zip')
    with open(os.path.join(py_dir, pth_name.replace('.zip', '._pth')), 'w', encoding='utf-8') as f:
        f.write(f'{pth_name}\n.\nLib\\site-packages\n\nimport site\n')

    site_packages = os.path.join(py_dir, 'Lib', 'site-packages')
    os.makedirs(site_packages, exist_ok=True)
    log(f'复制 Windows 依赖 -> {site_packages}')
    copy_tree(wheels_dir, site_packages,
              ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyi'))


def copy_tools(stage, tools_dir):
    """拷贝 uv.exe 等工具（在线安装版用它们安装依赖）。"""
    if not tools_dir or not os.path.isdir(tools_dir):
        return
    dst = os.path.join(stage, 'tools')
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(tools_dir):
        src = os.path.join(tools_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst, name))
    log(f'工具 -> {dst}')


def write_console_bat(stage):
    path = os.path.join(stage, f'{APP_NAME}-Console.bat')
    with open(path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('@echo off\n'
                'chcp 65001 >nul\n'
                'title MiroFish 控制台\n'
                'cd /d "%~dp0"\n'
                'echo 正在启动 MiroFish（关闭此窗口即退出程序）...\n'
                'echo 如果窗口一闪而过，请先在 MiroFish.exe 同目录查看 Setup.bat 是否执行成功。\n'
                'echo.\n'
                f'"{APP_NAME}.exe" --console --headless\n'
                'pause\n')


def write_readme(stage, mode):
    offline = mode == 'offline'
    extra = ('本安装包已内置 Python 运行时与全部依赖，无需联网、无需安装 Python。\n'
             if offline else
             '本安装包为在线安装版：首次双击 MiroFish.exe 会提示自动下载运行环境\n'
             '（约 500 MB - 1 GB），完成后即可离线使用。也可手动双击 Setup.bat。\n')
    text = f"""MiroFish {VERSION} · Windows x64 桌面版
=================================================

一、启动
{extra}
    双击 MiroFish.exe 即可。数据与配置保存在：
        %APPDATA%\\MiroFish\\
            .env              配置文件（LLM / Zep 的 API Key）
            uploads\\          上传文档、图谱、模拟与报告
            logs\\desktop.log  运行日志
    升级软件不会覆盖你的配置与数据。

二、首次使用必须填写 API Key
    1. 用记事本打开 %APPDATA%\\MiroFish\\.env
    2. 填写：
           LLM_API_KEY      大模型 API Key（任意 OpenAI 兼容接口）
           LLM_BASE_URL     接口地址，如 https://dashscope.aliyuncs.com/compatible-mode/v1
           LLM_MODEL_NAME   模型名，如 qwen-plus
           ZEP_API_KEY      Zep Cloud 记忆图谱 Key（https://app.getzep.com/ 有免费额度）
    3. 保存后重启 MiroFish.exe

三、出问题时
    * 双击 MiroFish-Console.bat：保留控制台窗口，直接看到报错。
    * 日志：%APPDATA%\\MiroFish\\logs\\desktop.log
    * 在线安装版下载中断：重新双击 MiroFish.exe 或 Setup.bat。
    * 窗口空白：需要 Edge WebView2（Win10/11 一般自带），
      可从 https://developer.microsoft.com/microsoft-edge/webview2/ 安装；
      临时可用  MiroFish.exe --browser  在默认浏览器中使用。

四、网络与安全
    后端仅监听 127.0.0.1 的随机空闲端口，不对外开放。
    模拟运行时会调用你在 .env 中配置的 LLM / Zep 云服务。

五、许可
    AGPL-3.0，详见 LICENSE。
"""
    with open(os.path.join(stage, 'README.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(text)
    shutil.copy2(os.path.join(DESKTOP_DIR, 'env.example'), os.path.join(stage, '.env.example'))
    license_src = os.path.join(REPO_ROOT, 'LICENSE')
    if os.path.exists(license_src):
        shutil.copy2(license_src, os.path.join(stage, 'LICENSE'))


def make_zip(stage, out_dir, name):
    zip_path = os.path.join(out_dir, name + '.zip')
    log(f'压缩 -> {zip_path}')
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.join(name, os.path.relpath(full, stage)))
                count += 1
    size = os.path.getsize(zip_path) / 1024 / 1024
    log(f'完成：{zip_path}（{count} 个文件，{size:.0f} MB）')
    return zip_path


def main():
    ap = argparse.ArgumentParser(description='打包 MiroFish Windows 桌面版')
    ap.add_argument('--mode', choices=['offline', 'setup'], default='setup')
    ap.add_argument('--wheels', default='', help='Windows site-packages 目录（offline 模式必填）')
    ap.add_argument('--embed', default='', help='embeddable Python 目录（offline 模式必填）')
    ap.add_argument('--exe', default=os.path.join(REPO_ROOT, 'build', 'MiroFish.exe'))
    ap.add_argument('--relaunch', action='store_true',
                    help='打包后立即用新图标重新编译并替换 MiroFish.exe（需要 zig）')
    ap.add_argument('--tools', default=os.path.join(REPO_ROOT, 'build', 'tools'),
                    help='uv.exe 所在目录（可选）')
    ap.add_argument('--out', default=os.path.join(REPO_ROOT, 'dist'))
    ap.add_argument('--zip', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.exe):
        raise SystemExit(f'缺少启动器 {args.exe}，请先运行: python desktop/fetch_sources.py')

    suffix = 'offline' if args.mode == 'offline' else 'setup'
    name = f'{APP_NAME}-{VERSION}-windows-x64-{suffix}'
    stage = os.path.join(args.out, name)
    os.makedirs(args.out, exist_ok=True)
    rmtree(stage)
    os.makedirs(stage, exist_ok=True)

    log(f'模式: {args.mode} -> {stage}')
    assemble_app(stage)
    assemble_backend(stage)
    assemble_frontend(stage)
    write_requirements(stage)
    shutil.copy2(args.exe, os.path.join(stage, f'{APP_NAME}.exe'))
    shutil.copy2(os.path.join(DESKTOP_DIR, 'Setup.bat'), os.path.join(stage, 'Setup.bat'))
    copy_tools(stage, args.tools)
    write_console_bat(stage)
    write_readme(stage, args.mode)

    if args.mode == 'offline':
        if not (args.wheels and args.embed):
            raise SystemExit('offline 模式需要 --wheels 与 --embed')
        populate_runtime(stage, args.wheels, args.embed)

    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(stage) for f in fs)
    log(f'未压缩体积: {total / 1024 / 1024:.1f} MB')

    # 用安装包内的 icon.ico 重新编译启动器，保证 exe 图标与窗口图标一致
    import subprocess
    try:
        from fetch_sources import compile_launcher
        compile_launcher(os.path.dirname(args.exe))
        shutil.copy2(os.path.join(os.path.dirname(args.exe), 'MiroFish.exe'),
                     os.path.join(stage, f'{APP_NAME}.exe'))
        log('已用最新图标重新编译 MiroFish.exe')
    except SystemExit as exc:
        log(f'跳过重新编译启动器：{exc}')
    except Exception as exc:  # noqa: BLE001
        log(f'跳过重新编译启动器：{exc}')

    if args.zip:
        make_zip(stage, args.out, name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
