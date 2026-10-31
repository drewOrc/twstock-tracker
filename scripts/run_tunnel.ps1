# Supervisor loop for the Cloudflare Tunnel (public HTTPS -> http://127.0.0.1:8000).
# Started by the "TWStock Tunnel" scheduled task (tunnel_install.ps1). Needs a named tunnel
# configured by tunnel_install.ps1; for a throwaway test URL use tunnel_quick.ps1 instead.
param([string]$TunnelName = "twstock")
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supLog = Join-Path $logDir "tunnel-supervisor.log"
$errLog = Join-Path $logDir "tunnel.log"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = "$env:ProgramFiles\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { "$(Get-Date -Format s) cloudflared not found" | Out-File -Append -Encoding utf8 $supLog; exit 1 }

while ($true) {
    "$(Get-Date -Format s) starting tunnel $TunnelName" | Out-File -Append -Encoding utf8 $supLog
    & cmd /c "`"$cf`" tunnel --no-autoupdate run $TunnelName 2>>`"$errLog`""
    "$(Get-Date -Format s) tunnel exited with code $LASTEXITCODE; restarting in 10s" | Out-File -Append -Encoding utf8 $supLog
    Start-Sleep -Seconds 10
}
