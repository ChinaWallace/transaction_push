$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DefaultsFile = Join-Path $ProjectRoot "config\mysql-local.ini"
$Mysqld = "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe"

if (-not (Test-Path $Mysqld)) {
    throw "mysqld.exe not found at $Mysqld"
}

if (-not (Test-Path $DefaultsFile)) {
    throw "MySQL defaults file not found at $DefaultsFile"
}

$listener = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "MySQL is already listening on 3306 (PID $($listener.OwningProcess))."
    exit 0
}

$dataDir = Join-Path $ProjectRoot "mysql-data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    & $Mysqld --defaults-file="$DefaultsFile" --initialize-insecure
}

Start-Process `
    -FilePath $Mysqld `
    -ArgumentList "--defaults-file=`"$DefaultsFile`"" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    $listener = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Output "MySQL started on 127.0.0.1:3306 (PID $($listener.OwningProcess))."
        exit 0
    }
    Start-Sleep -Seconds 1
}

throw "MySQL did not start listening on 3306 within 30 seconds."
