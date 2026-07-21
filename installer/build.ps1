#Requires -Version 5.1
<#
.SYNOPSIS
    Build MiroFish Windows installer
    
.DESCRIPTION
    This script builds a Windows installer (.exe) for MiroFish.
    Supports embedded Python mode (smaller) or PyInstaller mode (larger but self-contained).
    
.PARAMETER PyInstaller
    Use PyInstaller mode instead of embedded Python mode
    
.PARAMETER SkipFrontend
    Skip frontend build (use if unchanged)
    
.PARAMETER SkipBackend
    Skip backend processing (use if unchanged)
    
.PARAMETER SkipInstaller
    Skip installer creation (only generate executables)
    
.PARAMETER Clean
    Clean old builds before starting
    
.PARAMETER Version
    Version number for the installer (default: 0.1.1)
    
.EXAMPLE
    .\build.ps1
    
.EXAMPLE
    .\build.ps1 -PyInstaller -Clean
    
.EXAMPLE
    .\build.ps1 -SkipFrontend -SkipBackend
#>

param(
    [switch]$PyInstaller,
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SkipInstaller,
    [switch]$Clean,
    [string]$Version = "0.1.1"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"

# Colors for output
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# Check prerequisites
function Test-Prerequisites {
    Write-Info "Checking prerequisites..."
    
    # Check Python
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Error "Python not found. Please install Python 3.9+ and add to PATH."
        exit 1
    }
    $pythonVersion = & python --version 2>&1
    Write-Info "Found $pythonVersion"
    
    # Check Node.js
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeCmd) {
        Write-Error "Node.js not found. Please install Node.js 18+ and add to PATH."
        exit 1
    }
    $nodeVersion = & node --version 2>&1
    Write-Info "Found Node.js $nodeVersion"
    
    # Check Inno Setup (optional)
    $isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $isccCmd) {
        Write-Warning "Inno Setup not found. Installer creation will be skipped."
        Write-Warning "Install from: https://jrsoftware.org/isdl.php"
    } else {
        Write-Info "Found Inno Setup"
    }
    
    if ($PyInstaller) {
        # Check PyInstaller
        $pyinstallerCmd = Get-Command pyinstaller -ErrorAction SilentlyContinue
        if (-not $pyinstallerCmd) {
            Write-Info "Installing PyInstaller..."
            & pip install pyinstaller
        }
    }
    
    Write-Success "Prerequisites check passed"
}

# Clean old builds
function Clear-Build {
    Write-Info "Cleaning old builds..."
    
    if (Test-Path $DistDir) {
        Remove-Item $DistDir -Recurse -Force
        Write-Info "Removed $DistDir"
    }
    
    if (Test-Path $BuildDir) {
        Remove-Item $BuildDir -Recurse -Force
        Write-Info "Removed $BuildDir"
    }
    
    # Clean Python cache
    Get-ChildItem -Path $RootDir -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem -Path $RootDir -Filter "*.pyc" -Recurse | Remove-Item -Force
    
    # Clean Node modules cache
    $frontendDir = Join-Path $RootDir "frontend"
    $nodeModulesDir = Join-Path $frontendDir "node_modules"
    if (Test-Path (Join-Path $frontendDir ".vite")) {
        Remove-Item (Join-Path $frontendDir ".vite") -Recurse -Force
    }
    
    Write-Success "Clean completed"
}

# Build frontend
function Build-Frontend {
    if ($SkipFrontend) {
        Write-Info "Skipping frontend build (as requested)"
        return
    }
    
    Write-Info "Building frontend..."
    
    $frontendDir = Join-Path $RootDir "frontend"
    Push-Location $frontendDir
    
    try {
        # Install dependencies
        Write-Info "Installing frontend dependencies..."
        & npm ci
        
        # Build production version
        Write-Info "Building production frontend..."
        & npm run build
        
        Write-Success "Frontend build completed"
    } finally {
        Pop-Location
    }
}

# Build backend
function Build-Backend {
    if ($SkipBackend) {
        Write-Info "Skipping backend processing (as requested)"
        return
    }
    
    Write-Info "Building backend..."
    
    $backendDir = Join-Path $RootDir "backend"
    
    # Install Python dependencies
    Write-Info "Installing Python dependencies..."
    Push-Location $backendDir
    try {
        & pip install -r requirements.txt --target ./libs -q
    } finally {
        Pop-Location
    }
    
    if ($PyInstaller) {
        Build-PyInstaller
    } else {
        Build-Embedded
    }
    
    Write-Success "Backend build completed"
}

