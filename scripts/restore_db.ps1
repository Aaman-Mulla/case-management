param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "production" })
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$flaskBin = Join-Path $projectDir "venv\Scripts\flask.exe"
$appPath = Join-Path $projectDir "run.py"

if (-not (Test-Path $flaskBin)) {
    Write-Host "[FAIL] Flask binary not found at $flaskBin"
    exit 1
}

if (-not (Test-Path $InputFile)) {
    Write-Host "[FAIL] Backup file not found: $InputFile"
    exit 1
}

$env:APP_CONFIG = $AppConfig

Write-Host "WARNING: Restore is destructive and will overwrite existing data."
$confirm = Read-Host "Type RESTORE to continue"
if ($confirm -ne "RESTORE") {
    Write-Host "Restore cancelled."
    exit 1
}

Write-Host "Restoring database from: $InputFile"
Write-Host "Config: $AppConfig"

& $flaskBin --app $appPath restore-db --input-file $InputFile --yes
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Restore completed successfully."
exit 0
