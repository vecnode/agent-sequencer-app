# One-time Hunyuan3D-2.1 vendor setup for shape-only TT3D on Windows.
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

Write-Host "[tt3d] Installing dependencies from uv.lock..."
Push-Location $Root
try {
    uv sync --extra gpu --extra tt3d
} finally {
    Pop-Location
}

Write-Host "[tt3d] Shape-only setup complete. Paint/texture pipeline is not required."
