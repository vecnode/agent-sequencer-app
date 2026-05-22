@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 exit /b %errorlevel%

set "web_host=%WEB_HOST%"
if not defined web_host set "web_host=127.0.0.1"

set "web_port=%WEB_PORT%"
if not defined web_port set "web_port=8000"

set "browser_host=%web_host%"
if /i "%browser_host%"=="0.0.0.0" set "browser_host=127.0.0.1"
set "platform_url=http://%browser_host%:%web_port%"

uv pip install -e .
if errorlevel 1 (
	popd
	exit /b %errorlevel%
)

set "chrome_exe="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "chrome_exe=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined chrome_exe if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "chrome_exe=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined chrome_exe for %%I in (chrome.exe) do set "chrome_exe=%%~$PATH:I"

start "Comms Platform" cmd /k "cd /d ""%~dp0"" && uv run python -m comms_platform.main"

if defined chrome_exe (
	start "" "%chrome_exe%" "%platform_url%"
) else (
	start "" "%platform_url%"
)

popd
exit /b 0
