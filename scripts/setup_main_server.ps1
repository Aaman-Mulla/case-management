param(
    [string]$ProjectDir  = "E:\Application\case-management-main",
    [string]$BindIp      = "10.144.32.103",
    [int]$Port           = 5000,
    [string]$BackupDir   = "E:\Application\Backup",
    [string]$BackupTime  = "02:00"
)

$ErrorActionPreference = "Stop"

# ---- Elevation guard ----
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    throw "This script must run from an elevated PowerShell (Run as Administrator)."
}

# ---- Validate paths ----
$envFile       = Join-Path $ProjectDir ".env"
$pythonExe     = Join-Path $ProjectDir "venv\Scripts\python.exe"
$serveScript   = Join-Path $ProjectDir "serve.py"
$dailyBackup   = Join-Path $ProjectDir "scripts\daily_backup.ps1"

foreach ($p in @($envFile, $pythonExe, $serveScript, $dailyBackup)) {
    if (-not (Test-Path $p)) { throw "Required file not found: $p" }
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

# ---- 1. .env binding values ----
Write-Host "`n=== Updating .env ==="
$envText = Get-Content -Path $envFile -Raw
$envText = [Regex]::Replace($envText, '(?m)^HOST=.*$',        "HOST=0.0.0.0")
$envText = [Regex]::Replace($envText, '(?m)^PORT=.*$',        "PORT=$Port")
$envText = [Regex]::Replace($envText, '(?m)^SERVER_MODE=.*$', "SERVER_MODE=waitress")
Set-Content -Path $envFile -Value $envText -Encoding ascii
Write-Host "[OK] HOST=0.0.0.0  PORT=$Port  SERVER_MODE=waitress"

# ---- 2. Windows Firewall ----
Write-Host "`n=== Configuring Firewall ==="
$firewallRule = "ROC Case Management $Port"
if (Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -DisplayName $firewallRule -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
    Write-Host "[OK] Updated existing rule: $firewallRule - TCP $Port inbound"
} else {
    New-NetFirewallRule -DisplayName $firewallRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
    Write-Host "[OK] Created rule: $firewallRule - TCP $Port inbound"
}

# ---- 3. Scheduled Task ??? App auto-start at boot ----
Write-Host "`n=== Registering auto-start task ==="
$taskApp = "ROC-CaseManagement-AutoStart"

# Remove previous version if it exists
Unregister-ScheduledTask -TaskName $taskApp -Confirm:$false -ErrorAction SilentlyContinue

$actionApp = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "`"$serveScript`"" `
    -WorkingDirectory $ProjectDir

$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$settingsApp = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)   # run indefinitely

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName  $taskApp `
    -Action    $actionApp `
    -Trigger   $triggerBoot `
    -Settings  $settingsApp `
    -Principal $principal `
    -Description "Starts ROC Case Management on boot via http://${BindIp}:${Port}" | Out-Null

Write-Host "[OK] Task '$taskApp' registered - runs at every boot as SYSTEM"

# ---- 4. Scheduled Task ??? Daily backup at $BackupTime ----
Write-Host "`n=== Registering daily backup task ==="
$taskBackup = "ROC-CaseManagement-DailyBackup"

Unregister-ScheduledTask -TaskName $taskBackup -Confirm:$false -ErrorAction SilentlyContinue

$actionBackup = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NonInteractive -File `"$dailyBackup`" -OutputDir `"$BackupDir`"" `
    -WorkingDirectory $ProjectDir

$triggerDaily = New-ScheduledTaskTrigger -Daily -At $BackupTime
$settingsBackup = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable   # if machine was off at 2 AM, run as soon as it wakes

Register-ScheduledTask `
    -TaskName  $taskBackup `
    -Action    $actionBackup `
    -Trigger   $triggerDaily `
    -Settings  $settingsBackup `
    -Principal $principal `
    -Description "Daily dedup backup of ROC Case Management DB to $BackupDir" | Out-Null

Write-Host "[OK] Task '$taskBackup' registered - daily at $BackupTime"

# ---- 5. Start the app now if not already listening ----
Write-Host "`n=== Starting app ==="
$listening = netstat -ano | Select-String ":$Port" | Select-String "LISTENING"
if ($listening) {
    Write-Host "[OK] Port $Port already has a listener - app appears running."
} else {
    Start-ScheduledTask -TaskName $taskApp
    Start-Sleep -Seconds 4
    $listening = netstat -ano | Select-String ":$Port" | Select-String "LISTENING"
    if ($listening) {
        Write-Host "[OK] App started via scheduled task."
    } else {
        Write-Host "[WARN] App may still be starting. Check in a few seconds."
    }
}

# ---- 6. Summary ----
Write-Host "`n==========================================="
Write-Host " Setup Complete"
Write-Host "==========================================="
Write-Host "App URL      : http://${BindIp}:${Port}"
Write-Host "Firewall     : $firewallRule - TCP $Port inbound allowed"
Write-Host "Auto-start   : $taskApp - runs at every boot"
Write-Host "Daily backup : $taskBackup - daily at $BackupTime"
Write-Host "Backup folder: $BackupDir"
Write-Host "DB resilience: SQLite WAL mode + integrity check + auto-restore on startup"
Write-Host "===========================================`n"

# Quick HTTP check
try {
    $r = Invoke-WebRequest -Uri "http://${BindIp}:${Port}/auth/login" -UseBasicParsing -TimeoutSec 8
    Write-Host "[OK] HTTP check: $($r.StatusCode) on http://${BindIp}:${Port}/auth/login"
} catch {
    Write-Host "[INFO] HTTP check could not reach the app yet - it may still be starting."
}
