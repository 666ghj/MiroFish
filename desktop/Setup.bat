@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title MiroFish 首次运行初始化
cd /d "%~dp0"

echo ================================================================
echo   MiroFish 初始化（首次运行执行一次即可）
echo ================================================================
echo   1) 用你系统里的 Python 3.10-3.13 生成程序专用的独立运行时
echo      （不会改动你已装的 Python，不需要管理员权限）
echo   2) 安装运行依赖（约 500 MB - 1 GB，取决于网络）
echo   3) 创建桌面快捷方式
echo.
echo   系统里没有 Python 时，会尝试用 winget 自动安装 Python 3.12。
echo ================================================================
echo.

set "ROOT=%~dp0"
set "VENV=%ROOT%runtime\venv"
set "PY=%VENV%\Scripts\python.exe"
set "REQ=%ROOT%app\backend\requirements-desktop.txt"
set "UV=%ROOT%tools\uv.exe"

if exist "%PY%" (
    echo 检测到已有运行环境，开始体检...
    "%PY%" -c "import flask, webview, waitress, openai, pydantic, fitz, camel, oasis, mcp" >nul 2>&1
    if not errorlevel 1 (
        echo 运行环境完好，跳过安装。
        goto :shortcut
    )
    echo 运行环境不完整，继续修复...
    goto :install
)

rem ---------------- 1. 寻找基础 Python ----------------
set "BASEPY="
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined BASEPY (
        py -%%V-64 -c "import sys" >nul 2>&1 && set "BASEPY=py -%%V-64"
    )
)
if not defined BASEPY (
    python -c "import sys;assert (3,10)<=sys.version_info[:2]<(3,14)" >nul 2>&1 && set "BASEPY=python"
)

if not defined BASEPY (
    echo [!] 未找到 Python 3.10 - 3.13，尝试用 winget 安装 Python 3.12 ...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [X] 系统没有 winget。请先手动安装 Python 3.12：
        echo     https://www.python.org/downloads/windows/
        echo     安装时请勾选 "Add python.exe to PATH"。
        pause
        exit /b 1
    )
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    set "BASEPY=py -3.12-64"
    !BASEPY! -c "import sys" >nul 2>&1 || (
        echo [X] Python 安装后仍不可用，请重启电脑后再次运行本脚本。
        pause
        exit /b 1
    )
)

echo [1/4] 基础 Python：%BASEPY%

rem ---------------- 2. 创建独立运行时 ----------------
echo [2/4] 创建独立运行环境...
if not exist "%ROOT%runtime" mkdir "%ROOT%runtime"
!BASEPY! -m venv "%VENV%"
if errorlevel 1 (
    echo [X] 创建虚拟环境失败。
    pause
    exit /b 1
)

rem ---------------- 3. 安装依赖 ----------------
:install
echo [3/4] 安装依赖（最慢的一步，请保持网络连接）...
if exist "%UV%" (
    "%UV%" pip install --python "%PY%" -r "%REQ%"
    if errorlevel 1 (
        echo [!] 官方源失败，改用清华镜像重试...
        "%UV%" pip install --python "%PY%" -r "%REQ%" --default-index https://pypi.tuna.tsinghua.edu.cn/simple
    )
) else (
    "%PY%" -m pip install --upgrade pip --disable-pip-version-check -q
    "%PY%" -m pip install --disable-pip-version-check -r "%REQ%"
    if errorlevel 1 (
        "%PY%" -m pip install --disable-pip-version-check -r "%REQ%" ^
            -i https://pypi.tuna.tsinghua.edu.cn/simple ^
            --trusted-host pypi.tuna.tsinghua.edu.cn
    )
)

echo 校验依赖...
"%PY%" -c "import flask, webview, waitress, openai, pydantic, fitz, camel, oasis, mcp; print('OK: 依赖全部就绪')"
if errorlevel 1 (
    echo [X] 依赖校验失败，请检查网络后重新运行 Setup.bat。
    pause
    exit /b 1
)

rem ---------------- 4. 桌面快捷方式 ----------------
:shortcut
echo [4/4] 创建桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MiroFish.lnk');" ^
  "$s.TargetPath='%ROOT%MiroFish.exe'; $s.WorkingDirectory='%ROOT%';" ^
  "$s.IconLocation='%ROOT%MiroFish.exe,0'; $s.Save()" >nul 2>&1

echo.
echo ================================================================
echo   初始化完成！现在双击 MiroFish.exe 就能启动。
echo   首次启动请填写 %APPDATA%\MiroFish\.env 里的 LLM_API_KEY 与 ZEP_API_KEY。
echo ================================================================
echo.
if /i not "%~1"=="--quiet" pause
exit /b 0
