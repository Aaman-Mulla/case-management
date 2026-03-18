import os
import logging
import shutil
import sqlite3
from datetime import datetime

from flask import Flask, request as flask_request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import OperationalError

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

# Optional Flask-Limiter
limiter = None
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
except ImportError:
    pass


REQUIRED_DB_TABLES = ('user', 'section', 'letter', 'reminder')


def create_app(config_name='default'):
    from config import config as config_map, get_instance_path
    app = Flask(__name__, instance_path=get_instance_path())
    app.config.from_object(config_map.get(config_name, config_map['default']))

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    migrate.init_app(app, db)
    csrf.init_app(app)

    if limiter:
        limiter.init_app(app)

    # Ensure upload dirs exist
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads/attachments'), exist_ok=True)
    os.makedirs(os.path.join(app.instance_path), exist_ok=True)
    os.makedirs(os.path.join(app.instance_path, 'backups'), exist_ok=True)

    # User loader
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (OperationalError, ValueError):
            db.session.rollback()
            return None

    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.data_entry import bp as data_entry_bp
    app.register_blueprint(data_entry_bp, url_prefix='/data-entry')

    from app.cases import bp as cases_bp
    app.register_blueprint(cases_bp, url_prefix='/cases')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    # SEC-2: No longer blanket-exempt the API blueprint from CSRF.
    # AJAX calls send X-CSRFToken header; only exempt specific JSON-only endpoints.

    @app.errorhandler(403)
    def handle_forbidden(error):
        from flask import redirect, url_for, flash, jsonify
        from flask_login import current_user

        if flask_request.path.startswith('/api/'):
            return jsonify({'error': 'Forbidden'}), 403

        if not current_user.is_authenticated:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))

        flash('You do not have permission to view that page. Redirected to your dashboard.', 'warning')
        if getattr(current_user, 'is_admin', False):
            return redirect(url_for('admin.dashboard'))
        if getattr(current_user, 'is_data_entry', False):
            return redirect(url_for('data_entry.dashboard'))
        return redirect(url_for('main.dashboard'))

    # Context processors — PERF-4: skip for API/static requests
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        # Skip expensive notification query for non-HTML requests (API, static)
        if flask_request.path.startswith('/api/') or flask_request.path.startswith('/static/'):
            return dict(unread_notification_count=0, config=app.config)
        from app.models import Notification
        unread_count = 0
        if current_user.is_authenticated:
            try:
                unread_count = Notification.query.filter_by(
                    user_id=current_user.id, is_read=False
                ).count()
            except OperationalError:
                db.session.rollback()
                unread_count = 0
        return dict(
            unread_notification_count=unread_count,
            config=app.config,
        )

    # SEC-6: Content-Security-Policy header
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://code.jquery.com https://cdn.jsdelivr.net https://cdn.datatables.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.datatables.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        response.headers['Content-Security-Policy'] = csp
        return response

    # Create tables and sync sections (optional bootstrap)
    if app.config.get('AUTO_DB_BOOTSTRAP', True):
        with app.app_context():
            _backup_broken_sqlite_db(app)
            db.create_all()
            _sync_sections(app)
            _ensure_default_users(app)
    else:
        app.logger.info('AUTO_DB_BOOTSTRAP is disabled; skipping startup db.create_all/_sync_sections.')

    # Start APScheduler — PERF-6: prevent duplicate schedulers
    _start_scheduler(app)

    # Logging
    logging.basicConfig(level=logging.INFO)

    return app


def _get_sqlite_db_path(app):
    """Return the SQLite file path if the app uses SQLite, else None."""
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:///'):
        return None
    return uri.replace('sqlite:///', '', 1)


def _sqlite_has_required_tables(db_path, required_tables=None):
    """Check whether the SQLite file contains the required application tables."""
    required_tables = required_tables or REQUIRED_DB_TABLES
    if not db_path or not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return False

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for table in required_tables:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if not cur.fetchone():
                conn.close()
                return False
        conn.close()
        return True
    except sqlite3.Error:
        return False


