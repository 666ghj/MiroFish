# MiroFish Desktop · Windows `.exe`

把 MiroFish（Vue 3 前端 + Flask 后端）打包成双击即用的 Windows 桌面程序。

```
desktop/
├── launcher.c            原生启动器（C）→ 编译成 MiroFish.exe
├── app.rc / app.manifest 图标、版本信息、DPI 与长路径清单
├── app.py                桌面运行时：用户数据目录、Flask+静态资源、pywebview 窗口
├── Setup.bat             在线安装版首次运行：创建 Python 运行时并安装依赖
├── fetch_sources.py      准备素材：Windows 依赖、embeddable Python、图标、exe
├── build.py              组装安装包（offline / setup 两种模式）
├── verify_exe.py         校验 PE：GUI 子系统、图标资源、依赖 DLL
├── icon_source.png       应用图标母版（1024²）
├── icon.ico / icon.png   由 fetch_sources.py 生成（多尺寸 + 小尺寸放大主体）
├── requirements-desktop.txt
├── version.txt
└── tests/test_desktop.py 启动器与配置接口的单测
```

## 产物

| 模式 | 体积 | 说明 |
|------|------|------|
| `--mode offline` | 约 1 GB（zip 约 500 MB） | 内置 Python 3.12 + 全部依赖，解压即用，完全离线 |
| `--mode setup` | 约 34 MB（zip 16 MB） | 内置 `uv.exe`；首次运行由 `Setup.bat` 创建运行时并联网装依赖 |

两者目录结构一致，`MiroFish.exe` 会依次查找：

```
runtime\venv\Scripts\pythonw.exe     <- Setup.bat 创建的虚拟环境
runtime\python\pythonw.exe           <- 完整离线版内置的 embeddable Python
MIROFISH_PYTHON 环境变量              <- 开发调试用
```

## 运行时行为

1. 数据目录：`%APPDATA%\MiroFish`（可用 `MIROFISH_HOME` 覆盖）
   - `.env` 首次启动由模板生成，并写入随机 `SECRET_KEY`
   - `uploads\` 文档、图谱、模拟、报告
   - `logs\desktop.log` 完整日志（打包后没有控制台，也能排查）
2. 后端：`waitress` 监听 `127.0.0.1:<随机空闲端口>`，同一端口同时提供
   * 前端构建产物（支持 vue-router history 深链接回落）
   * `/api/*`、`/health`
   因此桌面端没有跨域、也没有写死的端口。
3. 窗口：`pywebview`（WebView2）加载 `http://127.0.0.1:<port>/`；
   首次使用若未配置 Key，前端会自动跳到 `/settings` 配置页。

## 本地打包（Linux / macOS / Windows 均可）

```bash
# 0) 依赖：Node 18+、Python 3.10-3.13
cd frontend && npm ci && npm run build && cd ..

python -m pip install uv ziglang pillow      # zig 用于交叉编译 .exe
python desktop/fetch_sources.py --build-dir build
python desktop/verify_exe.py build/MiroFish.exe

python desktop/build.py --mode setup   --out dist --zip
python desktop/build.py --mode offline --out dist --zip \
    --wheels build/wheels-win312 --embed build/embed312
```

`fetch_sources.py` 做的事情：

- `uv pip install --python-platform x86_64-pc-windows-msvc` 拉取 Windows 版依赖
- 从 PyPI 的 `python-embed` 包中取出官方 **embeddable CPython 3.12**
- 由 `icon_source.png` 生成多尺寸 `.ico`（≤48px 自动放大主体）
- 用 `zig cc` 交叉编译 `launcher.c`（GUI 子系统 + 图标资源）

## CI

`.github/workflows/desktop-build.yml` 在 `windows-latest` 上原生构建：

- 推送 `v*` tag → 构建两种安装包并附加到 Release
- `workflow_dispatch` → 手动触发，产物在 Actions artifacts

## 已知限制

- 只发布 **x64**；ARM64 Windows 可通过源码方式运行。
- WebView2 缺失（极少见）时，可用 `MiroFish.exe --browser` 在默认浏览器中使用。
- 模拟运行时依赖网络调用 LLM / Zep 云服务；断网时只能浏览已有结果。
