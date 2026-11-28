"""
MiroFish Backend 启动入口

环境变量:
    FLASK_USE_RELOADER  是否启用 Werkzeug 自动重载（默认 false，与 FLASK_DEBUG 无关）。
                        取值 true/1/yes（不区分大小写）为启用，其余或未设置均为禁用。
                        注意：重载会退出当前服务进程，触发 atexit 清理并终止所有
                        正在运行的模拟子进程，因此默认关闭。
"""

import os
import sys

# 解决 Windows 控制台中文乱码问题：在所有导入之前设置 UTF-8 编码
if sys.platform == 'win32':
    # 设置环境变量确保 Python 使用 UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # 重新配置标准输出流为 UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def _env_flag(name, default=False):
    """宽松解析布尔型环境变量：true/1/yes（不区分大小写）为 True，其余为 False"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes')


def main():
    """主函数"""
    # 验证配置
    errors = Config.validate()
    if errors:
        print("配置错误:")
        for err in errors:
            print(f"  - {err}")
        print("\n请检查 .env 文件中的配置")
        sys.exit(1)
    
    # 创建应用
    app = create_app()
    
    # 获取运行配置
    # 默认仅监听本机回环地址；设置 FLASK_HOST=0.0.0.0 会将未鉴权的 API 暴露到网络
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG
    # 自动重载默认关闭，避免源码修改触发重载杀死正在运行的模拟
    use_reloader = _env_flag('FLASK_USE_RELOADER', default=False)
    
    # 启动服务
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader, threaded=True)


if __name__ == '__main__':
    main()

