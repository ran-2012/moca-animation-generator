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

$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$backendProcess = $null
$frontendProcess = $null

try {
    $backendProcess = Start-Process -FilePath "python" -ArgumentList @(
        "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8787", "--reload"
    ) -WorkingDirectory $backend -NoNewWindow -PassThru

    $frontendProcess = Start-Process -FilePath "npm.cmd" -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1"
    ) -WorkingDirectory $frontend -NoNewWindow -PassThru

    Write-Host ""
    Write-Host "MocaDiff dev servers starting in this console:"
    Write-Host "  Frontend : http://127.0.0.1:5173"
    Write-Host "  Backend  : http://127.0.0.1:8787/api/health"
    Write-Host "  Press Ctrl+C to stop both servers."
    Write-Host ""

    Wait-Process -Id $backendProcess.Id, $frontendProcess.Id
}
finally {
    foreach ($process in @($backendProcess, $frontendProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
