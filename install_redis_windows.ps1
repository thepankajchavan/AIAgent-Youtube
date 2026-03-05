# Install Memurai (Redis for Windows) using Chocolatey or manual download

Write-Host "Installing Redis for Windows..." -ForegroundColor Green

# Check if Redis is already running
try {
    $testConnection = Test-NetConnection -ComputerName localhost -Port 6379 -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    if ($testConnection.TcpTestSucceeded) {
        Write-Host "[OK] Redis is already running on port 6379" -ForegroundColor Green
        exit 0
    }
} catch {
    # Connection test failed, Redis not running
}

# Check if Chocolatey is available
$chocoExists = Get-Command choco -ErrorAction SilentlyContinue
if ($chocoExists) {
    Write-Host "Installing Memurai (Redis for Windows) via Chocolatey..." -ForegroundColor Cyan
    choco install memurai-developer -y

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Memurai installed successfully!" -ForegroundColor Green
        Write-Host "Starting Memurai service..." -ForegroundColor Cyan
        Start-Service Memurai

        Start-Sleep -Seconds 3

        # Test connection
        $testConnection = Test-NetConnection -ComputerName localhost -Port 6379 -WarningAction SilentlyContinue
        if ($testConnection.TcpTestSucceeded) {
            Write-Host "[OK] Memurai is running on port 6379" -ForegroundColor Green
        }
        exit 0
    }
}

# Manual installation instructions
Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "Manual Redis Installation Required" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Option 1: Install Chocolatey, then run this script again" -ForegroundColor White
Write-Host "  Install Chocolatey: https://chocolatey.org/install" -ForegroundColor Cyan
Write-Host ""
Write-Host "Option 2: Use Docker Desktop (Recommended)" -ForegroundColor White
Write-Host "  docker run -d -p 6379:6379 --name redis redis:7-alpine" -ForegroundColor Cyan
Write-Host ""
Write-Host "Option 3: Install Memurai manually" -ForegroundColor White
Write-Host "  1. Download from: https://www.memurai.com/get-memurai" -ForegroundColor Cyan
Write-Host "  2. Install and start the service" -ForegroundColor Cyan
Write-Host ""
Write-Host "Option 4: Use WSL2 with Ubuntu" -ForegroundColor White
Write-Host "  1. wsl --install Ubuntu" -ForegroundColor Cyan
Write-Host "  2. wsl" -ForegroundColor Cyan
Write-Host "  3. sudo apt-get update && sudo apt-get install -y redis-server" -ForegroundColor Cyan
Write-Host "  4. sudo service redis-server start" -ForegroundColor Cyan
Write-Host ""
