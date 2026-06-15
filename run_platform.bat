@echo off

setlocal EnableExtensions



pushd "%~dp0"

if errorlevel 1 exit /b %errorlevel%



set "PY=.venv\Scripts\python.exe"

set "UV_PIP=uv pip"



set "web_host=%WEB_HOST%"

if not defined web_host set "web_host=127.0.0.1"



set "web_port=%WEB_PORT%"

if not defined web_port set "web_port=8000"



set "platform_url=http://%web_host%:%web_port%"



call :ensure_venv

if errorlevel 1 goto :fail



call :ensure_project

if errorlevel 1 goto :fail



call :ensure_cuda_torch

if errorlevel 1 goto :fail



call :ensure_xformers

if errorlevel 1 goto :fail



call :ensure_triton_windows

if errorlevel 1 goto :fail



call :ensure_tt3d_patches



set HF_HUB_DISABLE_XET=1



rem Use the venv interpreter directly so uv does not re-sync packages on startup.

start "Inference API" cmd /k "cd /d ""%~dp0"" && set HF_HUB_DISABLE_XET=1 && .venv\Scripts\python.exe -m comms_platform.main"

echo [startup] Inference API running at %platform_url%



popd

exit /b 0



:fail

popd

exit /b 1



:ensure_venv

if exist "%PY%" (

	echo [setup] Virtual environment ready.

	exit /b 0

)

echo [setup] Creating virtual environment...

uv venv

if errorlevel 1 exit /b 1

exit /b 0



:ensure_project

%UV_PIP% show ai-comms-platform >nul 2>&1

if not errorlevel 1 (

	echo [setup] Platform package already installed; skipping editable install.

	exit /b 0

)

echo [setup] Installing platform package editable...

%UV_PIP% install -e .

if errorlevel 1 exit /b 1

echo [setup] Platform package installed.

exit /b 0



:ensure_cuda_torch

%UV_PIP% show torch 2>nul | findstr /I /C:"2.6.0+cu124" >nul 2>&1

if not errorlevel 1 (

	echo [setup] CUDA PyTorch cu124 already installed; skipping.

	exit /b 0

)

echo [setup] Installing CUDA-enabled PyTorch cu124...

%UV_PIP% install --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0+cu124

if errorlevel 1 (

	echo [setup] CUDA wheel install failed, falling back to default PyTorch install.

	%UV_PIP% install torch torchvision torchaudio

	if errorlevel 1 exit /b 1

) else (

	echo [setup] CUDA-enabled PyTorch installed.

)

exit /b 0



:ensure_xformers

%UV_PIP% show xformers 2>nul | findstr /C:"0.0.29.post2" >nul 2>&1

if not errorlevel 1 (

	echo [setup] xFormers 0.0.29.post2 already installed; skipping.

	exit /b 0

)

echo [setup] Installing xFormers acceleration 0.0.29.post2...

%UV_PIP% install --no-deps xformers==0.0.29.post2

if errorlevel 1 (

	echo [setup] xFormers install failed; continuing without it.

) else (

	echo [setup] xFormers acceleration is active.

)

exit /b 0



:ensure_triton_windows

%UV_PIP% show triton-windows >nul 2>&1

if not errorlevel 1 (

	echo [setup] triton-windows already installed; skipping.

	exit /b 0

)

echo [setup] Installing triton-windows for PyTorch 2.6 / xFormers...

%UV_PIP% install "triton-windows>=3.2.0.post21,<3.3"

if errorlevel 1 (

	echo [setup] triton-windows install failed; xFormers may log a Triton warning.

) else (

	echo [setup] triton-windows is active.

)

exit /b 0



:ensure_tt3d_patches

echo [setup] Applying TT3D runtime patches if Hunyuan3D vendor is present...

"%PY%" -c "from comms_platform.inference.tt3d import prepare_tt3d_runtime; prepare_tt3d_runtime()" >nul 2>&1

exit /b 0


