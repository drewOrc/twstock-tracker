# Supervisor loop for a *temporary* Cloudflare quick tunnel (no account, no domain).
# Keeps a *.trycloudflare.com URL pointed at the engine; the URL changes whenever cloudflared
# restarts, so every URL is written to data\tunnel-url.txt, which the engine shows in /api/health
# and announces through the configured notification channels (job "tunnel_watch").
# Started by the "TWStock Tunnel" scheduled task (tunnel_quick_install.ps1). Replace with
# tunnel_install.ps1 -Hostname ... once you have a domain on Cloudflare.
param([int]$Port = 8000)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supLog = Join-Path $logDir "tunnel-supervisor.log"
$errLog = Join-Path $logDir "tunnel.log"
$urlFile = Join-Path $root "data\tunnel-url.txt"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = "$env:ProgramFiles\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { $cf = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cf)) { "$(Get-Date -Format s) cloudflared not found" | Out-File -Append -Encoding utf8 $supLog; exit 1 }

while ($true) {
    "$(Get-Date -Format s) starting quick tunnel -> http://127.0.0.1:$Port" | Out-File -Append -Encoding utf8 $supLog
    if (Test-Path $urlFile) { Remove-Item $urlFile -Force }
    & $cf tunnel --no-autoupdate --url "http://127.0.0.1:$Port" 2>&1 | ForEach-Object {
        $line = "$_"
        Add-Content -Path $errLog -Value $line -Encoding utf8
        if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            "$($Matches[0])`n$(Get-Date -Format s)" | Set-Content -Path $urlFile -Encoding ascii
            "$(Get-Date -Format s) public url $($Matches[0])" | Out-File -Append -Encoding utf8 $supLog
        }
    }
    "$(Get-Date -Format s) quick tunnel exited; restarting in 15s" | Out-File -Append -Encoding utf8 $supLog
    if (Test-Path $urlFile) { Remove-Item $urlFile -Force }
    Start-Sleep -Seconds 15
}
