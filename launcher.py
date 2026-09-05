"""
MiroFish 启动器
双击运行后自动启动后端服务和前端服务，并打开浏览器
"""

import os
import sys
import time
import subprocess
import webbrowser
import signal
import threading
from pathlib import Path
from typing import Optional


def get_base_path():
    """获取程序基础路径"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的路径
        return Path(sys.executable).parent
    else:
        # 开发环境路径
        return Path(__file__).parent


def has_usable_stdin() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def show_error(title: str, message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}\n{message}", file=sys.stderr)


LOG_FILE: Optional[Path] = None


def log_line(message: str) -> None:
    if not LOG_FILE:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(message + "\n")
    except Exception:
        pass


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """等待服务器启动"""
    import urllib.request
    import urllib.error
    import socket
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, ConnectionRefusedError, socket.timeout, TimeoutError):
            time.sleep(0.5)
    return False


def read_env_lines(env_file: Path) -> list[str]:
    data = env_file.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312"):
        try:
            return data.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").splitlines()


def main():
    """主函数"""
    base_path = get_base_path()
    
    # 配置路径
    backend_path = base_path / "backend"
    frontend_path = base_path / "frontend" / "dist"
    env_file = backend_path / ".env"
    
    # 检查 .env 文件是否存在
    if not env_file.exists():
        show_error(
            "MiroFish 启动失败",
            "未找到配置文件 .env。\n\n"
            "请先运行安装程序并在“API 配置”页面填写密钥，或手动创建：\n"
            f"{env_file}",
        )
        log_line(f".env missing: {env_file}")
        if has_usable_stdin():
            input("按回车键退出...")
        sys.exit(1)
    
    # 设置环境变量
    os.environ['FLASK_HOST'] = '127.0.0.1'
    os.environ['FLASK_PORT'] = '5001'
    if getattr(sys, 'frozen', False):
        os.environ['FLASK_DEBUG'] = 'False'
    
    # 日志目录
    logs_path = base_path / "logs"
    try:
        logs_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        temp_dir = Path(os.environ.get("TEMP", str(base_path)))
        logs_path = temp_dir / "MiroFishLogs"
        logs_path.mkdir(parents=True, exist_ok=True)
    backend_log = logs_path / "backend.log"
    global LOG_FILE
    LOG_FILE = logs_path / "launcher.log"
    log_line("=== launcher start ===")
    log_line(f"base_path={base_path}")
    log_line(f"logs_path={logs_path}")

    # 存储子进程
    processes = []
    
    def terminate_processes():
        """清理子进程"""
        if has_usable_stdin():
            print("\n正在关闭服务...")
        for proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                proc.kill()

    def handle_signal(signum, frame):
        terminate_processes()
        raise SystemExit(0)
    
    # 注册信号处理
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        # 启动后端服务
        print("正在启动后端服务...")
        
        # 加载 .env 文件到环境变量
        for line in read_env_lines(env_file):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()
        
        if getattr(sys, 'frozen', False):
            # 打包环境
            # 优先检查嵌入式 Python
            python_exe = base_path / "python" / "python.exe"
            backend_exe = backend_path / "mirofish_backend.exe"
            run_py = backend_path / "run.py"
            
            if python_exe.exists() and run_py.exists():
                # 嵌入式 Python 模式
                print("  使用嵌入式 Python 启动后端...")
                with open(backend_log, "a", encoding="utf-8", errors="replace") as log_file:
                    log_file.write("\n=== backend start (embedded python) ===\n")
                    backend_proc = subprocess.Popen(
                        [str(python_exe), str(run_py)],
                        cwd=str(backend_path),
                        env=os.environ.copy(),
                        stdout=log_file,
                        stderr=log_file,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
            elif backend_exe.exists():
                # PyInstaller 打包模式
                print("  使用打包的后端程序...")
                with open(backend_log, "a", encoding="utf-8", errors="replace") as log_file:
                    log_file.write("\n=== backend start (pyinstaller) ===\n")
                    backend_proc = subprocess.Popen(
                        [str(backend_exe)],
                        cwd=str(backend_path),
                        env=os.environ.copy(),
                        stdout=log_file,
                        stderr=log_file,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
            else:
                show_error(
                    "MiroFish 启动失败",
                    "未找到后端启动程序。\n\n"
                    f"请检查以下路径是否存在：\n{python_exe}\n{backend_exe}",
                )
                if has_usable_stdin():
                    input("按回车键退出...")
                sys.exit(1)
        else:
            # 开发环境：使用 uv
            backend_proc = subprocess.Popen(
                ["uv", "run", "python", "run.py"],
                cwd=str(backend_path)
            )
        
        processes.append(backend_proc)
        
        # 启动前端静态文件服务
        print("正在启动前端服务...")
        
        # 使用内置线程作为简单 HTTP 服务器
        import http.server
        import socketserver
        
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(frontend_path), **kwargs)
            
            def log_message(self, format, *args):
                pass  # 禁用日志输出
        
        def run_frontend_server():
            with socketserver.TCPServer(("127.0.0.1", 3000), QuietHandler) as httpd:
                httpd.serve_forever()
        
        frontend_thread = threading.Thread(target=run_frontend_server, daemon=True)
        frontend_thread.start()
        
        # 等待后端服务启动
        print("正在等待服务启动...")
        time.sleep(0.5)
        if backend_proc.poll() is not None:
            show_error(
                "MiroFish 启动失败",
                "后端服务启动后立刻退出。\n\n"
                f"请查看日志：\n{backend_log}"
            )
            log_line("backend exited immediately; see backend.log")
            raise SystemExit(1)
        if wait_for_server("http://127.0.0.1:5001/health", timeout=30):
            print("后端服务已启动")
        else:
            print("警告：后端服务启动超时")
        
        # 等待前端服务启动
        if wait_for_server("http://127.0.0.1:3000/", timeout=10):
            print("前端服务已启动")
        else:
            print("警告：前端服务启动超时")
        
        # 打开浏览器
        print("正在打开浏览器...")
        webbrowser.open("http://127.0.0.1:3000")
        
        print("\n" + "=" * 50)
        print("MiroFish 已启动！")
        print("前端地址: http://127.0.0.1:3000")
        print("后端地址: http://127.0.0.1:5001")
        print("=" * 50)
        print("\n按 Ctrl+C 关闭服务...")
        
        # 等待进程
        while True:
            # 检查后端进程是否仍在运行
            if backend_proc.poll() is not None:
                print("后端服务已停止")
                break
            time.sleep(1)
            
    except Exception as e:
        show_error("MiroFish 启动失败", f"{e}")
        log_line(f"launcher exception: {e}")
        terminate_processes()
        raise SystemExit(1)
    finally:
        terminate_processes()


if __name__ == "__main__":
    main()
