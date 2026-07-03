$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

if (-not (Test-Path $VenvDir)) {
    Write-Host "==> Creating virtual environment..."
    python -m venv $VenvDir
}

$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"
. $Activate

Write-Host "==> Installing dependencies..."
pip install -r (Join-Path $ScriptDir "requirements.txt")

Write-Host "==> Done! Run .\dev.ps1 to start the server."
