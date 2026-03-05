# Setup PostgreSQL database for local development
$env:PGPASSWORD = "@Satyajit96k"

# Check if database exists
$dbExists = psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='content_engine'"

if ($dbExists -eq "1") {
    Write-Host "[OK] Database 'content_engine' already exists"
} else {
    Write-Host "[INFO] Creating database 'content_engine'..."
    psql -U postgres -c "CREATE DATABASE content_engine;"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Database created successfully"
    } else {
        Write-Host "[ERROR] Failed to create database"
        exit 1
    }
}

# Verify database exists
psql -U postgres -l | findstr content_engine
