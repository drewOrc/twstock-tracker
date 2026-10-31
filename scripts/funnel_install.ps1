<#
.SYNOPSIS
  Fixed public HTTPS address without buying a domain: Tailscale Funnel. Installs Tailscale, has you
  log in once (browser), turns Funnel on in the background (survives reboots; the Tailscale service
  keeps it) pointing at the engine, and records the address as PUBLIC_URL in .env.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\funnel_install.ps1

.NOTES
  The address is https://<machine>.<tailnet>.ts.net; it follows this machine's name. Funnel must be
  allowed for your tailnet (the first `tailscale funnel` prints a link to enable it if it is not).
  Turn off with: tailscale funnel --https=443 off
#>
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = "$env:ProgramFiles\Tailscale\tailscale.exe" }
if (-not (Test-Path $ts)) {
    Write-Host "installing Tailscale..." -ForegroundColor Yellow
    winget install --id Tailscale.Tailscale -e --accept-package-agreements --accept-source-agreements
    $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
}
$state = (& $ts status --json | ConvertFrom-Json)
if ($state.BackendState -ne "Running") {
    Write-Host "log in to Tailscale in the browser window that opens..." -ForegroundColor Yellow
    & $ts login
    $state = (& $ts status --json | ConvertFrom-Json)
}
& $ts funnel --bg $Port
$dns = $state.Self.DNSName.TrimEnd(".")
$url = "https://$dns"
$envFile = Join-Path $root ".env"
$lines = if (Test-Path $envFile) { Get-Content $envFile } else { @() }
if ($lines -match '^PUBLIC_URL=') { $lines = $lines -replace '^PUBLIC_URL=.*', "PUBLIC_URL=$url" } else { $lines += "PUBLIC_URL=$url" }
$lines | Set-Content -Encoding utf8 $envFile
Write-Host "Funnel on: $url -> http://127.0.0.1:$Port (PUBLIC_URL written to .env; restart the engine: scripts\service_restart.ps1 -Engine)" -ForegroundColor Green
