import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


def _resolve_path(path_value, default_path):
    if not path_value:
        return os.path.abspath(default_path)
    if os.path.isabs(path_value):
        return path_value
    return os.path.abspath(os.path.join(basedir, path_value))


def get_instance_path():
    return _resolve_path(os.environ.get('INSTANCE_PATH'), os.path.join(basedir, 'instance'))


def get_data_path():
    return _resolve_path(os.environ.get('DATA_DIR'), get_instance_path())


def _env_bool(name, default=False):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _normalize_database_uri(raw_uri):
    if not raw_uri:
        return ''
    if raw_uri.startswith('sqlite:///'):
        sqlite_path = raw_uri.replace('sqlite:///', '', 1)
        if not os.path.isabs(sqlite_path):
            sqlite_path = _resolve_path(sqlite_path, sqlite_path)
        return f'sqlite:///{sqlite_path}'
    return raw_uri


# Approved 23 sections: (code, display_name)
SECTIONS = [
    ('3IS', '3ls'),
    ('PROS', 'Prosecution'),
    ('MER230', 'Merger (230-232)'),
    ('MER233', 'Merger (233)'),
    ('COMPD', 'Compounding'),
    ('CTC', 'CTC'),
    ('SHIFT', 'Shifting'),
    ('RDREF', 'RD reference'),
    ('ADM', 'Admin'),
    ('INSOL', 'Insolvency'),
    ('LIQDN', 'Liquidation'),
    ('252', 'Section 252'),
    ('NCLT', 'NCLT'),
    ('NCLAT', 'NCLAT'),
    ('HC', 'High Court'),
    ('SC', 'Supreme Court'),
    ('INSTR', 'Instructions'),
    ('ADJ', 'Adjudication'),
    ('CONV', 'Conversions'),
    ('AUDTR', 'Auditor related'),
    ('BILLS', 'Bills'),
    ('RTI', 'RTI'),
    ('MISC', 'Miscellaneous'),
]

SECTION_CODE_MIGRATION = {
    '3Is': '3IS',
    'M230': 'MER230',
    'M233': 'MER233',
    'COMP': 'COMPD',
    'SHFT': 'SHIFT',
    'RDRF': 'RDREF',
    'INLQ': 'INSOL',
    'LIGDN': 'LIQDN',
    'S252': '252',
    'INST': 'INSTR',
    'ADJD': 'ADJ',
    'AUDT': 'AUDTR',
    'BILL': 'BILLS',
}

# Case statuses (ordered)
CASE_STATUSES = [
    'Open',
    'Assigned',
    'Under Investigation',
    'Awaiting Response',
    'Resolved',
    'Closed',
]

# Letter statuses
LETTER_STATUSES = ['Unassigned', 'Assigned', 'In Progress', 'Resolved']

# Priority choices (config level – forms may add Critical)
PRIORITY_CHOICES = ['High', 'Medium', 'Low']

# Deadline day choices
DEADLINE_CHOICES = [1, 3, 7, 10, 14, 21, 30]

# SLA days by priority
SLA_DAYS = {
    'Critical': 3,
    'High': 6,
    'Medium': 9,
    'Low': 15,
}

# Default ROC office address
DEFAULT_ROC_ADDRESS = (
    'Sheti Mahamandal Bhavan, 1st Floor, 270, Bhamburda, '
    'Senapati Bapat Road, Pune 411016'
)


def _get_or_generate_secret_key():
    """Read SECRET_KEY from env or instance/secret_key file; generate if missing."""
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    instance_path = get_instance_path()
    key_file = os.path.join(instance_path, 'secret_key')
    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            return f.read().strip()
    import secrets
    key = secrets.token_hex(32)
    os.makedirs(instance_path, exist_ok=True)
    with open(key_file, 'w') as f:
        f.write(key)
    return key


class Config:
    INSTANCE_PATH = get_instance_path()
    DATA_DIR = get_data_path()
    SECRET_KEY = _get_or_generate_secret_key()
    SQLALCHEMY_DATABASE_URI = _normalize_database_uri(os.environ.get('DATABASE_URL')) or \
        'sqlite:///' + os.path.join(DATA_DIR, 'letter_tracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_DB_BOOTSTRAP = _env_bool('AUTO_DB_BOOTSTRAP', True)

    UPLOAD_FOLDER = _resolve_path(
        os.environ.get('UPLOAD_FOLDER'),
        os.path.join(DATA_DIR, 'uploads', 'attachments')
    )
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # Disable CSRF token expiry
    SESSION_COOKIE_HTTPONLY = True

    OFFICE_CODE = 'ROCP'
    ALERT_WARNING_HOURS = 24
    LOGIN_RATE_LIMIT = '6 per minute'
    DEFAULT_RATE_LIMIT = '200 per day'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

    SECTIONS = SECTIONS
    SECTION_CODE_MIGRATION = SECTION_CODE_MIGRATION
    CASE_STATUSES = CASE_STATUSES
    LETTER_STATUSES = LETTER_STATUSES
    PRIORITY_CHOICES = PRIORITY_CHOICES
    DEADLINE_CHOICES = DEADLINE_CHOICES
    SLA_DAYS = SLA_DAYS
    DEFAULT_ROC_ADDRESS = DEFAULT_ROC_ADDRESS


class DevelopmentConfig(Config):
    DEBUG = True
    WTF_CSRF_ENABLED = False  # Disable CSRF in dev for iframe/Simple Browser compatibility
    SESSION_COOKIE_SAMESITE = None
    SESSION_COOKIE_SECURE = False
    LOGIN_RATE_LIMIT = '30 per minute'


class ProductionConfig(Config):
    DEBUG = False
    PREFERRED_URL_SCHEME = 'https'
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    AUTO_DB_BOOTSTRAP = False
    LOGIN_RATE_LIMIT = '999 per minute'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
