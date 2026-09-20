# SmartClipboard PyInstaller Build Script
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Building SmartClipboard Standalone EXE " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Stop any running instances to avoid file-lock errors during linking
Stop-Process -Name "SmartClipboard" -Force -ErrorAction SilentlyContinue

if (-not (Test-Path "app_icon.ico")) {
    Write-Host "Generating icon..." -ForegroundColor Yellow
    python generate_icon.py
}

Write-Host "Running unit tests..." -ForegroundColor Yellow
python -m unittest discover -s tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Unit tests failed!"
    exit 1
}
Write-Host "Unit tests passed!" -ForegroundColor Green

Write-Host "Compiling with PyInstaller..." -ForegroundColor Yellow
python -m PyInstaller --clean `
    --name "SmartClipboard" `
    --onefile `
    --windowed `
    --icon "app_icon.ico" `
    --hidden-import "PIL.BmpImagePlugin" `
    --hidden-import "PIL.PngImagePlugin" `
    --hidden-import "pystray._win32" `
    main.py

if ($LASTEXITCODE -eq 0) {
    $exePath = Join-Path $scriptDir "dist\SmartClipboard.exe"
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " Build Succeeded!" -ForegroundColor Green
    Write-Host " Standalone EXE Path: $exePath" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Error "Build failed. Check output above."
    exit 1
}
