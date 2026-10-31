<#
.SYNOPSIS
  Keep a temporary public HTTPS URL (*.trycloudflare.com) pointed at the engine, started at logon and
  restarted on failure. Needs no Cloudflare account and no domain. The URL changes on every restart;
  the engine shows the current one in /api/health and the 系統 page and pushes it to LINE / Email
  when it changes (job "tunnel_watch").

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\tunnel_quick_install.ps1 -Start

.NOTES
  Same task name as tunnel_install.ps1 ("TWStock Tunnel"), so installing a named tunnel later
  replaces this one. Remove with: Unregister-ScheduledTask 'TWStock Tunnel' -Confirm:$false
#>
param([int]$Port = 8000, [switch]$Start)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = "$env:ProgramFiles\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) {
    Write-Host "installing cloudflared..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
}

$ps = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $ps `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'run_quick_tunnel.ps1')`" -Port $Port" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "TWStock Tunnel" -Action $action -Trigger $trigger -Settings $settings `
    -Description "TW Stock Tracker: temporary Cloudflare quick tunnel (URL in data\tunnel-url.txt)" -Force | Out-Null
Write-Host "registered task 'TWStock Tunnel' (quick tunnel). Current URL: data\tunnel-url.txt, /api/health -> public_url"
if ($Start) {
    Start-ScheduledTask -TaskName "TWStock Tunnel"
    Start-Sleep -Seconds 8
    $f = Join-Path $root "data\tunnel-url.txt"
    if (Test-Path $f) { Write-Host ("public URL: " + (Get-Content $f -TotalCount 1)) -ForegroundColor Green } else { Write-Host "started; URL not up yet, check data\tunnel-url.txt in a few seconds" }
}
