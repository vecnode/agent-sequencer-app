@echo off
setlocal EnableExtensions
pushd "%~dp0"
if errorlevel 1 exit /b %errorlevel%

set "web_host=%WEB_HOST%"
if not defined web_host set "web_host=127.0.0.1"
set "web_port=%WEB_PORT%"
if not defined web_port set "web_port=8000"
set "platform_url=http://%web_host%:%web_port%"

echo [setup] Syncing environment from pyproject.toml and uv.lock...
uv sync --extra gpu --extra tt3d
if errorlevel 1 goto :fail

set HF_HUB_DISABLE_XET=1

echo [startup] Launching inference API gateway and worker processes...
start "Inference API" cmd /k "cd /d ""%~dp0"" && set HF_HUB_DISABLE_XET=1 && uv run python -m comms_platform.main"
echo [startup] Inference API running at %platform_url%

popd
exit /b 0

:fail
popd
exit /b 1
