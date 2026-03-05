# Install Redis in WSL for local development

Write-Host "Installing Redis in WSL..." -ForegroundColor Green

# Check if WSL is installed
$wslVersion = wsl --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] WSL is not installed or not working" -ForegroundColor Red
    Write-Host "Please install WSL first: wsl --install" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] WSL is available" -ForegroundColor Green

# Update package list and install Redis
Write-Host "Updating WSL package list..." -ForegroundColor Cyan
wsl sudo apt-get update -y

Write-Host "Installing Redis server..." -ForegroundColor Cyan
wsl sudo apt-get install -y redis-server

# Start Redis
Write-Host "Starting Redis server..." -ForegroundColor Cyan
wsl sudo service redis-server start

# Test Redis
Write-Host "Testing Redis connection..." -ForegroundColor Cyan
$pingResult = wsl redis-cli ping
if ($pingResult -eq "PONG") {
    Write-Host "[OK] Redis is running successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To start Redis in future sessions, run:" -ForegroundColor Yellow
    Write-Host "  wsl sudo service redis-server start" -ForegroundColor White
} else {
    Write-Host "[ERROR] Redis installation failed" -ForegroundColor Red
    exit 1
}