def _create_database_backup(app, label='manual'):
    """Create a timestamped backup of the SQLite database and return its path."""
    db_path = _get_sqlite_db_path(app)
    if not db_path or not os.path.exists(db_path):
        return None

    backup_dir = os.path.join(app.instance_path, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'letter_tracker_{label}_{timestamp}.db')
    shutil.copy2(db_path, backup_path)
    return backup_path


def _backup_broken_sqlite_db(app):
    """Snapshot an existing SQLite DB if it looks incomplete before auto-repairing it."""
    db_path = _get_sqlite_db_path(app)
    if not db_path or not os.path.exists(db_path):
        return None

    if _sqlite_has_required_tables(db_path):
        return None

    backup_path = _create_database_backup(app, label='startup-recovery')
    if backup_path:
        app.logger.warning(
            'Existing SQLite database was missing required tables. '
            'Created safety backup at %s before recovery.',
            backup_path,
        )
    return backup_path


def _sync_sections(app):
    """Sync the approved sections list into the database."""
    from app.models import Section, Case, Letter
    section_migration = app.config.get('SECTION_CODE_MIGRATION', {})
    approved_sections = app.config.get('SECTIONS', [])

    # Migrate old codes
    for old_code, new_code in section_migration.items():
        Case.query.filter_by(section=old_code).update({'section': new_code})
        Letter.query.filter_by(section=old_code).update({'section': new_code})

    # Remove legacy section rows that have been renamed via migration map
    legacy_codes = [old_code for old_code, new_code in section_migration.items() if old_code != new_code]
    if legacy_codes:
        Section.query.filter(Section.code.in_(legacy_codes)).delete(synchronize_session='fetch')

    approved_codes = set()
    for idx, (code, name) in enumerate(approved_sections):
        approved_codes.add(code)
        existing = Section.query.filter_by(code=code).first()
        if existing:
            existing.name = name
            existing.display_order = idx
            existing.is_active = True
        else:
            section = Section(
                code=code, name=name,
                display_order=idx, is_active=True
            )
            db.session.add(section)

    # Deactivate sections not in approved list
    Section.query.filter(~Section.code.in_(approved_codes)).update(
        {'is_active': False}, synchronize_session='fetch'
    )

    db.session.commit()


DEFAULT_USERS = [
    ('admin', 'ROC Administrator', 'admin'),
]


def _ensure_default_users(app):
    """Auto-seed the admin user when the user table is empty.

    This runs on every startup so that even if the database is
    recreated or wiped, the admin account is always available.
    The default password is 'Admin@123'.  All other users (data_entry,
    regular users) must be created by the admin from within the tool.
    This only fires when the table has zero rows.
    """
    from app.models import User

    if app.config.get('TESTING') or User.query.first() is not None:
        return  # users exist, nothing to do

    default_password = app.config.get('DEFAULT_ADMIN_PASSWORD', 'Admin@123')

    for username, full_name, role in DEFAULT_USERS:
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_active_user=True,
        )
        user.set_password(default_password)
        db.session.add(user)

    db.session.commit()
    app.logger.warning(
        'User table was empty — seeded default admin user. '
        'Change the default password immediately in production.',
    )


def _start_scheduler(app):
    """Start APScheduler for background tasks.
    PERF-6: Use a file lock to prevent duplicate schedulers in multi-worker setups.
    """
    # Skip in testing or when SCHEDULER_DISABLED is set
    if app.config.get('TESTING') or os.environ.get('SCHEDULER_DISABLED'):
        return

    lock_file = os.path.join(app.instance_path, '.scheduler.lock')

    try:
        import fcntl
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError, ImportError):
        # Another worker already holds the lock, or fcntl not available
        app.logger.info('Scheduler lock not acquired — skipping duplicate scheduler.')
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()

        def check_alerts():
            with app.app_context():
                from app.utils.alerts import check_deadline_alerts
                check_deadline_alerts()

        def check_reminders():
            with app.app_context():
                from app.utils.reminders import process_due_reminders
                process_due_reminders()

        scheduler.add_job(check_alerts, 'interval', hours=1, id='check_alerts')
        scheduler.add_job(check_reminders, 'interval', minutes=5, id='check_reminders')
        scheduler.start()
        app.logger.info('APScheduler started successfully.')
    except Exception as e:
        app.logger.warning(f'Could not start scheduler: {e}')
