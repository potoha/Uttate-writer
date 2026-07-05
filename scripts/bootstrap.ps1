$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot ".uv-python"
$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install uv before running this script."
}

Push-Location $projectRoot
try {
    uv python install 3.12 --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Python 3.12."
    }

    uv sync --all-groups
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to sync dependencies."
    }

    Write-Host "Uttate local development environment is ready." -ForegroundColor Green
    uv run python --version
} finally {
    Pop-Location
}
