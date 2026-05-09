$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $ProjectRoot "mysql-data\mysql.pid"

if (Test-Path $PidFile) {
    $mysqlPid = (Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1).Trim()
    if ($mysqlPid -and (Get-Process -Id $mysqlPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $mysqlPid -Force
        Write-Output "Stopped MySQL process PID $mysqlPid."
        exit 0
    }
}

$listeners = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Output "MySQL is not listening on 3306."
    exit 0
}

foreach ($listener in $listeners) {
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq "mysqld") {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped MySQL process PID $($process.Id)."
    }
}
