# ROC Case Management / Letter Tracking

A Flask-based web application for the Regional Office of Companies (ROC), Pune to manage inward/outward correspondence and cases.

## Features

- **Letter Management** — Track inward and outward letters with reference numbers, priorities, SLA deadlines, and assignments
- **Case Management** — Group related letters into cases with status workflows
- **Role-Based Access** — Admin (ROC), Data Entry, and User roles with appropriate permissions
- **Excel Import** — Bulk import letters from Excel/CSV files with duplicate detection
- **Analytics Dashboard** — Charts for status distribution, priority breakdown, monthly trends, section workload
- **Notifications** — Automatic deadline alerts and custom reminders
- **Dark Mode** — Full dark theme support with persistent user preference
- **Audit Trail** — Complete activity logging with Excel/PDF export

## Tech Stack

- **Backend:** Python 3.12+, Flask 3.0, SQLAlchemy, Flask-Migrate
- **Frontend:** Bootstrap 5.3, DataTables, Chart.js, Select2, jQuery
- **Database:** SQLite (default), upgradeable to PostgreSQL
- **Scheduling:** APScheduler for deadline alerts and reminders

## Quick Start

### 1. Clone & Install

```bash
git clone <repo-url>
cd case-management
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your SECRET_KEY
```

For production baseline values:

```bash
cp .env.production.example .env
```

### 3. Initialize Database

```bash
export FLASK_APP=run.py
flask db upgrade
flask init-db
```

This creates the database, applies migrations, seeds 23 sections, and creates the admin user with:
- **Username:** `admin`
- **Password:** `Admin@123`

### 4. Run

```bash
flask run
```

Visit http://127.0.0.1:5000

### Stable Local Run (Recommended)

Use the helper scripts to avoid path/port/reloader issues:

```bash
./scripts/start_server.sh
```

Default URL: http://127.0.0.1:5001

Optional custom port:

```bash
PORT=5002 ./scripts/start_server.sh
```

Production-like local mode (Waitress):

```bash
APP_CONFIG=production SERVER_MODE=waitress HOST=0.0.0.0 PORT=5001 ./scripts/start_server.sh
```

Stop server:

```bash
./scripts/stop_server.sh
```

Restart server:

```bash
./scripts/restart_server.sh
```

Logs and PID files:
- Log file: `var/log/server.log`
- PID file: `var/run/server.pid`

## Deployment Readiness Notes

- **Config by environment**: set `APP_CONFIG=production` in deployed environments.
- **Data/code separation**: use `DATA_DIR` and `INSTANCE_PATH` to keep DB, backups, and uploads outside code-update paths.
- **Database safety**: do **not** run `flask init-db` on every restart. Use it only for first-time setup.
- **Startup bootstrap control**: set `AUTO_DB_BOOTSTRAP=false` in production to skip startup `db.create_all`/section sync overhead.
- **Backup operations**: run `flask backup-db` before schema/data maintenance tasks.
- **Production server mode**: use `SERVER_MODE=waitress` (Windows-friendly WSGI serving).
- **Windows on-prem guide**: see `docs/DEPLOYMENT_WINDOWS.md` for end-to-end setup and operations.

## Docker

```bash
docker-compose up --build
```

Visit http://localhost:5000

## CLI Commands

| Command | Description |
|---------|-------------|
| `flask init-db` | Create tables and seed admin user |
| `flask db-status` | Check configured DB connectivity/health details |
| `flask backup-db` | Create DB backup (SQLite copy or PostgreSQL dump) |
| `flask restore-db --input-file <file> --yes` | Restore DB from backup file |
| `flask check-deadlines` | Manually trigger deadline alerts |
| `flask create-user` | Create a new user interactively |
| `flask db migrate -m "msg"` | Generate new migration |
| `flask db upgrade` | Apply pending migrations |

Ops helper scripts:

- `./scripts/backup_db.sh [output-dir]`
- `./scripts/restore_db.sh <backup-file>`
- `./scripts/preflight_check.sh` (checks required env vars, DB connectivity, backup path)
- `./scripts/go_live_checklist.sh` (runs preflight + backup + migration dry-run)
- `powershell -ExecutionPolicy Bypass -File .\\scripts\\preflight_check.ps1`
- `powershell -ExecutionPolicy Bypass -File .\\scripts\\go_live_checklist.ps1` (Windows wrapper)
- `powershell -ExecutionPolicy Bypass -File .\\scripts\\backup_db.ps1`
- `powershell -ExecutionPolicy Bypass -File .\\scripts\\restore_db.ps1 -InputFile <backup-file>`
- `powershell -ExecutionPolicy Bypass -File .\\scripts\\windows_daily_ops.ps1` (interactive operator menu)

## Project Structure

```
case-management/
├── app/
│   ├── __init__.py          # App factory
│   ├── models.py            # All SQLAlchemy models
│   ├── auth/                # Authentication (login, logout, password)
│   ├── admin/               # ROC admin views
│   ├── data_entry/          # Data entry operator views
│   ├── main/                # Regular user views
│   ├── cases/               # Case management
│   ├── api/                 # REST API endpoints
│   ├── utils/               # Shared utilities
│   │   ├── queries.py       # Reusable query builders
│   │   ├── excel_parser.py  # Import parser
│   │   ├── alerts.py        # Deadline alert checker
│   │   └── reminders.py     # Reminder processor
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/main.js
│   └── templates/           # Jinja2 templates
├── migrations/              # Alembic migrations
├── config.py                # Configuration
├── run.py                   # Entry point & CLI
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Roles

| Role | Display Name | Access |
|------|-------------|--------|
| `admin` | ROC | Full access — manage letters, cases, users, sections, analytics |
| `data_entry` | Data Entry | Letter CRUD, import, assignment (no user/section management) |
| `user` | User | View assigned letters, update status, add comments |

## 23 Approved Sections

3ls, Prosecution, Merger (230-232), Merger (233), Compounding, CTC, Shifting, RD reference, Admin, Insolvency, Liquidation, Section 252, NCLT, NCLAT, High Court, Supreme Court, Instructions, Adjudication, Conversions, Auditor related, Bills, RTI, Miscellaneous

## SLA Configuration

| Priority | Days |
|----------|------|
| Critical | 3 |
| High | 6 |
| Medium | 9 |
| Low | 15 |

## License

Internal use — Regional Office of Companies, Pune.
