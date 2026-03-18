param(
    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "production" }),
    [string]$OutputDir = $(if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { "$PSScriptRoot\..\var\backups" })
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$flaskBin = Join-Path $projectDir "venv\Scripts\flask.exe"
$appPath = Join-Path $projectDir "run.py"

if (-not (Test-Path $flaskBin)) {
    Write-Host "[FAIL] Flask binary not found at $flaskBin"
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$env:APP_CONFIG = $AppConfig

Write-Host "Creating database backup..."
Write-Host "Config: $AppConfig"
Write-Host "Output: $OutputDir"

& $flaskBin --app $appPath backup-db --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Backup command completed successfully."
exit 0
