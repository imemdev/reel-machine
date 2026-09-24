# Start Reel Machine on Windows without installing or downloading anything.
# Usage (from the project folder):  .\scripts\run-local.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Write-Error 'Missing project dependencies. Follow the Windows steps in README.md first.'
    exit 1
}
& $python (Join-Path $root 'scripts\run_local.py')
exit $LASTEXITCODE
