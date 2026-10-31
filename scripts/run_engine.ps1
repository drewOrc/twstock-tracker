# Supervisor loop for the engine. Started by the scheduled task (see service_install.ps1).
# Restarts uvicorn if it ever exits; logs go to data\logs\engine.log (rotated by the app),
# engine-stderr.log (uvicorn console) and supervisor.log (this script).
#
# Stop-ScheduledTask kills only this PowerShell process, not the python it spawned, so every
# start first reclaims the port from any orphaned server. Use service_stop.ps1 to stop cleanly.
param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1"
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supLog = Join-Path $logDir "supervisor.log"
$errLog = Join-Path $logDir "engine-stderr.log"
. (Join-Path $PSScriptRoot "common.ps1")

while ($true) {
    $killed = Stop-PortOwner $Port "*uvicorn app.main*"
    if ($killed) { "$(Get-Date -Format s) reclaimed port $Port from pid $($killed -join ',')" | Out-File -Append -Encoding utf8 $supLog }
    "$(Get-Date -Format s) starting engine on ${BindHost}:$Port" | Out-File -Append -Encoding utf8 $supLog
    # redirect inside cmd so stderr is written as raw UTF-8 bytes (PowerShell 5.1's 2>> re-encodes as UTF-16)
    & cmd /c "python -X utf8 -m uvicorn app.main:app --host $BindHost --port $Port --no-access-log 2>>`"$errLog`""
    "$(Get-Date -Format s) engine exited with code $LASTEXITCODE; restarting in 5s" | Out-File -Append -Encoding utf8 $supLog
    Start-Sleep -Seconds 5
}
