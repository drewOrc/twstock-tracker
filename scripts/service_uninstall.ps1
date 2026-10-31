# Stop and remove the scheduled tasks created by service_install.ps1 (engine and, if present, CRM).
$ErrorActionPreference = "Continue"
foreach ($name in @("TWStock Engine", "TWStock CRM")) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "removed task '$name'"
    } else {
        Write-Host "task '$name' not found"
    }
}
# The supervisors spawn python; stopping the task kills the PowerShell loop, so also stop any
# uvicorn / stockcrm.api started by it that may still be running.
Get-CimInstance Win32_Process -Filter "name like 'python%'" |
    Where-Object { $_.CommandLine -like '*uvicorn app.main*' -or $_.CommandLine -like '*stockcrm.api*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "stopped python pid $($_.ProcessId)" }
