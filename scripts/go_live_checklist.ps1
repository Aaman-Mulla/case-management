param(
    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "production" }),
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { "$PSScriptRoot\..\var\backups" }),
    [string]$MigrationSqlOut = $(if ($env:MIGRATION_SQL_OUT) { $env:MIGRATION_SQL_OUT } else { "$PSScriptRoot\..\var\log\migration-preview.sql" })
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$flaskBin = Join-Path $projectDir "venv\Scripts\flask.exe"
$appPath = Join-Path $projectDir "run.py"
$preflightScript = Join-Path $projectDir "scripts\preflight_check.ps1"

if (-not (Test-Path $flaskBin)) {
    Write-Host "[FAIL] Flask binary not found at $flaskBin"
    exit 1
}

if (-not (Test-Path $preflightScript)) {
    Write-Host "[FAIL] Preflight script not found at $preflightScript"
    exit 1
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $MigrationSqlOut -Parent) | Out-Null

Write-Host "== Go-Live Checklist (PowerShell Wrapper) =="
Write-Host "Project: $projectDir"
Write-Host "Config: $AppConfig"

Write-Host "`n[1/3] Running preflight checks"
$env:APP_CONFIG = $AppConfig
$env:BACKUP_DIR = $BackupDir
& $preflightScript -AppConfig $AppConfig -BackupDir $BackupDir
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "`n[2/3] Creating backup"
& $flaskBin --app $appPath backup-db --output-dir $BackupDir
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "`n[3/3] Checking migrations (dry-run SQL generation)"
$null = & $flaskBin --app $appPath db upgrade --sql 2>&1 | Tee-Object -FilePath $MigrationSqlOut
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ((Get-Item $MigrationSqlOut).Length -eq 0) {
    Write-Host "[WARN] Migration SQL preview file is empty: $MigrationSqlOut"
} else {
    Write-Host "[ OK ] Migration preview written: $MigrationSqlOut"
}

Write-Host "`nGo-live checklist PASSED"
Write-Host "- Backup dir: $BackupDir"
Write-Host "- Migration preview: $MigrationSqlOut"
exit 0
