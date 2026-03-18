param(
    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "production" }),
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { "$PSScriptRoot\..\var\backups" })
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$flaskBin = Join-Path $projectDir "venv\Scripts\flask.exe"
$appPath = Join-Path $projectDir "run.py"
$dbStatusLog = Join-Path $env:TEMP "case_mgmt_preflight_dbstatus.log"

$requiredVars = @(
    "APP_CONFIG",
    "SECRET_KEY",
    "DATABASE_URL",
    "HOST",
    "PORT",
    "SERVER_MODE"
)

$errors = 0
$warnings = 0

Write-Host "== ROC Case Management Preflight =="
Write-Host "Project: $projectDir"
Write-Host "Config: $AppConfig"

if (-not (Test-Path $flaskBin)) {
    Write-Host "[FAIL] Flask binary missing at $flaskBin"
    Write-Host "       Create venv and install deps first."
    exit 1
}

$env:APP_CONFIG = $AppConfig

foreach ($varName in $requiredVars) {
    $value = [Environment]::GetEnvironmentVariable($varName)
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "[FAIL] Required env var missing: $varName"
        $errors++
    } else {
        Write-Host "[ OK ] $varName is set"
    }
}

if ($AppConfig -ne "production") {
    Write-Host "[WARN] APP_CONFIG is not 'production'"
    $warnings++
}

$databaseUrl = [Environment]::GetEnvironmentVariable("DATABASE_URL")
if ($databaseUrl -like "sqlite://*") {
    Write-Host "[WARN] DATABASE_URL uses SQLite. PostgreSQL is recommended for production."
    $warnings++
}

$rateLimitStorage = [Environment]::GetEnvironmentVariable("RATELIMIT_STORAGE_URI")
if ([string]::IsNullOrWhiteSpace($rateLimitStorage)) {
    $rateLimitStorage = "memory://"
}
if ($rateLimitStorage -eq "memory://") {
    Write-Host "[WARN] RATELIMIT_STORAGE_URI is memory:// (fine for single instance; use Redis for scaled deployment)."
    $warnings++
}

try {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
} catch {
    Write-Host "[FAIL] Cannot create backup directory: $BackupDir"
    $errors++
}

if (Test-Path $BackupDir) {
    $probeFile = Join-Path $BackupDir ".preflight-write-test"
    try {
        New-Item -ItemType File -Force -Path $probeFile | Out-Null
        Remove-Item -Force -Path $probeFile -ErrorAction SilentlyContinue
        Write-Host "[ OK ] Backup directory writable: $BackupDir"
    } catch {
        Write-Host "[FAIL] Backup directory not writable: $BackupDir"
        $errors++
    }
}

Write-Host "[....] Checking DB connectivity via flask db-status"
try {
    & $flaskBin --app $appPath db-status *> $dbStatusLog
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[ OK ] Database connectivity check passed"
    } else {
        Write-Host "[FAIL] Database connectivity check failed"
        if (Test-Path $dbStatusLog) {
            Get-Content $dbStatusLog
        }
        $errors++
    }
} catch {
    Write-Host "[FAIL] Database connectivity check failed"
    if (Test-Path $dbStatusLog) {
        Get-Content $dbStatusLog
    }
    $errors++
}

if ($errors -gt 0) {
    Write-Host "`nPreflight result: FAILED ($errors errors, $warnings warnings)"
    exit 1
}

Write-Host "`nPreflight result: PASSED ($warnings warnings)"
exit 0
