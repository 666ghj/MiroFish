# MiroFish Windows build script
# Requirements: Python 3.11+, Node.js 18+, Inno Setup 6
#
# Usage:
#   .\build.ps1
#   .\build.ps1 -PyInstaller
#   .\build.ps1 -SkipFrontend
#   .\build.ps1 -SkipBackend
#   .\build.ps1 -SkipInstaller
#   .\build.ps1 -Clean

param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SkipInstaller,
    [switch]$Clean,
    [switch]$PyInstaller
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $ProjectRoot "dist"
$InstallerDir = Join-Path $ProjectRoot "installer"
$PythonVersion = "3.11.9"
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "         MiroFish Windows Builder" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if ($PyInstaller) {
    Write-Host "Mode: PyInstaller (large, standalone)" -ForegroundColor Magenta
} else {
    Write-Host "Mode: Embedded Python (recommended)" -ForegroundColor Magenta
}
Write-Host ""

if ($Clean -or -not (Test-Path $DistDir)) {
    Write-Host "[1/5] Cleaning output..." -ForegroundColor Yellow
    if (Test-Path $DistDir) {
        Remove-Item -Recurse -Force $DistDir
    }
    New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
}

$MiroFishDist = Join-Path $DistDir "MiroFish"
New-Item -ItemType Directory -Force -Path $MiroFishDist | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $MiroFishDist "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $MiroFishDist "frontend") | Out-Null

