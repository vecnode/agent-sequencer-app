# One-time Hunyuan3D-2.1 vendor setup for TT3D on Windows.
# Run from the repository root: .\scripts\setup_hunyuan3d.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor\Hunyuan3D-2.1"

Write-Host "[tt3d] Repository root: $Root"
Write-Host "[tt3d] Vendor target:  $Vendor"

if (-not (Test-Path $Vendor)) {
    Write-Host "[tt3d] Cloning Tencent Hunyuan3D-2.1..."
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "vendor") | Out-Null
    git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git $Vendor
} else {
    Write-Host "[tt3d] Vendor directory already exists; skipping clone."
}

Write-Host "[tt3d] Installing TT3D Python extras..."
Push-Location $Root
try {
    uv pip install -e ".[tt3d]"
    $Requirements = Join-Path $Root "requirements-tt3d.txt"
    if (Test-Path $Requirements) {
        uv pip install -r $Requirements
    }
} finally {
    Pop-Location
}

$Rasterizer = Join-Path $Vendor "hy3dpaint\custom_rasterizer"
if (Test-Path $Rasterizer) {
    Write-Host "[tt3d] Building custom_rasterizer..."
    Push-Location $Rasterizer
    try {
        uv pip install -e .
    } finally {
        Pop-Location
    }
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
uv run python -c "from comms_platform.inference.tt3d import _patch_hunyuan_mesh_utils_optional_bpy, _apply_tt3d_compat_shims; _patch_hunyuan_mesh_utils_optional_bpy(); _apply_tt3d_compat_shims()"

Write-Host "[tt3d] Setup complete."
Write-Host "[tt3d] Note: pip install bpy is NOT available on Python 3.12."
Write-Host "[tt3d]       Install Blender desktop and set BLENDER_EXE for GLB export, or use Python 3.11/3.13 for native bpy."
