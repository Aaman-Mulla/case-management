param(
    [string]$AppConfig = $(if ($env:APP_CONFIG) { $env:APP_CONFIG } else { "development" }),
    [string]$OutputDir = "E:\Application\Backup"
)

$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path "$PSScriptRoot\..").Path
$flaskBin   = Join-Path $projectDir "venv\Scripts\flask.exe"
$appPath    = Join-Path $projectDir "run.py"

if (-not (Test-Path $flaskBin)) {
    Write-Host "[FAIL] Flask binary not found at $flaskBin"
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# --- Dedup check: skip if today's backup already exists ---
$todayStamp = (Get-Date).ToString("yyyyMMdd")
$existingToday = Get-ChildItem -Path $OutputDir -Filter "*$todayStamp*.db" -ErrorAction SilentlyContinue
if ($existingToday) {
    Write-Host "[SKIP] Backup for today ($todayStamp) already exists: $($existingToday[0].Name)"
    exit 0
}

$env:APP_CONFIG = $AppConfig

Write-Host "Creating daily database backup..."
Write-Host "Config : $AppConfig"
Write-Host "Output : $OutputDir"

& $flaskBin --app $appPath backup-db --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Backup command returned exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "[OK] Daily backup completed successfully."
exit 0