if (-not $SkipFrontend) {
    Write-Host "[2/5] Building frontend..." -ForegroundColor Yellow
    Push-Location (Join-Path $ProjectRoot "frontend")
    try {
        npm install
        npm run build
        $FrontendDist = Join-Path -Path $ProjectRoot -ChildPath "frontend\\dist"
        $TargetFrontendDist = Join-Path -Path $MiroFishDist -ChildPath "frontend\\dist"
        if (Test-Path $FrontendDist) {
            if (Test-Path $TargetFrontendDist) {
                Remove-Item -Recurse -Force $TargetFrontendDist
            }
            Copy-Item -Recurse -Force $FrontendDist $TargetFrontendDist
            Write-Host "  Frontend build complete" -ForegroundColor Green
        } else {
            throw "Frontend build failed: dist not found"
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[2/5] Skipped frontend build" -ForegroundColor Gray
}

if (-not $SkipBackend) {
    Write-Host "[3/5] Preparing backend..." -ForegroundColor Yellow
    if ($PyInstaller) {
        Write-Host "  Using PyInstaller..." -ForegroundColor Gray
        Push-Location (Join-Path $ProjectRoot "backend")
        try {
            uv sync
            uv pip install pyinstaller
            uv run pyinstaller `
                --name "mirofish_backend" `
                --distpath "$DistDir\backend_temp" `
                --workpath "$DistDir\build" `
                --specpath "$DistDir" `
                --add-data "app;app" `
                --hidden-import "flask" `
                --hidden-import "flask_cors" `
                --hidden-import "openai" `
                --hidden-import "zep_cloud" `
                --hidden-import "pydantic" `
                --hidden-import "dotenv" `
                --hidden-import "charset_normalizer" `
                --hidden-import "chardet" `
                --hidden-import "fitz" `
                --noconfirm `
                --console `
                run.py
            $BackendBuild = Join-Path -Path $DistDir -ChildPath "backend_temp\\mirofish_backend"
            if (Test-Path $BackendBuild) {
                Copy-Item -Recurse -Force "$BackendBuild\*" (Join-Path $MiroFishDist "backend")
                Write-Host "  Backend build complete" -ForegroundColor Green
            } else {
                throw "Backend build failed"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "  Downloading embedded Python $PythonVersion..." -ForegroundColor Gray
        $PythonZip = Join-Path $DistDir "python-embed.zip"
        $PythonDir = Join-Path $MiroFishDist "python"
        if (-not (Test-Path $PythonZip)) {
            Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $PythonZip
        }
        Write-Host "  Extracting embedded Python..." -ForegroundColor Gray
        Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force

        $PthFile = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
        if ($PthFile) {
            $PthContent = Get-Content $PthFile.FullName
            $PthContent = $PthContent -replace "^#import site", "import site"
            if ($PthContent -notcontains "Lib\site-packages") {
                $PthContent += "Lib\site-packages"
            }
            Set-Content -Path $PthFile.FullName -Value $PthContent
        }

        Write-Host "  Installing pip..." -ForegroundColor Gray
        $GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
        $GetPipPath = Join-Path $DistDir "get-pip.py"
        if (-not (Test-Path $GetPipPath)) {
            Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath
        }
        $PythonExe = Join-Path $PythonDir "python.exe"
        & $PythonExe $GetPipPath --no-warn-script-location

        Write-Host "  Installing backend deps..." -ForegroundColor Gray
        $RequirementsFile = Join-Path -Path $ProjectRoot -ChildPath "backend\\requirements.txt"
        & $PythonExe -m pip install -r $RequirementsFile --no-warn-script-location -q

        Write-Host "  Copying backend sources..." -ForegroundColor Gray
        $BackendSrc = Join-Path -Path $ProjectRoot -ChildPath "backend"
        $BackendDst = Join-Path -Path $MiroFishDist -ChildPath "backend"
        Copy-Item -Force (Join-Path -Path $BackendSrc -ChildPath "run.py") $BackendDst
        Copy-Item -Recurse -Force (Join-Path -Path $BackendSrc -ChildPath "app") (Join-Path -Path $BackendDst -ChildPath "app")
        Write-Host "  Backend prepared" -ForegroundColor Green
    }
} else {
    Write-Host "[3/5] Skipped backend" -ForegroundColor Gray
}

Write-Host "[4/5] Building launcher..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    $pip = pip --version 2>$null
    if (-not $?) {
        Write-Host "  Installing PyInstaller..." -ForegroundColor Gray
    }
    pip install pyinstaller -q
    pyinstaller `
        --name "MiroFish" `
        --distpath "$DistDir\launcher_temp" `
        --workpath "$DistDir\build" `
        --specpath "$DistDir" `
        --icon "$InstallerDir\MiroFish.ico" `
        --onefile `
        --windowed `
        --noconfirm `
        launcher.py
    $LauncherExe = Join-Path -Path $DistDir -ChildPath "launcher_temp\\MiroFish.exe"
    Copy-Item -Force $LauncherExe $MiroFishDist
    Write-Host "  Launcher built" -ForegroundColor Green
} finally {
    Pop-Location
}

if (-not $SkipInstaller) {
    Write-Host "[5/5] Building installer..." -ForegroundColor Yellow
    $ISCCPaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $ISCC = $null
    foreach ($path in $ISCCPaths) {
        if (Test-Path $path) {
            $ISCC = $path
            break
        }
    }
    if ($ISCC) {
        Push-Location $InstallerDir
        try {
            & $ISCC "setup.iss"
            Write-Host "  Installer built" -ForegroundColor Green
            Write-Host ("  Output: {0}" -f (Join-Path $InstallerDir "output")) -ForegroundColor Cyan
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "  Inno Setup not found; skipping installer" -ForegroundColor Yellow
        Write-Host "  Install Inno Setup 6: https://jrsoftware.org/isinfo.php" -ForegroundColor Yellow
    }
} else {
    Write-Host "[5/5] Skipped installer" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Cleaning temp files..." -ForegroundColor Gray
Remove-Item -Recurse -Force (Join-Path $DistDir "backend_temp") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $DistDir "launcher_temp") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $DistDir "build") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $DistDir "*.spec") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $DistDir "python-embed.zip") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $DistDir "get-pip.py") -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "               Done" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Output: $MiroFishDist" -ForegroundColor Cyan
if (Test-Path (Join-Path $InstallerDir "output")) {
    Write-Host ("Installer: {0}" -f (Join-Path $InstallerDir "output")) -ForegroundColor Cyan
}
Write-Host ""
