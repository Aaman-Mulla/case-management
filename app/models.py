import hashlib
from datetime import datetime, timezone, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db

# ---------------------------------------------------------------------------
# Datetime helper – replaces deprecated datetime.utcnow() for Python 3.12+
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    role = db.Column(db.String(20), default='user', nullable=False)
    is_active_user = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    # Relationships
    assigned_letters = db.relationship(
        'Letter', foreign_keys='Letter.assignee_id',
        backref='assignee', lazy='dynamic'
    )
    notifications = db.relationship(
        'Notification', backref='user', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    assigned_cases = db.relationship(
        'Case', foreign_keys='Case.assignee_id',
        backref='assignee', lazy='dynamic'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_data_entry(self):
        return self.role == 'data_entry'

    @property
    def role_display(self):
        mapping = {'admin': 'ROC', 'data_entry': 'Data Entry', 'user': 'User'}
        return mapping.get(self.role, self.role)

    # Flask-Login integration
    @property
    def is_active(self):
        return self.is_active_user

    def __repr__(self):
        return f'<User {self.username}>'


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------

class Section(db.Model):
    __tablename__ = 'section'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)

    @staticmethod
    def get_choices():
        """Return list of (code, name) tuples for form choices."""
        from flask import current_app
        sections = Section.query.filter_by(is_active=True).order_by(Section.code).all()
        if sections:
            return [(s.code, s.name) for s in sections]
        # Fallback to config list
        return current_app.config.get('SECTIONS', [])

    def __repr__(self):
        return f'<Section {self.code}>'


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

class Case(db.Model):
    __tablename__ = 'case'

    id = db.Column(db.Integer, primary_key=True)
    reference_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    section = db.Column(db.String(20), nullable=False, index=True)
    complainant = db.Column(db.String(200), nullable=True)
    respondent = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), default='Open', nullable=False)
    priority = db.Column(db.String(20), nullable=True)
    deadline_date = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)
    total_paused_days = db.Column(db.Integer, default=0)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    letters = db.relationship(
        'Letter', backref='case', lazy='dynamic',
        order_by='Letter.import_date.asc()'
    )
    case_activity_logs = db.relationship(
        'CaseActivityLog', backref='case', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    comments = db.relationship(
        'Comment', backref='case_rel',
        primaryjoin='Comment.case_id == Case.id',
        lazy='dynamic', cascade='all, delete-orphan'
    )
    attachments = db.relationship(
        'Attachment', backref='case_rel',
        primaryjoin='Attachment.case_id == Case.id',
        lazy='dynamic', cascade='all, delete-orphan'
    )
    status_history = db.relationship(
        'StatusHistory', backref='case_rel',
        primaryjoin='StatusHistory.case_id == Case.id',
        lazy='dynamic', cascade='all, delete-orphan'
    )

    @staticmethod
    def get_financial_year(dt=None):
        """Return financial year string e.g. '2025-26'."""
        if dt is None:
            dt = _utcnow()
        if dt.month >= 4:
            start_year = dt.year
        else:
            start_year = dt.year - 1
        end_year = start_year + 1
        return f'{start_year}-{str(end_year)[-2:]}'

    @staticmethod
    def generate_reference_number(section_code):
        """Generate ROCP/<FY>/<SECTION>/<5-digit-seq>."""
        from flask import current_app
        office_code = current_app.config.get('OFFICE_CODE', 'ROCP')
        fy = Case.get_financial_year()
        prefix = f'{office_code}/{fy}/{section_code}/'
        last_case = Case.query.filter(
            Case.reference_number.like(f'{prefix}%')
        ).order_by(Case.id.desc()).first()
        if last_case:
            try:
                last_seq = int(last_case.reference_number.split('/')[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0
        new_seq = str(last_seq + 1).zfill(5)
        return f'{prefix}{new_seq}'

    @property
    def inward_letters(self):
        return self.letters.filter_by(direction='Inward').all()

    @property
    def outward_letters(self):
        return self.letters.filter_by(direction='Outward').all()

    @property
    def letter_count(self):
        return self.letters.count()

    @property
    def is_paused(self):
        return self.paused_at is not None

    @property
    def date_assigned(self):
        if not self.assignee_id:
            return None
        first_assigned_letter = self.letters.filter(
            Letter.assignment_date.isnot(None),
            Letter.assignee_id == self.assignee_id,
        ).order_by(Letter.assignment_date.asc()).first()
        if first_assigned_letter:
            return first_assigned_letter.assignment_date
        return None

    @property
    def days_remaining(self):
        if not self.deadline_date:
            return None
        reference_time = self.paused_at if self.is_paused and self.paused_at else _utcnow()
        return (self.deadline_date - reference_time).days

    @property
    def is_overdue(self):
        if not self.deadline_date:
            return False
        if self.status in ('Resolved', 'Closed'):
            return False
        remaining = self.days_remaining
        return remaining is not None and remaining < 0

    def pause_deadline(self):
        if not self.is_paused:
            self.paused_at = _utcnow()

    def resume_deadline(self):
        if self.is_paused and self.paused_at:
            paused_delta = _utcnow() - self.paused_at
            paused_days = int(paused_delta.total_seconds() // 86400)
            self.total_paused_days = (self.total_paused_days or 0) + paused_days
            if self.deadline_date:
                self.deadline_date += paused_delta
            self.paused_at = None

    def __repr__(self):
        return f'<Case {self.reference_number}>'


# ---------------------------------------------------------------------------
# Letter
# ---------------------------------------------------------------------------

class Letter(db.Model):
    __tablename__ = 'letter'

    id = db.Column(db.Integer, primary_key=True)
    from_address = db.Column(db.Text, nullable=True)
    sender_name = db.Column(db.String(200), nullable=True)
    to_address = db.Column(db.Text, nullable=True)
    subject = db.Column(db.Text, nullable=True)
    unique_hash = db.Column(db.String(64), unique=True, nullable=True, index=True)
    received_date = db.Column(db.DateTime, nullable=True)
    import_date = db.Column(db.DateTime, default=_utcnow)
    direction = db.Column(db.String(10), default='Inward', nullable=False)
    section = db.Column(db.String(20), nullable=True, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True, index=True)
    status = db.Column(db.String(30), default='Unassigned', nullable=False)
    priority = db.Column(db.String(20), nullable=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assignment_date = db.Column(db.DateTime, nullable=True)
    deadline_date = db.Column(db.DateTime, nullable=True)
    resolution_date = db.Column(db.DateTime, nullable=True)

    # Relationships
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    activity_logs = db.relationship(
        'ActivityLog', backref='letter', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    comments = db.relationship(
        'Comment', backref='letter_rel',
        primaryjoin='Comment.letter_id == Letter.id',
        lazy='dynamic', cascade='all, delete-orphan',
        order_by='Comment.created_at.desc()'
    )
    attachments = db.relationship(
        'Attachment', backref='letter_rel',
        primaryjoin='Attachment.letter_id == Letter.id',
        lazy='dynamic', cascade='all, delete-orphan'
    )
    status_history = db.relationship(
        'StatusHistory', backref='letter_rel',
        primaryjoin='StatusHistory.letter_id == Letter.id',
        lazy='dynamic', cascade='all, delete-orphan'
    )

    @staticmethod
    def generate_hash(from_address, to_address, subject):
        raw = f'{(from_address or "").strip().lower()}|{(to_address or "").strip().lower()}|{(subject or "").strip().lower()}'
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @property
    def is_overdue(self):
        if not self.deadline_date:
            return False
        if self.status in ('Resolved', 'Closed', 'Outward'):
            return False
        return _utcnow() > self.deadline_date

    @property
    def is_near_deadline(self):
        if not self.deadline_date:
            return False
        if self.status in ('Resolved', 'Closed', 'Outward'):
            return False
        remaining = (self.deadline_date - _utcnow()).total_seconds() / 3600
        return 0 < remaining <= 24

    @property
    def days_remaining(self):
        if not self.deadline_date:
            return None
        return (self.deadline_date - _utcnow()).days

    @property
    def effective_status(self):
        if self.is_overdue:
            return 'Overdue'
        return self.status

    def __repr__(self):
        return f'<Letter {self.id} {self.direction}>'


# ---------------------------------------------------------------------------
# ActivityLog (letters)
# ---------------------------------------------------------------------------

class ActivityLog(db.Model):
    __tablename__ = 'activity_log'

    id = db.Column(db.Integer, primary_key=True)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=_utcnow)

    actor = db.relationship('User', foreign_keys=[actor_id])

    def __repr__(self):
        return f'<ActivityLog {self.id}>'


# ---------------------------------------------------------------------------
# CaseActivityLog
# ---------------------------------------------------------------------------

class CaseActivityLog(db.Model):
    __tablename__ = 'case_activity_log'

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=_utcnow)

    actor = db.relationship('User', foreign_keys=[actor_id])

    def __repr__(self):
        return f'<CaseActivityLog {self.id}>'


# ---------------------------------------------------------------------------
# Comment (letters + cases)
# ---------------------------------------------------------------------------

class Comment(db.Model):
    __tablename__ = 'comment'

    id = db.Column(db.Integer, primary_key=True)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    author = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f'<Comment {self.id}>'


# ---------------------------------------------------------------------------
# Attachment (letters + cases)
# ---------------------------------------------------------------------------

class Attachment(db.Model):
    __tablename__ = 'attachment'

    id = db.Column(db.Integer, primary_key=True)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    content_type = db.Column(db.String(100), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=_utcnow)

    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id])

    @property
    def file_size_display(self):
        if not self.file_size:
            return '0 B'
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

    def __repr__(self):
        return f'<Attachment {self.original_filename}>'


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

class Reminder(db.Model):
    __tablename__ = 'reminder'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True)
    remind_at = db.Column(db.DateTime, nullable=False)
    message = db.Column(db.Text, nullable=True)
    is_triggered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    letter = db.relationship('Letter', foreign_keys=[letter_id])
    case = db.relationship('Case', foreign_keys=[case_id])

    def __repr__(self):
        return f'<Reminder {self.id}>'


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    letter = db.relationship('Letter', foreign_keys=[letter_id])

    def __repr__(self):
        return f'<Notification {self.id}>'


# ---------------------------------------------------------------------------
# StatusHistory (letters + cases)
# ---------------------------------------------------------------------------

class StatusHistory(db.Model):
    __tablename__ = 'status_history'

    id = db.Column(db.Integer, primary_key=True)
    letter_id = db.Column(db.Integer, db.ForeignKey('letter.id'), nullable=True, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True, index=True)
    old_status = db.Column(db.String(30), nullable=True)
    new_status = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    changed_at = db.Column(db.DateTime, default=_utcnow)
    reason = db.Column(db.Text, nullable=True)

    changed_by = db.relationship('User', foreign_keys=[changed_by_id])

    def __repr__(self):
        return f'<StatusHistory {self.id}>'
