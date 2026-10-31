# Throwaway public HTTPS URL for testing (no Cloudflare account needed). Prints a *.trycloudflare.com
# address that forwards to the engine; the URL changes on every run and dies with this window.
# The engine requires login, so sharing this URL is as safe as the accounts behind it.
param([int]$Port = 8000)
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    Write-Host "installing cloudflared with winget..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
    $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cf) { $cf = "$env:ProgramFiles\cloudflared\cloudflared.exe" }
}
& $cf tunnel --no-autoupdate --url "http://127.0.0.1:$Port"
