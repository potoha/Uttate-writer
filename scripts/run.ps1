$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot ".uv-python"
$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv"

Push-Location $projectRoot
try {
    uv run --no-sync uttate
} finally {
    Pop-Location
}

