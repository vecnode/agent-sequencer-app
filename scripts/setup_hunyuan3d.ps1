# One-time Hunyuan3D-2.1 vendor setup for TT3D on Windows.
# Run from the repository root: .\scripts\setup_hunyuan3d.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor\Hunyuan3D-2.1"
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "[tt3d] Repository root: $Root"
Write-Host "[tt3d] Vendor target:  $Vendor"

if (-not (Test-Path $Vendor)) {
    Write-Host "[tt3d] Cloning Tencent Hunyuan3D-2.1..."
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "vendor") | Out-Null
    git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git $Vendor
} else {
    Write-Host "[tt3d] Vendor directory already exists; skipping clone."
}

Write-Host "[tt3d] Installing platform dependencies..."
Push-Location $Root
try {
    uv pip install -e .
} finally {
    Pop-Location
}

$Rasterizer = Join-Path $Vendor "hy3dpaint\custom_rasterizer"
if (Test-Path $Rasterizer) {
    $Kernel = Join-Path $Rasterizer "lib\custom_rasterizer_kernel"
    $WinKernel = Join-Path $Rasterizer "lib\custom_rasterizer_kernel_for_windows"
    if (Test-Path $WinKernel) {
        Write-Host "[tt3d] Applying Windows custom_rasterizer kernel sources..."
        Copy-Item "$WinKernel\*" $Kernel -Force
    }

    $Cuda124 = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4"
    if (Test-Path $Cuda124) {
        Write-Host "[tt3d] Using CUDA 12.4 toolkit for custom_rasterizer build..."
        $env:CUDA_PATH = $Cuda124
        $env:PATH = "$Cuda124\bin;$env:PATH"
    } else {
        Write-Host "[tt3d] WARNING: CUDA 12.4 toolkit not found at '$Cuda124'."
        Write-Host "[tt3d]          Install CUDA 12.4 to match PyTorch cu124 before building custom_rasterizer."
    }

    Write-Host "[tt3d] Building custom_rasterizer CUDA extension..."
    Push-Location $Rasterizer
    try {
        uv pip install -e . --no-build-isolation
    } finally {
        Pop-Location
    }

    Write-Host "[tt3d] Verifying custom_rasterizer..."
    & $Py -c @"
from comms_platform.inference.tt3d import _verify_custom_rasterizer
ok, err = _verify_custom_rasterizer()
if not ok:
    raise SystemExit(err or 'custom_rasterizer verification failed')
print('custom_rasterizer OK')
"@
}

$RealEsrgan = Join-Path $Vendor "hy3dpaint\ckpt\RealESRGAN_x4plus.pth"
if (-not (Test-Path $RealEsrgan)) {
    Write-Host "[tt3d] Downloading Real-ESRGAN weights..."
    New-Item -ItemType Directory -Force -Path (Split-Path $RealEsrgan) | Out-Null
    Invoke-WebRequest `
        -Uri "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" `
        -OutFile $RealEsrgan
}

Write-Host "[tt3d] Installing triton-windows for xFormers on Windows..."
uv pip install "triton-windows>=3.2.0.post21,<3.3"

Write-Host "[tt3d] Applying optional-bpy vendor patch (Python 3.12 has no bpy wheel)..."
& $Py -c "from comms_platform.inference.tt3d import _patch_hunyuan_mesh_utils_optional_bpy, _apply_tt3d_compat_shims; _patch_hunyuan_mesh_utils_optional_bpy(); _apply_tt3d_compat_shims()"

Write-Host "[tt3d] Setup complete."
Write-Host "[tt3d] Note: pip install bpy is NOT available on Python 3.12."
Write-Host "[tt3d]       Install Blender desktop and set BLENDER_EXE for GLB export, or use Python 3.11/3.13 for native bpy."
