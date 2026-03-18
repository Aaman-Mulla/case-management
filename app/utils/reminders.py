"""Reminder processing utility."""

from app import db
from app.models import Reminder, Notification, _utcnow


def process_due_reminders():
    """Process due reminders and create notifications."""
    now = _utcnow()
    due_reminders = Reminder.query.filter(
        Reminder.is_triggered == False,
        Reminder.remind_at <= now
    ).all()

    for reminder in due_reminders:
        message = reminder.message or 'You have a reminder.'
        if reminder.letter_id:
            message = f'Reminder: {message} (Letter #{reminder.letter_id})'
        elif reminder.case_id:
            message = f'Reminder: {message} (Case #{reminder.case_id})'

        notification = Notification(
            user_id=reminder.user_id,
            letter_id=reminder.letter_id,
            message=message,
            notification_type='reminder'
        )
        db.session.add(notification)
        reminder.is_triggered = True

    db.session.commit()
