# Windows On-Prem Deployment Runbook

## Target Topology

- 1 central Windows Server hosting app + database
- 12–15 LAN client machines (Windows 7 browsers)
- Access pattern: users open a LAN URL from browser

## 1) Server Prerequisites

- Python 3.12+
- Git (optional)
- PostgreSQL 14+
- PostgreSQL client tools (`pg_dump`, `pg_restore`)
- Optional reverse proxy: IIS + URL Rewrite + ARR

## 2) App Setup

```powershell
cd C:\apps
git clone <repo-url> case-management
cd case-management
py -3 -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Set minimum values in `.env`:

- `APP_CONFIG=production`
- `HOST=127.0.0.1`
- `PORT=5001`
- `SERVER_MODE=waitress`
- `DATABASE_URL=postgresql+psycopg2://cm_user:strong_password@127.0.0.1:5432/case_management`
- `RATELIMIT_STORAGE_URI=memory://` (replace with Redis in scaled/multi-instance setups)
- `AUTO_DB_BOOTSTRAP=false`

## 3) Database First-Time Setup

```powershell
$env:APP_CONFIG="production"
.\venv\Scripts\flask --app run.py db upgrade
.\venv\Scripts\flask --app run.py init-db
```

Important:

- Run `init-db` only once for initial setup.
- For normal upgrades, run only `flask db upgrade`.

## 4) Start Application

Recommended (native PowerShell):

```powershell
$env:APP_CONFIG="production"
$env:HOST="127.0.0.1"
$env:PORT="5001"
.\venv\Scripts\python.exe serve.py
```


## 5) Run as Windows Service (Recommended)

Use NSSM to keep the app running after reboot:

- Path: `C:\apps\case-management\venv\Scripts\python.exe`
- Startup dir: `C:\apps\case-management`
- Arguments: `C:\apps\case-management\serve.py`
- Environment: `APP_CONFIG=production`, `HOST=127.0.0.1`, `PORT=5001`

Set service recovery to restart on failure.

## 6) LAN Exposure

Option A (simple): open firewall for app port and expose directly.

Option B (preferred): IIS reverse proxy

- IIS listens on port 80/443
- Proxy to `http://127.0.0.1:5001`
- Add TLS cert if HTTPS is required internally

## 7) Backup and Restore SOP

Daily backup task (native PowerShell):

```powershell
$env:APP_CONFIG="production"
powershell -ExecutionPolicy Bypass -File .\scripts\backup_db.ps1 -OutputDir C:\backups\case-management
```

Restore (controlled maintenance window):

```powershell
$env:APP_CONFIG="production"
powershell -ExecutionPolicy Bypass -File .\scripts\restore_db.ps1 -InputFile C:\backups\case-management\postgres_case_management_YYYYMMDD_HHMMSS.dump
```

## 8) Release Procedure (No Data Loss)

1. Take DB backup
2. Stop app service
3. Deploy new code
4. Install dependencies if changed
5. Run `flask db upgrade`
6. Start app service
7. Smoke test `/auth/login`

## 9) Health Checks

- Endpoint: `/auth/login` should return HTTP 200
- Logs: `var/log/server.log`
- PID file: `var/run/server.pid`

PowerShell preflight check:

```powershell
$env:APP_CONFIG="production"
powershell -ExecutionPolicy Bypass -File .\scripts\preflight_check.ps1
```

Single-command go-live verification (native PowerShell):

```powershell
$env:APP_CONFIG="production"
powershell -ExecutionPolicy Bypass -File .\scripts\go_live_checklist.ps1
```

## 10) Known Future Scale Hurdles

- SQLite should not be used once concurrent users increase.
- In-memory rate limit storage does not coordinate across multiple instances.
- If multiple app instances are introduced, use shared rate-limit backend and central logging.
