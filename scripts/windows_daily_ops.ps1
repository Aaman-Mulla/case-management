param(
    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "production" }),
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { "$PSScriptRoot\..\var\backups" })
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$preflightScript = Join-Path $PSScriptRoot "preflight_check.ps1"
$backupScript = Join-Path $PSScriptRoot "backup_db.ps1"
$restoreScript = Join-Path $PSScriptRoot "restore_db.ps1"
$goLiveScript = Join-Path $PSScriptRoot "go_live_checklist.ps1"

foreach ($requiredScript in @($preflightScript, $backupScript, $restoreScript, $goLiveScript)) {
    if (-not (Test-Path $requiredScript)) {
        Write-Host "[FAIL] Required script missing: $requiredScript"
        exit 1
    }
}

function Show-Menu {
    Write-Host ""
    Write-Host "==========================================="
    Write-Host " ROC Case Management - Daily Ops Menu"
    Write-Host "==========================================="
    Write-Host "Project: $projectDir"
    Write-Host "AppConfig: $AppConfig"
    Write-Host "BackupDir: $BackupDir"
    Write-Host ""
    Write-Host "1) Run Preflight Check"
    Write-Host "2) Create Database Backup"
    Write-Host "3) Run Go-Live Checklist"
    Write-Host "4) Restore Database"
    Write-Host "5) Exit"
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Select an option (1-5)"

    switch ($choice) {
        "1" {
            Write-Host ""
            Write-Host "Running Preflight Check..."
            & $preflightScript -AppConfig $AppConfig -BackupDir $BackupDir
            Write-Host ""
            Read-Host "Press Enter to continue"
        }
        "2" {
            Write-Host ""
            Write-Host "Creating Database Backup..."
            & $backupScript -AppConfig $AppConfig -OutputDir $BackupDir
            Write-Host ""
            Read-Host "Press Enter to continue"
        }
        "3" {
            Write-Host ""
            Write-Host "Running Go-Live Checklist..."
            & $goLiveScript -AppConfig $AppConfig -BackupDir $BackupDir
            Write-Host ""
            Read-Host "Press Enter to continue"
        }
        "4" {
            Write-Host ""
            $inputFile = Read-Host "Enter full path of backup file to restore"
            if ([string]::IsNullOrWhiteSpace($inputFile)) {
                Write-Host "No file provided. Restore cancelled."
            } else {
                & $restoreScript -AppConfig $AppConfig -InputFile $inputFile
            }
            Write-Host ""
            Read-Host "Press Enter to continue"
        }
        "5" {
            Write-Host "Exiting Daily Ops Menu."
            break
        }
        default {
            Write-Host "Invalid choice. Please select 1, 2, 3, 4, or 5."
            Read-Host "Press Enter to continue"
        }
    }
}

exit 0
