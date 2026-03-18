"""Deadline alert checking utility."""

from datetime import timedelta

from app import db
from app.models import Letter, Notification, User, Case, _utcnow


def check_deadline_alerts():
    """Check for letters and cases nearing or past their deadlines and create notifications."""
    now = _utcnow()
    warning_hours = 24
    threshold = now + timedelta(hours=warning_hours)

    admin_users = User.query.filter_by(role='admin', is_active_user=True).all()

    # Check letters approaching deadline
    letters = Letter.query.filter(
        Letter.deadline_date.isnot(None),
        Letter.deadline_date <= threshold,
        ~Letter.status.in_(['Resolved', 'Closed', 'Outward'])
    ).all()

    for letter in letters:
        days_left = (letter.deadline_date - now).days
        if days_left < 0:
            message = f'Letter #{letter.id} "{letter.subject[:50]}" is OVERDUE by {abs(days_left)} day(s).'
            ntype = 'overdue'
        else:
            message = f'Letter #{letter.id} "{letter.subject[:50]}" deadline is in {days_left} day(s).'
            ntype = 'deadline_warning'

        if letter.assignee_id:
            _ensure_notification(letter.assignee_id, letter.id, message, ntype)

        for admin in admin_users:
            if admin.id != letter.assignee_id:
                _ensure_notification(admin.id, letter.id, message, ntype)

    # Check cases approaching deadline
    cases = Case.query.filter(
        Case.deadline_date.isnot(None),
        Case.deadline_date <= threshold,
        ~Case.status.in_(['Resolved', 'Closed']),
        Case.paused_at.is_(None)
    ).all()

    for case in cases:
        days_left = (case.deadline_date - now).days
        if days_left < 0:
            message = f'Case {case.reference_number} is OVERDUE by {abs(days_left)} day(s).'
            ntype = 'case_overdue'
        else:
            message = f'Case {case.reference_number} deadline is in {days_left} day(s).'
            ntype = 'case_deadline_warning'

        if case.assignee_id:
            _ensure_notification(case.assignee_id, None, message, ntype)

        for admin in admin_users:
            if admin.id != case.assignee_id:
                _ensure_notification(admin.id, None, message, ntype)

    db.session.commit()


def _ensure_notification(user_id, letter_id, message, ntype):
    """Create notification if one with same type isn't already unread."""
    existing = Notification.query.filter_by(
        user_id=user_id,
        notification_type=ntype,
        is_read=False
    )
    if letter_id:
        existing = existing.filter_by(letter_id=letter_id)
    existing = existing.first()

    if not existing:
        db.session.add(Notification(
            user_id=user_id,
            letter_id=letter_id,
            message=message,
            notification_type=ntype
        ))
