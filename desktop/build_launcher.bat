@echo off
rem 在 GitHub Actions / 本机 “x64 Native Tools 命令行” 里用 MSVC 编译 MiroFish.exe
setlocal
chcp 65001 >nul

if "%VSCMD_ARG_TGT_ARCH%"=="" (
    set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
    if not exist "%VSWHERE%" (
        echo [X] 找不到 vswhere.exe，请在 “x64 Native Tools Command Prompt” 中运行。
        exit /b 1
    )
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
    call "%VSPATH%\Common7\Tools\VsDevCmd.bat" -arch=amd64 -no_logo
)

if not exist build mkdir build
rc /nologo /fo build\MiroFish.res desktop\app.rc
if errorlevel 1 exit /b 1

cl /nologo /O2 /MT /DUNICODE /D_UNICODE /Fe:build\MiroFish.exe desktop\launcher.c build\MiroFish.res ole32.lib shell32.lib user32.lib
if errorlevel 1 exit /b 1

echo [OK] build\MiroFish.exe
exit /b 0
