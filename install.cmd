@echo off
setlocal enabledelayedexpansion

REM Claude Code Windows CMD Bootstrap Script
REM Installs Claude Code for environments where PowerShell is not available

REM Parse command line argument
set "TARGET=%~1"
if "!TARGET!"=="" set "TARGET=latest"

REM Validate target parameter
if /i "!TARGET!"=="stable" goto :target_valid
if /i "!TARGET!"=="latest" goto :target_valid
echo !TARGET! | findstr /r "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*" >nul
if !ERRORLEVEL! equ 0 goto :target_valid

echo Usage: %0 [stable^|latest^|VERSION] >&2
echo Example: %0 1.0.58 >&2
exit /b 1

:target_valid

REM Check for 64-bit Windows
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" goto :arch_valid
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" goto :arch_valid
if /i "%PROCESSOR_ARCHITEW6432%"=="AMD64" goto :arch_valid
if /i "%PROCESSOR_ARCHITEW6432%"=="ARM64" goto :arch_valid

echo Claude Code does not support 32-bit Windows. Please use a 64-bit version of Windows. >&2
exit /b 1

:arch_valid

REM Set constants
set "GCS_BUCKET=https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases"
set "DOWNLOAD_DIR=%USERPROFILE%\.claude\downloads"
REM Use native ARM64 binary on ARM64 Windows, x64 otherwise
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PLATFORM=win32-arm64"
) else (
    set "PLATFORM=win32-x64"
)

REM Create download directory
if not exist "!DOWNLOAD_DIR!" mkdir "!DOWNLOAD_DIR!"

REM Check for curl availability
curl --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo curl is required but not available. Please install curl or use PowerShell installer. >&2
    exit /b 1
)

REM Always download latest version (which has the most up-to-date installer)
call :download_file "!GCS_BUCKET!/latest" "!DOWNLOAD_DIR!\latest"
if !ERRORLEVEL! neq 0 (
    echo Failed to get latest version >&2
    exit /b 1
)

REM Read version from file
set /p VERSION=<"!DOWNLOAD_DIR!\latest"
del "!DOWNLOAD_DIR!\latest"

REM Download manifest
call :download_file "!GCS_BUCKET!/!VERSION!/manifest.json" "!DOWNLOAD_DIR!\manifest.json"
if !ERRORLEVEL! neq 0 (
    echo Failed to get manifest >&2
    exit /b 1
)

REM Extract checksum from manifest
call :parse_manifest "!DOWNLOAD_DIR!\manifest.json" "!PLATFORM!"
if !ERRORLEVEL! neq 0 (
    echo Platform !PLATFORM! not found in manifest >&2
    del "!DOWNLOAD_DIR!\manifest.json" 2>nul
    exit /b 1
)
del "!DOWNLOAD_DIR!\manifest.json"

REM Download binary
set "BINARY_PATH=!DOWNLOAD_DIR!\claude-!VERSION!-!PLATFORM!.exe"
call :download_file "!GCS_BUCKET!/!VERSION!/!PLATFORM!/claude.exe" "!BINARY_PATH!"
if !ERRORLEVEL! neq 0 (
    echo Failed to download binary >&2
    if exist "!BINARY_PATH!" del "!BINARY_PATH!"
    exit /b 1
)

REM Verify checksum
call :verify_checksum "!BINARY_PATH!" "!EXPECTED_CHECKSUM!"
if !ERRORLEVEL! neq 0 (
    echo Checksum verification failed >&2
    del "!BINARY_PATH!"
    exit /b 1
)

REM Run claude install to set up launcher and shell integration
echo Setting up Claude Code...
"!BINARY_PATH!" install "!TARGET!"
set "INSTALL_RESULT=!ERRORLEVEL!"

REM Clean up downloaded file
REM Wait a moment for any file handles to be released
timeout /t 1 /nobreak >nul 2>&1
del /f "!BINARY_PATH!" >nul 2>&1
if exist "!BINARY_PATH!" (
    echo Warning: Could not remove temporary file: !BINARY_PATH!
)

