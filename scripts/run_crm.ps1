# Supervisor loop for Stock CRM (the sibling repository). Started by the scheduled task when
# service_install.ps1 is run with -WithCrm. Nothing in stockcrm is modified; it is only launched.
# Every start first reclaims the port from an orphaned server (see run_engine.ps1 for why).
param(
    [int]$Port = 8765,
    [string]$CrmPath = ""
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
if (-not $CrmPath) { $CrmPath = Join-Path (Split-Path -Parent $root) "stockcrm" }
if (-not (Test-Path (Join-Path $CrmPath "stockcrm\api.py"))) {
    Write-Error "Stock CRM not found at $CrmPath"
    exit 1
}
. (Join-Path $PSScriptRoot "common.ps1")
Set-Location $CrmPath
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supLog = Join-Path $logDir "crm-supervisor.log"
$errLog = Join-Path $logDir "crm-stderr.log"

while ($true) {
    $killed = Stop-PortOwner $Port "*stockcrm.api*"
    if ($killed) { "$(Get-Date -Format s) reclaimed port $Port from pid $($killed -join ',')" | Out-File -Append -Encoding utf8 $supLog }
    "$(Get-Date -Format s) starting stock crm on 127.0.0.1:$Port" | Out-File -Append -Encoding utf8 $supLog
    & cmd /c "python -X utf8 -m stockcrm.api $Port 2>>`"$errLog`""
    "$(Get-Date -Format s) stock crm exited with code $LASTEXITCODE; restarting in 5s" | Out-File -Append -Encoding utf8 $supLog
    Start-Sleep -Seconds 5
}
