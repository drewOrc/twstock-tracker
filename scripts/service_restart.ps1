# Restart the engine and/or CRM (e.g. after pulling new code). Stops task + server, then starts the task.
#   scripts\service_restart.ps1            # both
#   scripts\service_restart.ps1 -Engine
#   scripts\service_restart.ps1 -Crm
param([switch]$Engine, [switch]$Crm)
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")
if (-not $Engine -and -not $Crm) { $Engine = $true; $Crm = $true }
$names = @()
if ($Engine) { $names += "TWStock Engine" }
if ($Crm) { $names += "TWStock CRM" }
foreach ($n in $names) {
    Stop-TaskAndServer $n
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName $n
    Write-Host "$n restarted"
}
Start-Sleep -Seconds 6
foreach ($n in $names) {
    $port = $script:Services[$n].Port
    $owner = Get-PortOwner $port
    Write-Host ("{0}: {1}" -f $n, $(if ($owner) { "listening on $port (pid $owner)" } else { "NOT listening on $port yet" }))
}
