#!/usr/bin/env python3
"""Application entry point."""
import os
import shutil
import subprocess
from datetime import datetime
from urllib.parse import urlparse

import click
from sqlalchemy import text
from app import (
    create_app, db, _create_database_backup,
    _get_sqlite_db_path, _sqlite_has_required_tables,
)
from app.models import User


def _resolve_config_name():
    config_name = os.getenv('APP_CONFIG')
    if config_name:
        return config_name
    return os.getenv('FLASK_ENV', 'development')


app = create_app(_resolve_config_name())


def _get_database_uri():
    return app.config.get('SQLALCHEMY_DATABASE_URI', '')


def _is_postgres_uri(uri):
    return uri.startswith('postgresql://') or uri.startswith('postgresql+psycopg2://')


def _parse_postgres_uri(uri):
    normalized = uri.replace('postgresql+psycopg2://', 'postgresql://', 1)
    parsed = urlparse(normalized)
    db_name = parsed.path.lstrip('/')
    return {
        'host': parsed.hostname or '127.0.0.1',
        'port': str(parsed.port or 5432),
        'user': parsed.username or '',
        'password': parsed.password or '',
        'database': db_name,
    }


def _run_external_command(command, env=None):
    process = subprocess.run(command, env=env, capture_output=True, text=True)
    if process.returncode != 0:
        stderr = process.stderr.strip()
        stdout = process.stdout.strip()
        message = stderr or stdout or 'Unknown error from external command'
        raise click.ClickException(message)


@app.cli.command('init-db')
@click.option('--admin-password', default='Admin@123', help='Initial admin password')
def init_db(admin_password):
    """Create tables and seed initial admin user."""
    db_path = _get_sqlite_db_path(app)
    if db_path and os.path.exists(db_path):
        backup_path = _create_database_backup(app, label='pre-init')
        if backup_path:
            click.echo(f'Backup created before init: {backup_path}')

    db.create_all()

    # Sync sections from config
    from app import _sync_sections
    with app.app_context():
        _sync_sections(app)

    # Create admin user if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            full_name='ROC Administrator',
            role='admin',
            is_active_user=True
        )
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f'Admin user created (username: admin, password: {admin_password})')
    else:
        click.echo('Admin user already exists.')

    click.echo('Database initialized successfully.')


@app.cli.command('backup-db')
@click.option('--output-dir', default=None, help='Backup directory path')
def backup_db(output_dir):
    """Create a timestamped backup of the configured database."""
    uri = _get_database_uri()

    if _is_postgres_uri(uri):
        details = _parse_postgres_uri(uri)
        if not details['user'] or not details['database']:
            raise click.ClickException('Invalid PostgreSQL DATABASE_URL. Missing user/database information.')

        backup_root = output_dir or os.path.join(app.instance_path, 'backups')
        os.makedirs(backup_root, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_root, f"postgres_{details['database']}_{timestamp}.dump")

        pg_dump_path = shutil.which('pg_dump')
        if not pg_dump_path:
            raise click.ClickException('pg_dump not found. Install PostgreSQL client tools on this machine.')

        env = os.environ.copy()
        if details['password']:
            env['PGPASSWORD'] = details['password']

        command = [
            pg_dump_path,
            '-h', details['host'],
            '-p', details['port'],
            '-U', details['user'],
            '-d', details['database'],
            '-F', 'c',
            '--no-owner',
            '--no-privileges',
            '-f', backup_path,
        ]
        _run_external_command(command, env=env)
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        click.echo(f'PostgreSQL backup created: {backup_path} ({size_mb:.2f} MB)')
        return

    db_path = _get_sqlite_db_path(app)
    if not db_path or not os.path.exists(db_path):
        click.echo('No database file found.')
        return

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(output_dir, f'letter_tracker_manual_{timestamp}.db')
        shutil.copy2(db_path, backup_path)
    else:
        backup_path = _create_database_backup(app, label='manual')

    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    click.echo(f'Backup created: {backup_path} ({size_mb:.2f} MB)')


@app.cli.command('db-status')
def db_status():
    """Show basic database health information."""
    uri = _get_database_uri()
    try:
        db.session.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False

    db_path = _get_sqlite_db_path(app)
    if not db_path:
        if _is_postgres_uri(uri):
            details = _parse_postgres_uri(uri)
            click.echo('Database engine: PostgreSQL')
            click.echo(f"Host: {details['host']}:{details['port']}")
            click.echo(f"Database: {details['database']}")
            click.echo(f'Connectivity check: {"ok" if db_ok else "failed"}')
            return
        click.echo('Non-SQLite database configured.')
        return
    if not os.path.exists(db_path):
        click.echo(f'Database file missing: {db_path}')
        return

    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    healthy = _sqlite_has_required_tables(db_path)
    click.echo(f'Database: {db_path}')
    click.echo(f'Size: {size_mb:.2f} MB')
    click.echo(f'Has required tables: {"yes" if healthy else "no"}')
    click.echo(f'Connectivity check: {"ok" if db_ok else "failed"}')


@app.cli.command('restore-db')
@click.option('--input-file', required=True, type=click.Path(exists=True, dir_okay=False))
@click.option('--yes', is_flag=True, help='Confirm restore operation')
def restore_db(input_file, yes):
    """Restore configured database from a backup file."""
    if not yes:
        raise click.ClickException('Restore is destructive. Re-run with --yes after taking a backup.')

    uri = _get_database_uri()
    if _is_postgres_uri(uri):
        details = _parse_postgres_uri(uri)
        pg_restore_path = shutil.which('pg_restore')
        if not pg_restore_path:
            raise click.ClickException('pg_restore not found. Install PostgreSQL client tools on this machine.')

        env = os.environ.copy()
        if details['password']:
            env['PGPASSWORD'] = details['password']

        command = [
            pg_restore_path,
            '--clean',
            '--if-exists',
            '--no-owner',
            '--no-privileges',
            '-h', details['host'],
            '-p', details['port'],
            '-U', details['user'],
            '-d', details['database'],
            input_file,
        ]
        _run_external_command(command, env=env)
        click.echo(f'PostgreSQL restore completed from: {input_file}')
        return

    db_path = _get_sqlite_db_path(app)
    if not db_path:
        raise click.ClickException('Unsupported database type for restore operation.')

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        backup_path = _create_database_backup(app, label='pre-restore')
        if backup_path:
            click.echo(f'Created safety backup: {backup_path}')

    shutil.copy2(input_file, db_path)
    click.echo(f'SQLite restore completed from: {input_file}')


@app.cli.command('check-deadlines')
def check_deadlines():
    """Manually trigger deadline alert checks."""
    from app.utils.alerts import check_deadline_alerts
    with app.app_context():
        check_deadline_alerts()
    click.echo('Deadline check completed.')


@app.cli.command('create-user')
@click.option('--username', prompt=True)
@click.option('--full-name', prompt='Full name')
@click.option('--role', prompt=True, type=click.Choice(['admin', 'data_entry', 'user']))
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
def create_user(username, full_name, role, password):
    """Create a new user from CLI."""
    if User.query.filter_by(username=username).first():
        click.echo(f'User "{username}" already exists.')
        return
    user = User(username=username, full_name=full_name, role=role, is_active_user=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'User "{username}" created with role "{role}".')


if __name__ == '__main__':
    app.run()
