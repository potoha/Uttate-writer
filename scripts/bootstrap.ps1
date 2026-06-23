$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot ".uv-python"
$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv が見つかりません。先に uv をインストールしてください。"
}

Push-Location $projectRoot
try {
    uv python install 3.12 --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.12 のインストールに失敗しました。"
    }

    uv sync --all-groups
    if ($LASTEXITCODE -ne 0) {
        throw "依存関係の同期に失敗しました。"
    }

    Write-Host "Uttate のローカル開発環境を構築しました。" -ForegroundColor Green
    uv run python --version
} finally {
    Pop-Location
}
