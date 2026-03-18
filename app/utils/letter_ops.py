"""Shared business-logic helpers for letter create/assign operations.

These functions encapsulate the DB writes that are duplicated across the
admin and data_entry blueprints.  Route handlers remain thin: they own
form validation, flash messages, template selection, and redirect targets.

All helpers *flush* (making the new row visible inside the same session)
but do NOT commit — callers decide when to commit so they can chain
additional writes before persisting.
"""

from datetime import timedelta

from flask_login import current_user

from app import db
from app.models import (
    Letter, ActivityLog, Notification, Case,
    CaseActivityLog, StatusHistory, User, _utcnow,
)


# ---------------------------------------------------------------------------
# Inward letter
# ---------------------------------------------------------------------------

def build_inward_letter_from_form(form, *, actor_label: str) -> Letter:
    """Create an Inward Letter from a validated AddLetterForm.

    Adds the Letter, a 'Created' ActivityLog, and (if assignee is set) an
    'Assigned' ActivityLog + assignment Notification.  Flushes but does not
    commit — caller must call ``db.session.commit()``.

    Returns the newly-created Letter instance.
    """
    hash_val = Letter.generate_hash(
        form.from_address.data, form.to_address.data, form.subject.data
    )

    assignee_id = (
        form.assignee_id.data
        if form.assignee_id.data and form.assignee_id.data > 0
        else None
    )
    deadline_date = None
    if assignee_id and form.deadline_days.data:
        deadline_date = _utcnow() + timedelta(days=form.deadline_days.data)

    letter = Letter(
        from_address=form.from_address.data,
        sender_name=form.sender_name.data or None,
        to_address=form.to_address.data,
        subject=form.subject.data,
        unique_hash=hash_val,
        received_date=form.received_date.data if form.received_date.data else None,
        direction='Inward',
        section=form.section.data or None,
        priority=form.priority.data or None,
        status='Assigned' if assignee_id else 'Unassigned',
        deadline_date=deadline_date,
        assignee_id=assignee_id,
        assigned_by_id=current_user.id if assignee_id else None,
        assignment_date=_utcnow() if assignee_id else None,
        created_by_id=current_user.id,
    )
    db.session.add(letter)
    db.session.flush()

    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Created',
        details=f'Inward letter created by {actor_label}.',
    ))

    if letter.assignee_id:
        db.session.add(ActivityLog(
            letter_id=letter.id, actor_id=current_user.id,
            action='Assigned',
            details=f'Assigned to user #{letter.assignee_id}.',
        ))
        db.session.add(Notification(
            user_id=letter.assignee_id, letter_id=letter.id,
            message=f'You have been assigned letter: "{letter.subject[:50]}".',
            notification_type='assignment',
        ))

    return letter


# ---------------------------------------------------------------------------
# Outward letter
# ---------------------------------------------------------------------------

def build_outward_letter_from_form(form, *, actor_label: str) -> Letter:
    """Create an Outward Letter from a validated AddOutwardLetterForm.

    Handles optional case-linking, CaseActivityLog, and 'Awaiting Response'
    status transition.  Flushes but does not commit — caller must commit.

    Returns the newly-created Letter instance.
    """
    case = None
    section = form.section.data or None
    if form.case_id.data and form.case_id.data > 0:
        case = db.session.get(Case, form.case_id.data)
        if case:
            section = case.section

    letter = Letter(
        from_address=form.from_address.data,
        sender_name=form.sender_name.data or None,
        to_address=form.to_address.data,
        subject=form.subject.data,
        received_date=form.sent_date.data if form.sent_date.data else None,
        direction='Outward',
        section=section,
        case_id=case.id if case else None,
        status='Outward',
        deadline_date=(
            _utcnow() + timedelta(days=form.deadline_days.data)
            if form.deadline_days.data else None
        ),
        created_by_id=current_user.id,
    )
    letter.unique_hash = Letter.generate_hash(
        letter.from_address, letter.to_address, letter.subject
    )
    db.session.add(letter)
    db.session.flush()

    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Created',
        details=f'Outward letter created by {actor_label}.',
    ))

    if case:
        db.session.add(CaseActivityLog(
            case_id=case.id, actor_id=current_user.id,
            action='Outward Letter Added',
            details=f'Outward letter #{letter.id} added to case.',
        ))
        if form.mark_awaiting.data and case.status != 'Awaiting Response':
            old_status = case.status
            case.status = 'Awaiting Response'
            case.pause_deadline()
            db.session.add(StatusHistory(
                case_id=case.id, old_status=old_status,
                new_status='Awaiting Response',
                changed_by_id=current_user.id,
                reason='Outward letter sent, marking awaiting response.',
            ))

    return letter


# ---------------------------------------------------------------------------
# Assign / unassign
# ---------------------------------------------------------------------------

def perform_assign_letter(
    letter: Letter,
    user_id: int,
    deadline_days,
    *,
    actor_label: str,
) -> None:
    """Assign *letter* to *user_id*.

    Updates letter fields, adds an ActivityLog and a Notification.
    Does not flush or commit — caller decides when.
    """
    was_unassigned = letter.status == 'Unassigned'
    letter.assignee_id = user_id
    letter.assigned_by_id = current_user.id
    letter.assignment_date = _utcnow()

    if deadline_days:
        letter.deadline_date = _utcnow() + timedelta(days=deadline_days)
    elif was_unassigned:
        letter.deadline_date = None

    if letter.status == 'Unassigned':
        letter.status = 'Assigned'

    assignee = db.session.get(User, user_id)
    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Assigned',
        details=(
            f'Assigned to {assignee.full_name if assignee else user_id}'
            f' by {actor_label}.'
        ),
    ))
    db.session.add(Notification(
        user_id=user_id, letter_id=letter.id,
        message=f'You have been assigned letter: "{letter.subject[:50]}".',
        notification_type='assignment',
    ))


def perform_unassign_letter(letter: Letter, *, actor_label: str) -> None:
    """Clear assignment from *letter*.

    Updates letter fields and adds an ActivityLog.
    Does not flush or commit — caller decides when.
    """
    letter.assignee_id = None
    letter.assigned_by_id = None
    letter.assignment_date = None
    letter.deadline_date = None
    letter.status = 'Unassigned'

    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Unassigned',
        details=f'Letter unassigned by {actor_label}.',
    ))
