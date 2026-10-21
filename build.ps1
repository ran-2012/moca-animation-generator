# Build the React frontend and prepare a single-port production run.
# Usage:  .\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$env:npm_config_cache = Join-Path $root ".npm-cache"
New-Item -ItemType Directory -Force $env:npm_config_cache | Out-Null

Push-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Pop-Location

Write-Host ""
Write-Host "[MocaDiff] frontend built to frontend/dist"
Write-Host "Start the single-port server with:"
Write-Host "  cd backend"
Write-Host "  python -m uvicorn app.main:app --host 127.0.0.1 --port 8787"
