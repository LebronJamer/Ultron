# ============================================================================
# Ultron — local build: venv -> deps -> models -> PyInstaller -> Inno Setup
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#         powershell ... -Version 1.0.1
# ============================================================================
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # UltronV1
Push-Location $root

try {
    # ---- 1. virtual environment ------------------------------------------
    if (-not (Test-Path ".venv")) {
        Write-Host "[1/5] Creating virtual environment..." -ForegroundColor Cyan
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "python not found on PATH" }
    } else {
        Write-Host "[1/5] Reusing virtual environment." -ForegroundColor Cyan
    }
    $py = ".venv\Scripts\python.exe"
    $pip = ".venv\Scripts\pip.exe"

    # ---- 2. dependencies ---------------------------------------------------
    Write-Host "[2/5] Installing dependencies..." -ForegroundColor Cyan
    & $pip install --upgrade pip --quiet
    & $pip install -r requirements.txt --quiet
    & $pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    # ---- 3. speech model ----------------------------------------------------
    Write-Host "[3/5] Ensuring offline speech model..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\download_models.ps1
    if ($LASTEXITCODE -ne 0) { throw "model download failed" }

    # ---- 4. PyInstaller -------------------------------------------------------
    Write-Host "[4/5] Building Ultron.exe with PyInstaller..." -ForegroundColor Cyan
    & .venv\Scripts\pyinstaller.exe --noconfirm --clean `
        --distpath dist --workpath build scripts\ultron.spec
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

    # ---- 5. Inno Setup ---------------------------------------------------------
    Write-Host "[5/5] Compiling setup.exe with Inno Setup..." -ForegroundColor Cyan
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        Write-Warning "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php"
        Write-Warning "The raw app is ready at: $root\dist\Ultron\Ultron.exe"
    } else {
        & $iscc "/DMyAppVersion=$Version" "installer\ultron.iss"
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
        Write-Host ""
        Write-Host "DONE -> $root\installer\Output\UltronSetup-$Version-x64.exe" -ForegroundColor Green
    }
} finally {
    Pop-Location
}
