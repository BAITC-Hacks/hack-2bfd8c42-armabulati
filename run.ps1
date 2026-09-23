$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Run setup.ps1 first to create the environment and download models.'
}
Write-Host 'Dauys Hunt: http://127.0.0.1:8765 (Ctrl+C to stop)'
& $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
exit $LASTEXITCODE