# Build with PyInstaller
function Build-PyInstaller {
    Write-Info "Building with PyInstaller..."
    
    $backendDir = Join-Path $RootDir "backend"
    $distBackendDir = Join-Path $DistDir "backend"
    
    Push-Location $backendDir
    try {
        # Create PyInstaller spec
        $specContent = @"
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('templates', 'templates'),
    ],
    hiddenimports=['flask', 'flask_cors', 'gunicorn'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MiroFish',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"@
        
        $specContent | Out-File -FilePath "mirofish.spec" -Encoding UTF8
        
        # Run PyInstaller
        & pyinstaller mirofish.spec --distpath $distBackendDir --workpath $BuildDir --clean
        
        Write-Success "PyInstaller build completed"
    } finally {
        Pop-Location
    }
}

# Build with embedded Python
function Build-Embedded {
    Write-Info "Building with embedded Python..."
    
    $backendDir = Join-Path $RootDir "backend"
    $distBackendDir = Join-Path $DistDir "MiroFish_Portable\backend"
    
    # Create dist directory
    New-Item -ItemType Directory -Force -Path $distBackendDir | Out-Null
    
    # Copy backend files
    Write-Info "Copying backend files..."
    Copy-Item -Path "$backendDir\*" -Destination $distBackendDir -Recurse -Force
    
    # Download embedded Python
    $embeddedDir = Join-Path $ScriptDir "embedded"
    $pythonZip = Join-Path $embeddedDir "python.zip"
    
    if (-not (Test-Path $pythonZip)) {
        Write-Info "Downloading embedded Python..."
        New-Item -ItemType Directory -Force -Path $embeddedDir | Out-Null
        
        # Get Python version
        $pyVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        $pythonUrl = "https://www.python.org/ftp/python/$pyVersion.0/python-$pyVersion.0-embed-amd64.zip"
        
        try {
            Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonZip
            Write-Success "Downloaded embedded Python"
        } catch {
            Write-Error "Failed to download embedded Python: $_"
            Write-Info "Please download manually from: $pythonUrl"
            exit 1
        }
    }
    
    # Extract embedded Python
    $pythonDir = Join-Path $distBackendDir "python"
    New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
    Expand-Archive -Path $pythonZip -DestinationPath $pythonDir -Force
    
    # Install dependencies to embedded Python
    Write-Info "Installing dependencies to embedded Python..."
    $pipDir = Join-Path $pythonDir "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $pipDir | Out-Null
    
    Get-Content "$backendDir\requirements.txt" | ForEach-Object {
        if ($_ -match "^\s*#" -or $_ -match "^\s*$") { return }
        & pip install $_ --target $pipDir -q 2>&1 | Out-Null
    }
    
    Write-Success "Embedded Python build completed"
}

