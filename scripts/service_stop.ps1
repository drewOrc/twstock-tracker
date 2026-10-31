# Stop the engine and/or CRM cleanly: the scheduled task AND the server process it spawned.
#   scripts\service_stop.ps1            # both
#   scripts\service_stop.ps1 -Engine    # engine only
#   scripts\service_stop.ps1 -Crm       # CRM only
param([switch]$Engine, [switch]$Crm)
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $Engine -and -not $Crm) { $Engine = $true; $Crm = $true }
if ($Engine) { Stop-TaskAndServer "TWStock Engine"; Write-Host "TWStock Engine stopped" }
if ($Crm) { Stop-TaskAndServer "TWStock CRM"; Write-Host "TWStock CRM stopped" }
