# Start MocaDiff in development mode (backend + frontend).
# Usage:  .\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# npm cache must live inside the workspace (sandbox blocks %LOCALAPPDATA%).
$env:npm_config_cache = Join-Path $root ".npm-cache"
New-Item -ItemType Directory -Force $env:npm_config_cache | Out-Null

if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "[MocaDiff] installing frontend dependencies..."
    Push-Location (Join-Path $root "frontend")
    npm install
    Pop-Location
}

# Start backend in a new window.
$backend = Join-Path $root "backend"
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload"
) -WorkingDirectory $backend

# Start frontend in a new window.
$frontend = Join-Path $root "frontend"
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit", "-Command",
    "`$env:npm_config_cache='$($env:npm_config_cache)'; Set-Location '$frontend'; npm run dev -- --host 127.0.0.1"
) -WorkingDirectory $frontend

Start-Sleep -Seconds 3
Write-Host ""
Write-Host "MocaDiff dev servers starting:"
Write-Host "  Frontend : http://127.0.0.1:5173"
Write-Host "  Backend  : http://127.0.0.1:8787/api/health"
Write-Host ""
Write-Host "Close the two spawned windows to stop."
