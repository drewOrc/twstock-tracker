# Shared helpers for the supervisor and service scripts (dot-source this file).

function Get-PortOwner([int]$Port) {
    # PID of the process listening on the port, or $null
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess } else { return $null }
}

function Get-ServerByPattern([string]$Pattern) {
    # PIDs of python processes whose command line matches (fallback when the port query lags)
    if (-not $Pattern) { return @() }
    return @(Get-CimInstance Win32_Process -Filter "name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like $Pattern -and $_.ProcessId -ne $PID } |
        ForEach-Object { [int]$_.ProcessId })
}

function Stop-PortOwner([int]$Port, [string]$Pattern = "") {
    # Kill whatever serves this port: the listener, plus any python matching $Pattern (an orphaned
    # server from a previous supervisor). Waits until the port is free. Returns the pids killed.
    $pids = @()
    $owner = Get-PortOwner $Port
    if ($owner -and $owner -ne $PID) { $pids += $owner }
    $pids += Get-ServerByPattern $Pattern
    $pids = $pids | Sort-Object -Unique
    foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
    if ($pids.Count) {
        $deadline = (Get-Date).AddSeconds(10)
        while ((Get-PortOwner $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    }
    return $pids
}

$script:Services = @{
    "TWStock Engine" = @{ Port = 8000; Pattern = "*uvicorn app.main*" }
    "TWStock CRM"    = @{ Port = 8765; Pattern = "*stockcrm.api*" }
}

function Stop-TaskAndServer([string]$Name) {
    # Stop the scheduled task (kills the supervisor) and then the server it left behind.
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    }
    $svc = $script:Services[$Name]
    if ($svc) {
        $killed = Stop-PortOwner $svc.Port $svc.Pattern
        if ($killed) { Write-Host "stopped server on port $($svc.Port) (pid $($killed -join ','))" }
    }
}
