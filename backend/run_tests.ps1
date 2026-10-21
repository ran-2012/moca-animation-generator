# Run backend tests.
# Uses backend/vendor when present (the original sandbox fallback); otherwise
# relies on the packages installed from requirements-dev.txt.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$vendor = Join-Path $root "vendor"
if (Test-Path $vendor) {
    $env:PYTHONPATH = $vendor
} else {
    $env:PYTHONPATH = $root
}

python -m pytest tests -q
