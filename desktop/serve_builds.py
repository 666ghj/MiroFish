"""
本地下载服务器：把 dist-builds/ 里的安装包用一个网页暴露出来，方便直接下载。

用法：
    python desktop/serve_builds.py --dir dist-builds --port 8080

浏览器打开 http://<host>:8080/ 即可看到安装包列表并点击下载
（在 Arena 沙箱中会以 Live Preview 形式呈现）。
"""

import argparse
import html
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, quote


def human(size: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{size} B'
        size /= 1024
    return f'{size:.1f} GB'


INDEX_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MiroFish 安装包下载</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; padding: 48px 20px;
    font-family: -apple-system, "Segoe UI", "Noto Sans SC", system-ui, sans-serif;
    background: radial-gradient(circle at 15% 0%, #16233d 0%, #080d17 60%);
    color: #e8eef8; display: flex; justify-content: center;
  }}
  .wrap {{ width: min(820px, 100%); }}
  header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 10px; }}
  .logo {{
    width: 46px; height: 46px; border-radius: 12px; flex: none;
    background: linear-gradient(140deg, #0b1b33, #123c5c);
    display: grid; place-items: center; font-size: 22px;
  }}
  h1 {{ margin: 0; font-size: 24px; letter-spacing: .4px; }}
  .sub {{ color: #8fa2bd; font-size: 14px; line-height: 1.7; margin: 6px 0 28px; }}
  .card {{
    display: flex; align-items: center; gap: 16px; padding: 18px 20px;
    background: rgba(20, 30, 49, .88); border: 1px solid rgba(120, 160, 220, .2);
    border-radius: 14px; margin-bottom: 14px; transition: border-color .18s ease;
  }}
  .card:hover {{ border-color: #22d3ee; }}
  .icon {{
    width: 42px; height: 42px; border-radius: 10px; flex: none;
    background: rgba(34, 211, 238, .12); display: grid; place-items: center; font-size: 20px;
  }}
  .meta {{ flex: 1; min-width: 0; }}
  .name {{ font-size: 14px; font-weight: 600; word-break: break-all; }}
  .size {{ color: #7d8fa9; font-size: 12px; margin-top: 4px; }}
  .btn {{
    flex: none; padding: 10px 20px; border-radius: 10px; text-decoration: none;
    background: linear-gradient(135deg, #22d3ee, #3b82f6); color: #04101f;
    font-weight: 700; font-size: 13px;
  }}
  .btn:hover {{ filter: brightness(1.08); }}
  .empty {{ color: #7d8fa9; font-size: 14px; }}
  ol {{ color: #9fb0c9; font-size: 13px; line-height: 2; padding-left: 20px; margin-top: 28px; }}
  code {{ background: rgba(255,255,255,.07); padding: 2px 6px; border-radius: 5px; }}
  footer {{ margin-top: 34px; color: #64789a; font-size: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">🐟</div>
    <h1>MiroFish 安装包下载</h1>
  </header>
  <p class="sub">Windows x64 桌面版 · 点击右侧按钮即可下载压缩包，解压后双击 <code>MiroFish.exe</code> 运行。</p>
  {cards}
  <ol>
    <li>解压到你有写权限的目录（不要放在 <code>C:\\Program Files</code>）。</li>
    <li>双击 <code>MiroFish.exe</code>；首次运行需要下载运行环境，按提示确认即可。</li>
    <li>首次进入会自动打开配置页，填入 <code>LLM_API_KEY</code> 与 <code>ZEP_API_KEY</code> 后保存。</li>
    <li>如果启动异常，双击 <code>MiroFish-Console.bat</code> 可以看到完整报错日志。</li>
  </ol>
  <footer>由 desktop/serve_builds.py 提供 · 文件直接来自构建产物目录</footer>
</div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    directory = '.'

    def log_message(self, fmt, *args):  # 安静一些
        sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    def _files(self):
        items = []
        for name in sorted(os.listdir(self.directory)):
            path = os.path.join(self.directory, name)
            if os.path.isfile(path):
                items.append((name, os.path.getsize(path)))
        return items

    def _send_index(self):
        cards = []
        for name, size in self._files():
            lower = name.lower()
            icon = '🗜️' if lower.endswith('.zip') else '📄'
            cards.append(
                '<div class="card">'
                f'<div class="icon">{icon}</div>'
                f'<div class="meta"><div class="name">{html.escape(name)}</div>'
                f'<div class="size">{human(size)}</div></div>'
                f'<a class="btn" href="/download/{quote(name)}">下载</a>'
                '</div>'
            )
        if not cards:
            cards.append('<p class="empty">目录中还没有安装包，请先运行桌面版打包脚本。</p>')

        body = INDEX_TEMPLATE.format(cards='\n  '.join(cards)).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _send_file(self, name):
        path = os.path.join(self.directory, name)
        if not os.path.isfile(path):
            self.send_error(404, 'Not Found')
            return
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(size))
        self.send_header('Content-Disposition', f'attachment; filename="{name}"')
        self.send_header('Accept-Ranges', 'none')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(1024 * 256)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._send_index()
        elif self.path.startswith('/download/'):
            self._send_file(unquote(self.path[len('/download/'):]))
        else:
            self.send_error(404, 'Not Found')

    def do_HEAD(self):
        self.do_GET()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='dist-builds')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='0.0.0.0')
    args = ap.parse_args()

    directory = os.path.abspath(args.dir)
    if not os.path.isdir(directory):
        raise SystemExit(f'目录不存在: {directory}')

    Handler.directory = directory
    files = [(n, os.path.getsize(os.path.join(directory, n)))
             for n in sorted(os.listdir(directory))
             if os.path.isfile(os.path.join(directory, n))]
    print(f'[serve] 目录: {directory}')
    for name, size in files:
        print(f'[serve]   {name}  ({human(size)})')
    print(f'[serve] 监听 http://{args.host}:{args.port}/')

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
