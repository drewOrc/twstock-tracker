<#
.SYNOPSIS
  Expose the engine at a public HTTPS hostname through a named Cloudflare Tunnel, kept alive by a
  scheduled task like the engine itself. No router ports are opened; the engine stays on 127.0.0.1.

.PREREQUISITES
  A domain managed by Cloudflare (free plan is fine). The first run opens a browser once for
  `cloudflared tunnel login`.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\tunnel_install.ps1 -Hostname stocks.example.com

.NOTES
  Afterwards the app is reachable at https://<Hostname>/ with the normal login. Optionally add a
  Cloudflare Access policy (Zero Trust > Access) in front of the hostname as a second layer.
  Remove with: Unregister-ScheduledTask 'TWStock Tunnel'; cloudflared tunnel delete twstock
#>
param(
    [Parameter(Mandatory = $true)][string]$Hostname,
    [string]$TunnelName = "twstock",
    [int]$Port = 8000,
    [switch]$Start
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    Write-Host "installing cloudflared..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
    $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cf) { $cf = "$env:ProgramFiles\cloudflared\cloudflared.exe" }
    if (-not (Test-Path $cf)) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }  # winget MSI installs here
}

$cfDir = Join-Path $env:USERPROFILE ".cloudflared"
if (-not (Test-Path (Join-Path $cfDir "cert.pem"))) {
    Write-Host "log in to Cloudflare in the browser window that opens..." -ForegroundColor Yellow
    & $cf tunnel login
}
$existing = & $cf tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
if (-not $existing) { & $cf tunnel create $TunnelName | Out-Null }
$tunnel = & $cf tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
$id = $tunnel.id
$cred = Join-Path $cfDir "$id.json"

@"
tunnel: $id
credentials-file: $cred
ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:$Port
    originRequest:
      httpHostHeader: 127.0.0.1:$Port
  - service: http_status:404
"@ | Out-File -Encoding ascii (Join-Path $cfDir "config.yml")

& $cf tunnel route dns $TunnelName $Hostname 2>&1 | Out-Null
Write-Host "tunnel '$TunnelName' ($id) -> https://$Hostname -> http://127.0.0.1:$Port"

$ps = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $ps `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'run_tunnel.ps1')`" -TunnelName $TunnelName" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "TWStock Tunnel" -Action $action -Trigger $trigger -Settings $settings `
    -Description "TW Stock Tracker: Cloudflare Tunnel to https://$Hostname" -Force | Out-Null
Write-Host "registered task 'TWStock Tunnel'"
if ($Start) { Start-ScheduledTask -TaskName "TWStock Tunnel"; Write-Host "started" -ForegroundColor Green }
Write-Host "remember: set COOKIE_SECURE=true is not required (Secure is applied automatically over HTTPS)."