# Create launcher script
function New-Launcher {
    Write-Info "Creating launcher script..."
    
    $portableDir = Join-Path $DistDir "MiroFish_Portable"
    $launcherScript = Join-Path $portableDir "start.ps1"
    
    $scriptContent = @'
# MiroFish Launcher Script
param(
    [string]$ApiKey = "",
    [int]$Port = 5000
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$PythonExe = Join-Path $BackendDir "python\python.exe"

# Set environment variables
$env:MIROFISH_PORT = $Port
if ($ApiKey) {
    $env:MIROFISH_API_KEY = $ApiKey
}

Write-Host "Starting MiroFish..." -ForegroundColor Cyan
Write-Host "Backend: http://localhost:$Port" -ForegroundColor Green
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Green

# Start backend
$backendJob = Start-Job -ScriptBlock {
    param($PythonExe, $BackendDir)
    Set-Location $BackendDir
    & $PythonExe app.py
} -ArgumentList $PythonExe, $BackendDir

# Start frontend dev server
$frontendJob = Start-Job -ScriptBlock {
    param($FrontendDir)
    Set-Location $FrontendDir
    npm run dev -- --host
} -ArgumentList $FrontendDir

# Open browser
Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"

# Wait for jobs
Wait-Job $backendJob, $frontendJob
'@
    
    $scriptContent | Out-File -FilePath $launcherScript -Encoding UTF8
    
    # Create batch file for easy launch
    $batchFile = Join-Path $portableDir "start.bat"
    "@echo off`npowershell -ExecutionPolicy Bypass -File `"%~dp0start.ps1`" %*" | Out-File -FilePath $batchFile -Encoding ASCII
    
    # Copy frontend dist
    $frontendDistDir = Join-Path $RootDir "frontend\dist"
    if (Test-Path $frontendDistDir) {
        Copy-Item -Path $frontendDistDir -Destination (Join-Path $portableDir "frontend\dist") -Recurse -Force
    }
    
    Write-Success "Launcher script created"
}

# Create installer
function New-Installer {
    if ($SkipInstaller) {
        Write-Info "Skipping installer creation (as requested)"
        return
    }
    
    $isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $isccCmd) {
        Write-Warning "Inno Setup not found, skipping installer creation"
        Write-Warning "Portable version is available in: $DistDir\MiroFish_Portable"
        return
    }
    
    Write-Info "Creating installer..."
    
    $setupIss = Join-Path $ScriptDir "setup.iss"
    
    # Generate setup.iss
    $issContent = @"
[Setup]
AppName=MiroFish
AppVersion=$Version
AppPublisher=MiroFish Team
AppPublisherURL=https://github.com/666ghj/MiroFish
AppSupportURL=https://github.com/666ghj/MiroFish/issues
DefaultDirName={autopf}\MiroFish
DefaultGroupName=MiroFish
AllowNoIcons=yes
LicenseFile=..\LICENSE
InfoBeforeFile=README.txt
OutputDir=..\dist
OutputBaseFilename=MiroFish_Setup_$Version
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MiroFish_Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MiroFish"; Filename: "{app}\start.bat"
Name: "{group}\{cm:ProgramOnTheWeb,MiroFish}"; Filename: "https://github.com/666ghj/MiroFish"
Name: "{group}\{cm:UninstallProgram,MiroFish}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MiroFish"; Filename: "{app}\start.bat"; Tasks: desktopicon

[Run]
Filename: "{app}\start.bat"; Description: "{cm:LaunchProgram,MiroFish}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ApiKeyPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ApiKeyPage := CreateInputQueryPage(wpWelcome,
    'API Configuration', 'Enter your API key',
    'Please enter your API key for LLM services. You can also configure this later in the .env file.');
  ApiKeyPage.Add('API Key:', False);
end;

function GetApiKey(Param: String): String;
begin
  Result := ApiKeyPage.Values[0];
end;
"@
    
    $issContent | Out-File -FilePath $setupIss -Encoding UTF8
    
    # Create README for installer
    $readmeFile = Join-Path $ScriptDir "README.txt"
    "MiroFish $Version`n`nThank you for installing MiroFish!`n`nAfter installation, you can launch the application from the Start Menu or Desktop shortcut.`n`nThe application will open in your default web browser.`n`nFor more information, visit: https://github.com/666ghj/MiroFish" | Out-File -FilePath $readmeFile -Encoding UTF8
    
    # Create assets directory
    $assetsDir = Join-Path $ScriptDir "assets"
    New-Item -ItemType Directory -Force -Path $assetsDir | Out-Null
    
    # Run Inno Setup
    Push-Location $ScriptDir
    try {
        & iscc $setupIss
        Write-Success "Installer created: $DistDir\MiroFish_Setup_$Version.exe"
    } finally {
        Pop-Location
    }
}

# Main build process
function Main {
    Write-Host ""
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "  MiroFish Windows Installer Builder" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host ""
    
    Test-Prerequisites
    
    if ($Clean) {
        Clear-Build
    }
    
    # Create dist directory
    if (-not (Test-Path $DistDir)) {
        New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
    }
    
    Build-Frontend
    Build-Backend
    New-Launcher
    New-Installer
    
    Write-Host ""
    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "  Build completed successfully!" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
    Write-Host ""
    
    if (Test-Path (Join-Path $DistDir "MiroFish_Setup_$Version.exe")) {
        Write-Host "Installer: $DistDir\MiroFish_Setup_$Version.exe" -ForegroundColor Cyan
    }
    
    Write-Host "Portable:  $DistDir\MiroFish_Portable" -ForegroundColor Cyan
    Write-Host ""
}

# Run main
Main
