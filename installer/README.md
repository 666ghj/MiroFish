# MiroFish Windows 打包使用说明

本文档说明如何将 MiroFish 项目打包成 Windows 可执行安装程序。

## 环境要求

| 工具 | 版本要求 | 用途 | 下载地址 |
|------|---------|------|----------|
| **Python** | 3.11+ | 后端打包 | https://python.org |
| **Node.js** | 18+ | 前端构建 | https://nodejs.org |
| **uv** | 最新版 | Python 包管理 | `pip install uv` |
| **Inno Setup** | 6.x | 创建安装程序 | https://jrsoftware.org/isinfo.php |

## 快速开始

### 方式一：一键打包（推荐）

使用嵌入式 Python 模式打包（体积较小，适合大多数情况）：

```powershell
.\installer\build.ps1
```

### 方式二：PyInstaller 打包

使用 PyInstaller 完全打包（体积大，但完全独立）：

```powershell
.\installer\build.ps1 -PyInstaller
```

> ⚠️ 注意：PyInstaller 模式打包时间长，输出文件可能超过 1GB

### 方式三：分步执行

如果只需要部分步骤，可以使用参数跳过：

```powershell
# 跳过前端构建（如果前端没有修改）
.\installer\build.ps1 -SkipFrontend

# 跳过后端处理（如果后端没有修改）  
.\installer\build.ps1 -SkipBackend

# 跳过安装程序创建（只生成可执行文件）
.\installer\build.ps1 -SkipInstaller

# 清理旧构建后重新开始
.\installer\build.ps1 -Clean
```

## 输出文件

打包完成后，会生成以下文件（嵌入式 Python 模式）：

```
MiroFish_exe/
├── dist/
│   └── MiroFish/                    # 可直接运行的目录
│       ├── MiroFish.exe             # 主启动器（双击运行）
│       ├── python/                  # 嵌入式 Python 运行时
│       │   ├── python.exe
│       │   ├── Lib/
│       │   └── ...
│       ├── backend/                 # 后端源代码
│       │   ├── run.py
│       │   ├── app/
│       │   └── .env                 # 安装时生成的配置
│       └── frontend/
│           └── dist/                # 静态文件
│
└── installer/
    └── output/
        └── MiroFish_Setup_0.1.0.exe # 安装程序
```

## 安装程序功能

生成的安装程序 `MiroFish_Setup_0.1.0.exe` 包含：

1. **欢迎页面**：显示应用信息
2. **许可协议**：AGPL-3.0 许可证
3. **安装目录选择**：用户可自定义安装位置
4. **API 配置页面**：
   - LLM API Key（必填）
   - LLM Base URL（默认：阿里百炼）
   - LLM Model Name（默认：qwen-plus）
   - ZEP API Key（必填）
5. **安装进度**：显示文件复制进度
6. **完成页面**：可选立即启动

## 常见问题

### Inno Setup 未找到

如果看到警告"未找到 Inno Setup"，请：
1. 下载安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)
2. 确保安装到默认位置或将路径添加到环境变量
3. 重新运行打包脚本

### 后端打包失败

检查以下几点：
1. 确保 Python 3.11+ 已安装
2. 确保 uv 包管理器已安装：`pip install uv`
3. 确保后端依赖已安装：`cd backend && uv sync`

### 前端构建失败

检查以下几点：
1. 确保 Node.js 18+ 已安装
2. 确保前端依赖已安装：`cd frontend && npm install`

### 运行时缺少 DLL

PyInstaller 已自动包含大部分依赖，如果仍有问题：
1. 在干净的 Windows 环境测试
2. 安装 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

## 修改配置页面

如需修改安装程序的配置页面，编辑 `installer/setup.iss` 文件：

- 添加/删除配置项：修改 `InitializeWizard` 过程
- 修改默认值：修改对应的 `Edit.Text` 属性
- 修改验证逻辑：修改 `NextButtonClick` 函数
- 修改 .env 生成：修改 `CurStepChanged` 过程

## 版本更新

更新版本号时，修改以下位置：

1. `installer/setup.iss` 第 7 行：`#define MyAppVersion "x.x.x"`
2. `package.json` 中的 `version` 字段
3. `backend/pyproject.toml` 中的 `version` 字段
