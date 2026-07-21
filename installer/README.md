# MiroFish Windows Installer

This directory contains scripts to build Windows executable installers for MiroFish.

## Prerequisites

- Windows 10 or later
- PowerShell 5.1+
- Python 3.9+ (for embedded mode)
- Node.js 18+ (for frontend build)
- [Inno Setup](https://jrsoftware.org/isinfo.php) (optional, for creating setup.exe)

## Build Methods

### Method 1: Embedded Python Mode (Recommended)

Smaller file size (~200-300MB), faster build:

```powershell
.\installer\build.ps1
```

### Method 2: PyInstaller Mode

Self-contained executable, but larger file size (~1GB+):

```powershell
.\installer\build.ps1 -PyInstaller
```

## Build Options

```powershell
# Skip frontend build (if unchanged)
.\installer\build.ps1 -SkipFrontend

# Skip backend processing (if unchanged)
.\installer\build.ps1 -SkipBackend

# Skip installer creation (only generate executables)
.\installer\build.ps1 -SkipInstaller

# Clean old builds and start fresh
.\installer\build.ps1 -Clean
```

## Output

- `dist/MiroFish_Setup_0.1.1.exe` - Windows installer
- `dist/MiroFish_Portable/` - Portable version (no installation required)

## Installation Flow

1. User downloads and runs `MiroFish_Setup_0.1.1.exe`
2. Setup wizard prompts for API key
3. Installation completes
4. User can launch via desktop shortcut or start menu
5. Browser opens automatically to `http://localhost:5000`

## File Structure

```
installer/
├── build.ps1           # Main build script
├── setup.iss           # Inno Setup configuration
├── embedded/           # Embedded Python files
│   ├── python.zip      # Python runtime
│   └── requirements.txt
├── assets/             # Installer assets
│   ├── icon.ico        # Application icon
│   └── banner.bmp      # Setup wizard banner
└── templates/          # Configuration templates
    ├── config.json.template
    └── start.ps1.template
```

## Development

To modify the installer:

1. Edit `build.ps1` for build process changes
2. Edit `setup.iss` for installer UI changes
3. Edit `start.ps1.template` for launch behavior changes

## Troubleshooting

### Build fails with "Python not found"
Ensure Python 3.9+ is in your PATH:
```powershell
python --version
```

### Build fails with "Inno Setup not found"
Install Inno Setup from https://jrsoftware.org/isdl.php

### Installer too large
Use `-SkipFrontend` if frontend hasn't changed, or use embedded mode instead of PyInstaller.
