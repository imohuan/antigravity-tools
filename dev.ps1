$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

if (-not (Test-Path $VenvDir)) {
    Write-Host "Virtual environment not found. Run .\install.ps1 first."
    exit 1
}

$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"
. $Activate

Set-Location $ScriptDir

$Port = 8866
$Existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($Existing) { $Existing | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Write-Host "==> Killed old process on port $Port" }

Write-Host "==> Starting Antigravity Tools Web Server..."
python -m web.server
