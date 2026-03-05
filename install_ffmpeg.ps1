# Install FFmpeg for Windows

Write-Host "Installing FFmpeg..." -ForegroundColor Green

# Check if FFmpeg is already installed
$ffmpegExists = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegExists) {
    Write-Host "[OK] FFmpeg is already installed" -ForegroundColor Green
    ffmpeg -version | Select-Object -First 1
    exit 0
}

# Check if winget is available
$wingetExists = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetExists) {
    Write-Host "Installing FFmpeg via winget..." -ForegroundColor Cyan
    winget install --id=Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] FFmpeg installed successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Please restart your terminal for PATH changes to take effect" -ForegroundColor Yellow
        exit 0
    }
}

# Check if Chocolatey is available
$chocoExists = Get-Command choco -ErrorAction SilentlyContinue
if ($chocoExists) {
    Write-Host "Installing FFmpeg via Chocolatey..." -ForegroundColor Cyan
    choco install ffmpeg -y

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] FFmpeg installed successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Please restart your terminal for PATH changes to take effect" -ForegroundColor Yellow
        exit 0
    }
}

# Manual installation instructions
Write-Host "[WARN] Neither winget nor Chocolatey is available" -ForegroundColor Yellow
Write-Host ""
Write-Host "Please install FFmpeg manually:" -ForegroundColor White
Write-Host "1. Download from: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -ForegroundColor White
Write-Host "2. Extract to: C:\ffmpeg" -ForegroundColor White
Write-Host "3. Add to PATH: C:\ffmpeg\bin" -ForegroundColor White
Write-Host ""
Write-Host "Or install winget/Chocolatey first, then run this script again" -ForegroundColor White
