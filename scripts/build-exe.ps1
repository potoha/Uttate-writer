$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot ".uv-python"
$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv"
$venvScripts = Join-Path $projectRoot ".venv\Scripts"
$env:PATH = "$($venvScripts);$env:PATH"

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcherPath = Join-Path $projectRoot "uttate_launcher.py"
$targetExe = Join-Path $projectRoot "uttate-writer.exe"

Push-Location $projectRoot
try {
    if (Test-Path $targetExe) {
        Remove-Item -LiteralPath $targetExe -Force
    }

    & $pythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name uttate-writer `
        --paths src `
        --collect-data uttate `
        $launcherPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $candidate = Join-Path $projectRoot "dist\uttate-writer.exe"

    if (-not (Test-Path $candidate)) {
        throw "PyInstaller did not produce uttate-writer.exe"
    }

    Copy-Item -LiteralPath $candidate -Destination $targetExe -Force
    & $pythonPath -c "from pathlib import Path; p=Path('uttate-writer.exe'); print(f'created {p.resolve()} ({p.stat().st_size} bytes)')"
} finally {
    Pop-Location
}
