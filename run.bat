@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "UV_PYTHON_INSTALL_DIR=%PROJECT_ROOT%.uv-python"
set "UV_CACHE_DIR=%PROJECT_ROOT%.uv-cache"
set "UV_PROJECT_ENVIRONMENT=%PROJECT_ROOT%.venv"

pushd "%PROJECT_ROOT%"
uv run --no-sync uttate
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