if !INSTALL_RESULT! neq 0 (
    echo Installation failed >&2
    exit /b 1
)

echo.
echo Installation complete^^!
echo.
exit /b 0

REM ============================================================================
REM SUBROUTINES
REM ============================================================================

:download_file
REM Downloads a file using curl
REM Args: %1=URL, %2=OutputPath
set "URL=%~1"
set "OUTPUT=%~2"

curl -fsSL "!URL!" -o "!OUTPUT!"
exit /b !ERRORLEVEL!

:parse_manifest
REM Parse JSON manifest to extract checksum for platform
REM Args: %1=ManifestPath, %2=Platform
set "MANIFEST_PATH=%~1"
set "PLATFORM_NAME=%~2"
set "EXPECTED_CHECKSUM="

REM Use findstr to find platform section, then look for checksum
set "FOUND_PLATFORM="
set "IN_PLATFORM_SECTION="

REM Read the manifest line by line
for /f "usebackq tokens=*" %%i in ("!MANIFEST_PATH!") do (
    set "LINE=%%i"
    
    REM Check if this line contains our platform
    echo !LINE! | findstr /c:"\"%PLATFORM_NAME%\":" >nul
    if !ERRORLEVEL! equ 0 (
        set "IN_PLATFORM_SECTION=1"
    )
    
    REM If we're in the platform section, look for checksum
    if defined IN_PLATFORM_SECTION (
        echo !LINE! | findstr /c:"\"checksum\":" >nul
        if !ERRORLEVEL! equ 0 (
            REM Extract checksum value
            for /f "tokens=2 delims=:" %%j in ("!LINE!") do (
                set "CHECKSUM_PART=%%j"
                REM Remove quotes, whitespace, and comma
                set "CHECKSUM_PART=!CHECKSUM_PART: =!"
                set "CHECKSUM_PART=!CHECKSUM_PART:"=!"
                set "CHECKSUM_PART=!CHECKSUM_PART:,=!"
                
                REM Check if it looks like a SHA256 (64 hex chars)
                if not "!CHECKSUM_PART!"=="" (
                    call :check_length "!CHECKSUM_PART!" 64
                    if !ERRORLEVEL! equ 0 (
                        set "EXPECTED_CHECKSUM=!CHECKSUM_PART!"
                        exit /b 0
                    )
                )
            )
        )
        
        REM Check if we've left the platform section (closing brace)
        echo !LINE! | findstr /c:"}" >nul
        if !ERRORLEVEL! equ 0 set "IN_PLATFORM_SECTION="
    )
)

if "!EXPECTED_CHECKSUM!"=="" exit /b 1
exit /b 0

:check_length
REM Check if string length equals expected length
REM Args: %1=String, %2=ExpectedLength
set "STR=%~1"
set "EXPECTED_LEN=%~2"
set "LEN=0"
:count_loop
if "!STR:~%LEN%,1!"=="" goto :count_done
set /a LEN+=1
goto :count_loop
:count_done
if %LEN%==%EXPECTED_LEN% exit /b 0
exit /b 1

:verify_checksum
REM Verify file checksum using certutil
REM Args: %1=FilePath, %2=ExpectedChecksum
set "FILE_PATH=%~1"
set "EXPECTED=%~2"

for /f "skip=1 tokens=*" %%i in ('certutil -hashfile "!FILE_PATH!" SHA256') do (
    set "ACTUAL=%%i"
    set "ACTUAL=!ACTUAL: =!"
    if "!ACTUAL!"=="CertUtil:Thecommandcompletedsuccessfully." goto :verify_done
    if "!ACTUAL!" neq "" (
        if /i "!ACTUAL!"=="!EXPECTED!" (
            exit /b 0
        ) else (
            exit /b 1
        )
    )
)

:verify_done
exit /b 1
