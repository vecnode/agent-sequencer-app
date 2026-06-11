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

echo [setup] Trying CUDA-enabled PyTorch install (cu124)...
uv pip install --index-url https://download.pytorch.org/whl/cu124 --upgrade --force-reinstall torch torchvision torchaudio >nul 2>&1
if errorlevel 1 (
	echo [setup] CUDA wheel install failed, falling back to default PyTorch install.
	uv pip install torch torchvision torchaudio
	if errorlevel 1 (
		popd
		exit /b %errorlevel%
	)
) else (
	echo [setup] CUDA-enabled PyTorch installed.
)

uv pip install -e ".[tt3d]"
if errorlevel 1 (
	popd
	exit /b %errorlevel%
)

echo [setup] Installing TT3D requirements pin file...
uv pip install -r requirements-tt3d.txt >nul 2>&1

echo [setup] Applying TT3D runtime patches (if Hunyuan3D vendor is present)...
uv run python -c "from comms_platform.inference.tt3d import prepare_tt3d_runtime; prepare_tt3d_runtime()" >nul 2>&1

echo [setup] Re-applying CUDA-enabled PyTorch wheel after editable install...
uv pip install --index-url https://download.pytorch.org/whl/cu124 --upgrade --force-reinstall torch torchvision torchaudio >nul 2>&1
if errorlevel 1 (
	echo [setup] CUDA torch reinstall failed; keeping the currently installed torch build.
) else (
	echo [setup] CUDA torch wheel is active.
)

echo [setup] Installing xFormers acceleration (0.0.29.post2)...
uv pip install --no-deps --upgrade xformers==0.0.29.post2 >nul 2>&1
if errorlevel 1 (
	echo [setup] xFormers install failed; continuing without it.
) else (
	echo [setup] xFormers acceleration is active.
)

echo [setup] Installing Triton for Windows (PyTorch 2.6 / xFormers)...
uv pip install "triton-windows>=3.2.0.post21,<3.3" >nul 2>&1
if errorlevel 1 (
	echo [setup] triton-windows install failed; xFormers may log a Triton warning.
) else (
	echo [setup] triton-windows is active.
)

set HF_HUB_DISABLE_XET=1

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
