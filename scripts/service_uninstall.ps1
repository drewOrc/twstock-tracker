# Stop and remove the scheduled tasks created by service_install.ps1 (engine and, if present, CRM),
# including the server processes the supervisors spawned.
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")
foreach ($name in @("TWStock Engine", "TWStock CRM")) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        Stop-TaskAndServer $name
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "removed task '$name'"
    } else {
        Write-Host "task '$name' not found"
    }
}
