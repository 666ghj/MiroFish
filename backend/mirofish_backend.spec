# -*- mode: python ; coding: utf-8 -*-
"""
MiroFish Backend PyInstaller 规格文件
用于将 Flask 后端打包成 Windows 可执行文件
"""

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# 项目路径
backend_dir = os.path.abspath(os.path.dirname(SPECPATH))

# 收集 app 目录下的所有文件
app_datas = []
app_dir = os.path.join(backend_dir, 'app')
for root, dirs, files in os.walk(app_dir):
    for file in files:
        if not file.endswith('.pyc') and not file.endswith('__pycache__'):
            src = os.path.join(root, file)
            dst = os.path.relpath(root, backend_dir)
            app_datas.append((src, dst))

# 隐藏导入列表
hidden_imports = [
    # Flask 相关
    'flask',
    'flask_cors',
    'werkzeug',
    'jinja2',
    'markupsafe',
    
    # OpenAI / LLM
    'openai',
    'httpx',
    'httpcore',
    
    # Zep Cloud
    'zep_cloud',
    
    # Pydantic
    'pydantic',
    'pydantic.deprecated.decorator',
    
    # 数据处理
    'charset_normalizer',
    'chardet',
    'fitz',  # PyMuPDF
    
    # dotenv
    'dotenv',
    'python_dotenv',
    
    # 其他依赖
    'logging.handlers',
    'email.mime.text',
    'email.mime.multipart',
]

# 收集大型包的所有模块
datas = app_datas
binaries = []

# 分析配置
a = Analysis(
    [os.path.join(backend_dir, 'run.py')],
    pathex=[backend_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大型包以减小体积
        'matplotlib',
        'scipy',
        'numpy.distutils',
        'PIL',
        'tkinter',
        'test',
        'unittest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mirofish_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 保留控制台以便调试
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mirofish_backend',
)
