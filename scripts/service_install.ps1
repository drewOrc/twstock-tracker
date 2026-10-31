<#
.SYNOPSIS
  Register the engine (and optionally Stock CRM) as Windows scheduled tasks that start at logon,
  run hidden, and restart on failure. No admin rights, no third-party service wrapper.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\service_install.ps1            # engine only
  powershell -ExecutionPolicy Bypass -File scripts\service_install.ps1 -WithCrm   # engine + Stock CRM
  powershell -ExecutionPolicy Bypass -File scripts\service_install.ps1 -Start     # also start now

.NOTES
  Uninstall with scripts\service_uninstall.ps1. Logs: data\logs\engine.log, supervisor.log,
  crm-supervisor.log. The tasks run only while you are logged in (interactive session); the PC must
  be awake at the scheduled times. Check the "系統" page of the dashboard for data freshness.
#>
param(
    [switch]$WithCrm,
    [switch]$Start,
    [int]$Port = 8000,
    [int]$CrmPort = 8765,
    [string]$CrmPath = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ps = (Get-Command powershell.exe).Source

function Register-Supervisor([string]$Name, [string]$Script, [string]$Args) {
    $action = New-ScheduledTaskAction -Execute $ps `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`" $Args" `
        -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
        -Description "TW Stock Tracker: $Name (auto-start at logon, auto-restart)" -Force | Out-Null
    Write-Host "registered task '$Name' -> $Script $Args"
}

Register-Supervisor "TWStock Engine" (Join-Path $PSScriptRoot "run_engine.ps1") "-Port $Port"
if ($WithCrm) {
    $crmArgs = "-Port $CrmPort"
    if ($CrmPath) { $crmArgs += " -CrmPath `"$CrmPath`"" }
    Register-Supervisor "TWStock CRM" (Join-Path $PSScriptRoot "run_crm.ps1") $crmArgs
}

if ($Start) {
    Start-ScheduledTask -TaskName "TWStock Engine"
    if ($WithCrm) { Start-ScheduledTask -TaskName "TWStock CRM" }
    Write-Host "started. engine: http://127.0.0.1:$Port" -ForegroundColor Green
} else {
    Write-Host "tasks will start at next logon; run with -Start to launch them now."
}
