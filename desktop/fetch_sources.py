"""
准备 Windows 桌面版所需的全部“素材”（可在 Linux / macOS / Windows 上运行）。

产物（默认放在 build/ 下）：

    build/wheels-win312/    Windows x64 的 site-packages（含 torch 等二进制扩展）
    build/embed312/         官方 embeddable CPython 3.12（解压后）
    build/MiroFish.exe      交叉编译好的启动器
    build/MiroFish.ico      图标

依赖：
    pip install uv ziglang
    （zig 仅用于交叉编译启动器；在 Windows 上有 mingw/MSVC 时也可自行编译）

用法：
    python desktop/fetch_sources.py --build-dir build --python-version 3.12
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP_DIR = os.path.join(REPO_ROOT, 'desktop')

PYPI = 'https://pypi.org'
WINDOWS_PLATFORM = 'x86_64-pc-windows-msvc'

REQUIREMENTS = [
    'flask>=3.0.0',
    'flask-cors>=6.0.0',
    'waitress>=3.0.2',
    'pywebview>=6.2.1',
    'openai>=1.0.0',
    'zep-cloud==3.13.0',
    'camel-oasis==0.2.5',
    "camel-ai==0.2.78",
    "mcp==1.29.0",
    'PyMuPDF>=1.24.0,<2',
    'charset-normalizer>=3.0.0',
    'chardet>=5.0.0',
    'python-dotenv>=1.0.0',
    'pydantic>=2.0.0',
]


def log(msg):
    print(f'[sources] {msg}', flush=True)


def run(cmd, **kw):
    log(' '.join(cmd) if isinstance(cmd, list) else cmd)
    subprocess.check_call(cmd, **kw)


def download_wheels(build_dir, python_version):
    target = os.path.join(build_dir, f'wheels-win{str(python_version).replace(".", "")}')
    if os.path.isdir(target) and os.listdir(target):
        log(f'已存在，跳过下载: {target}')
        return target

    req_file = os.path.join(build_dir, 'requirements-desktop.txt')
    os.makedirs(build_dir, exist_ok=True)
    with open(req_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(REQUIREMENTS) + '\n')

    os.makedirs(target, exist_ok=True)
    run([
        sys.executable, '-m', 'uv', 'pip', 'install',
        '--target', target,
        '--python-platform', WINDOWS_PLATFORM,
        '--python-version', str(python_version),
        '-r', req_file,
    ])
    return target


def fetch_embeddable(build_dir, python_version):
    """从 PyPI 上的 python-embed 包中提取官方 embeddable CPython。"""
    short = '.'.join(str(python_version).split('.')[:2])
    target = os.path.join(build_dir, f'embed{short.replace(".", "")}')
    if os.path.isdir(target) and os.listdir(target):
        log(f'已存在，跳过解压: {target}')
        return target

    pkg = f'{short}.0'
    url = f'{PYPI}/pypi/python-embed/{pkg}/json'
    log(f'查询 {url}')
    with urllib.request.urlopen(url, timeout=60) as resp:
        import json
        data = json.load(resp)
    sdist = next(u for u in data['urls'] if u['filename'].endswith('.tar.gz'))
    log(f'下载 {sdist["filename"]} ({sdist["size"] / 1e6:.1f} MB)')
    with urllib.request.urlopen(sdist['url'], timeout=300) as resp:
        blob = resp.read()

    tmp = os.path.join(build_dir, '_embed_tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tf:
        tf.extractall(tmp)

    data_zip = None
    for root, _, files in os.walk(tmp):
        if 'data.zip' in files:
            data_zip = os.path.join(root, 'data.zip')
            break
    if not data_zip:
        raise SystemExit('python-embed 包结构异常：找不到 data.zip')

    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(data_zip) as zf:
        names = zf.namelist()
        prefix = names[0].split('/')[0] + '/'
        for name in names:
            if not name.startswith(prefix) or name.endswith('/'):
                continue
            dest = os.path.join(target, os.path.relpath(name, prefix))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(name) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)

    shutil.rmtree(tmp, ignore_errors=True)
    log(f'embeddable Python -> {target}')
    return target


def build_icon(build_dir):
    """把 desktop/icon_source.png 转成桌面图标（需要 Pillow）。

    小尺寸（<=48px）单独放大主体，保证任务栏 / 资源管理器里清晰可辨。
    没有 Pillow 时退回标准库绘制的极简图标。
    """
    ico = os.path.join(DESKTOP_DIR, 'icon.ico')
    png = os.path.join(DESKTOP_DIR, 'icon.png')
    source = os.path.join(DESKTOP_DIR, 'icon_source.png')

    try:
        from PIL import Image
    except ImportError:
        Image = None

    if Image is not None and os.path.exists(source):
        base = Image.open(source).convert('RGBA')
        side = min(base.size)
        base = base.crop(((base.width - side) // 2, (base.height - side) // 2,
                          (base.width + side) // 2, (base.height + side) // 2))
        base = base.resize((1024, 1024), Image.LANCZOS)
        base.save(png)

        zoom_factor = 1.32
        nw = nh = int(1024 / zoom_factor)
        left = top = (1024 - nw) // 2
        zoomed = base.crop((left, top, left + nw, top + nh))

        import io
        import struct

        def png_bytes(im):
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            return buf.getvalue()

        entries = []
        for size, src in [(256, base), (128, base), (64, base), (48, zoomed),
                          (32, zoomed), (24, zoomed), (16, zoomed)]:
            entries.append((size, png_bytes(src.resize((size, size), Image.LANCZOS))))

        head = struct.pack('<HHH', 0, 1, len(entries))
        offset = 6 + 16 * len(entries)
        directory, blobs = b'', b''
        for size, data in entries:
            directory += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                                     1, 32, len(data), offset)
            blobs += data
            offset += len(data)
        with open(ico, 'wb') as f:
            f.write(head + directory + blobs)
        log(f'图标 -> {ico} / {png}')
        return ico

    sys.path.insert(0, DESKTOP_DIR)
    import icon as fallback  # noqa: E402
    with open(ico, 'wb') as f:
        f.write(fallback.ico_bytes())
    with open(png, 'wb') as f:
        f.write(fallback.png_bytes(256))
    log(f'图标（标准库兜底）-> {ico}')
    return ico


def compile_launcher(build_dir):
    exe = os.path.join(build_dir, 'MiroFish.exe')
    launcher = os.path.join(DESKTOP_DIR, 'launcher.c')
    rc = os.path.join(DESKTOP_DIR, 'app.rc')
    ico_path = os.path.join(DESKTOP_DIR, 'icon.ico')

    compiler = None
    if shutil.which('zig'):
        compiler = [shutil.which('zig'), 'cc']
    else:
        try:
            import ziglang  # noqa: F401
            pkg_dir = os.path.dirname(ziglang.__file__)
            candidate = os.path.join(pkg_dir, 'zig')
            if os.path.exists(candidate):
                compiler = [candidate, 'cc']
        except ImportError:
            pass

    if not os.path.exists(ico_path or ''):
        # 保证 app.rc 引用的 icon.ico 一定存在
        build_icon(build_dir)

    if compiler:
        run(compiler + [
            '-target', 'x86_64-windows-gnu', '-O2', '-municode', '-Wl,--subsystem,windows',
            '-o', exe, launcher, rc,
            '-lole32', '-lshell32', '-luser32',
        ], cwd=DESKTOP_DIR)
        log(f'启动器 -> {exe}')
        return exe

    if sys.platform == 'win32':
        # 本机就是 Windows：用 MSVC + rc.exe（需在 “x64 Native Tools” 命令行里运行）
        windres = shutil.which('windres')
        res = os.path.join(build_dir, 'app.res.o')
        if windres:
            run([windres, os.path.join(DESKTOP_DIR, 'app.rc'), '-O', 'coff', '-o', res], cwd=DESKTOP_DIR)
            run(['cl', '/nologo', '/O2', f'/Fe:{exe}', launcher, res,
                 'ole32.lib', 'shell32.lib', 'user32.lib'], cwd=DESKTOP_DIR)
            log(f'启动器 -> {exe}')
            return exe

    raise SystemExit('找不到可用的 C 编译器。请先执行: pip install ziglang')


def write_version(build_dir):
    path = os.path.join(build_dir, 'version.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('0.1.0\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-dir', default=os.path.join(REPO_ROOT, 'build'))
    ap.add_argument('--python-version', default='3.12')
    ap.add_argument('--skip-wheels', action='store_true')
    ap.add_argument('--skip-exe', action='store_true')
    args = ap.parse_args()

    os.makedirs(args.build_dir, exist_ok=True)
    if not args.skip_wheels:
        download_wheels(args.build_dir, args.python_version)
    fetch_embeddable(args.build_dir, args.python_version)
    build_icon(args.build_dir)
    if not args.skip_exe:
        compile_launcher(args.build_dir)
    write_version(args.build_dir)
    log('素材准备完成')


if __name__ == '__main__':
    main()
