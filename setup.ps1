param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required. Pass -Python with its executable path.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' scripts\setup_models.py
if ($LASTEXITCODE -ne 0) { throw 'Model provisioning failed.' }
Write-Host 'Ready. Run: powershell -ExecutionPolicy Bypass -File run.ps1'
