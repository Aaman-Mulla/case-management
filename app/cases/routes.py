from datetime import timedelta

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.cases import bp
from app.admin.forms import AssignCaseForm, AddOutwardLetterForm, AddLetterForm, LinkToCaseForm, CreateCaseForm
from app.models import (
    Case, Letter, User, Section, CaseActivityLog, ActivityLog,
    Comment, Attachment, StatusHistory, Notification, _utcnow, db
)
from config import CASE_STATUSES


def _is_awaiting_response(status):
    return (status or '').strip().lower() == 'awaiting response'


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route('/dashboard')
@login_required
def dashboard():
    if not current_user.is_admin and not current_user.is_data_entry:
        return redirect(url_for('cases.my_cases'))

    query = Case.query

    # Filters
    status = request.args.get('status', '').strip()
    section = request.args.get('section', '').strip()
    assignee = request.args.get('assignee', '').strip()
    paused_only = request.args.get('paused', '').strip()
    q = request.args.get('q', '').strip()
    active_filters = {}

    if status:
        query = query.filter(Case.status == status)
        active_filters['status'] = status
    if section:
        query = query.filter(Case.section == section)
        active_filters['section'] = section
    if assignee:
        try:
            assignee_id = int(assignee)
            query = query.filter(Case.assignee_id == assignee_id)
            assignee_user = db.session.get(User, assignee_id)
            active_filters['assignee'] = (
                (assignee_user.full_name or assignee_user.username)
                if assignee_user else f'User #{assignee_id}'
            )
        except ValueError:
            pass
    if paused_only in ('1', 'true', 'yes', 'on'):
        query = query.filter(Case.paused_at.isnot(None))
        active_filters['paused'] = 'Yes'
    if q:
        search = f'%{q}%'
        query = query.filter(db.or_(
            Case.reference_number.ilike(search),
            Case.title.ilike(search),
            Case.description.ilike(search)
        ))
        active_filters['q'] = q

    cases = query.order_by(Case.created_at.desc()).all()

    # Stats
    stats = {s: sum(1 for c in cases if c.status == s) for s in CASE_STATUSES}
    stats['total'] = len(cases)

    sections = Section.get_choices()
    users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()

    return render_template('cases/dashboard.html',
                           cases=cases, stats=stats,
                           active_filters=active_filters,
                           sections=sections, case_statuses=CASE_STATUSES,
                           users=users)


# ---------------------------------------------------------------------------
# My Cases (user-only)
# ---------------------------------------------------------------------------
@bp.route('/my-cases')
@login_required
def my_cases():
    cases = Case.query.filter_by(assignee_id=current_user.id).all()

    # Sort: active first, closed last, nearest deadline first
    def sort_key(c):
        is_closed = 1 if c.status == 'Closed' else 0
        deadline = c.deadline_date or _utcnow() + timedelta(days=9999)
        return (is_closed, deadline)

    cases.sort(key=sort_key)

    stats = {s: sum(1 for c in cases if c.status == s) for s in CASE_STATUSES}
    stats['total'] = len(cases)

    return render_template('cases/my_cases.html',
                           cases=cases, stats=stats,
                           case_statuses=CASE_STATUSES)


# ---------------------------------------------------------------------------
# Case Detail
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>')
@login_required
def case_detail(case_id):
    case = Case.query.get_or_404(case_id)

    if not current_user.is_admin and not current_user.is_data_entry:
        if case.assignee_id != current_user.id:
            abort(403)

    inward_letters = case.inward_letters
    outward_letters = case.outward_letters
    comments = case.comments.order_by(Comment.created_at.desc()).all()
    attachments = case.attachments.all()
    activity_logs = case.case_activity_logs.order_by(CaseActivityLog.timestamp.desc()).all()
    status_history = case.status_history.order_by(StatusHistory.changed_at.desc()).all()

    return render_template('cases/case_detail.html',
                           case=case, inward_letters=inward_letters,
                           outward_letters=outward_letters,
                           comments=comments, attachments=attachments,
                           activity_logs=activity_logs,
                           status_history=status_history,
                           case_statuses=CASE_STATUSES)


# ---------------------------------------------------------------------------
# Assign Case
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/assign', methods=['GET', 'POST'])
@login_required
def assign_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin and not current_user.is_data_entry:
        abort(403)

    form = AssignCaseForm()
    if form.validate_on_submit():
        user_id = form.assignee_id.data
        if user_id and user_id > 0:
            old_assignee = case.assignee_id
            case.assignee_id = user_id
            case.assigned_by_id = current_user.id
            if form.deadline_days.data:
                case.deadline_date = _utcnow() + timedelta(days=form.deadline_days.data)
            elif not old_assignee:
                case.deadline_date = None
            if case.status == 'Open':
                case.status = 'Assigned'
                db.session.add(StatusHistory(
                    case_id=case.id, old_status='Open',
                    new_status='Assigned', changed_by_id=current_user.id
                ))

            db.session.add(CaseActivityLog(
                case_id=case.id, actor_id=current_user.id,
                action='Assigned',
                details=f'Case assigned to user #{user_id}.'
            ))
            db.session.add(Notification(
                user_id=user_id,
                message=f'You have been assigned case {case.reference_number}.',
                notification_type='case_assignment'
            ))
            db.session.commit()
            flash('Case assigned.', 'success')
            return redirect(url_for('cases.case_detail', case_id=case.id))

    return render_template('cases/assign_case.html', form=form, case=case)


# ---------------------------------------------------------------------------
# Unassign Case
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/unassign', methods=['POST'])
@login_required
def unassign_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin and not current_user.is_data_entry:
        abort(403)

    old_assignee = case.assignee_id
    case.assignee_id = None
    case.assigned_by_id = None
    case.deadline_date = None
    if case.status == 'Assigned':
        case.status = 'Open'
        db.session.add(StatusHistory(
            case_id=case.id, old_status='Assigned',
            new_status='Open', changed_by_id=current_user.id
        ))

    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Unassigned',
        details='Case unassigned.'
    ))
    db.session.commit()
    flash('Case unassigned.', 'info')
    return redirect(url_for('cases.case_detail', case_id=case.id))


# ---------------------------------------------------------------------------
# Update Case Status
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/update-status', methods=['POST'])
@login_required
def update_case_status(case_id):
    case = Case.query.get_or_404(case_id)

    if not current_user.is_admin and not current_user.is_data_entry:
        if case.assignee_id != current_user.id:
            abort(403)

    new_status = request.form.get('status')
    reason = request.form.get('reason', '').strip()

    if new_status not in CASE_STATUSES:
        flash('Invalid status.', 'danger')
        return redirect(url_for('cases.case_detail', case_id=case_id))

    old_status = case.status
    case.status = new_status
    case.updated_at = _utcnow()

    # Pause/resume deadline
    if _is_awaiting_response(new_status) and not _is_awaiting_response(old_status):
        case.pause_deadline()
    elif _is_awaiting_response(old_status) and not _is_awaiting_response(new_status):
        case.resume_deadline()

    # Auto-resolve letters when closing
    if new_status == 'Closed':
        open_letters = case.letters.filter(
            ~Letter.status.in_(['Resolved', 'Closed', 'Outward'])
        ).all()
        for letter in open_letters:
            letter_old_status = letter.status
            letter.status = 'Resolved'
            letter.resolution_date = _utcnow()
            db.session.add(StatusHistory(
                letter_id=letter.id, old_status=letter_old_status,
                new_status='Resolved', changed_by_id=current_user.id,
                reason='Auto-resolved on case closure.'
            ))

    db.session.add(StatusHistory(
        case_id=case.id, old_status=old_status,
        new_status=new_status, changed_by_id=current_user.id,
        reason=reason or None
    ))
    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Status Changed',
        details=f'Status changed from {old_status} to {new_status}.'
    ))

    # Notify
    if case.assignee_id and case.assignee_id != current_user.id:
        db.session.add(Notification(
            user_id=case.assignee_id,
            message=f'Case {case.reference_number} status changed to {new_status}.',
            notification_type='case_status_change'
        ))
    if not current_user.is_admin:
        admins = User.query.filter_by(role='admin', is_active_user=True).all()
        for admin in admins:
            if admin.id != current_user.id:
                db.session.add(Notification(
                    user_id=admin.id,
                    message=f'Case {case.reference_number} status changed to {new_status} by {current_user.full_name or current_user.username}.',
                    notification_type='case_status_change'
                ))

    db.session.commit()
    flash(f'Case status updated to {new_status}.', 'success')
    return redirect(url_for('cases.case_detail', case_id=case_id))


# ---------------------------------------------------------------------------
# Create Case from Letter
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Create Case (standalone) — UX-2
# ---------------------------------------------------------------------------
@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_case():
    if current_user.is_data_entry:
        abort(403)

    form = CreateCaseForm()
    if form.validate_on_submit():
        section = form.section.data
        ref_number = Case.generate_reference_number(section)

        priority = form.priority.data or None

        assignee_id = form.assignee_id.data if form.assignee_id.data and form.assignee_id.data > 0 else None

        case = Case(
            reference_number=ref_number,
            title=form.title.data,
            description=form.description.data or None,
            section=section,
            priority=priority,
            assignee_id=assignee_id,
            assigned_by_id=current_user.id if assignee_id else None,
            created_by_id=current_user.id,
            status='Assigned' if assignee_id else 'Open',
        )

        db.session.add(case)
        db.session.flush()

        db.session.add(CaseActivityLog(
            case_id=case.id, actor_id=current_user.id,
            action='Created', details='Case created from dashboard.'
        ))

        if assignee_id and assignee_id != current_user.id:
            db.session.add(Notification(
                user_id=assignee_id,
                message=f'A new case {case.reference_number} has been created and assigned to you.',
                notification_type='case_created'
            ))

        db.session.commit()
        flash(f'Case {case.reference_number} created.', 'success')
        return redirect(url_for('cases.case_detail', case_id=case.id))

    return render_template('cases/create_case.html', form=form)


# ---------------------------------------------------------------------------
# Create from Letter
# ---------------------------------------------------------------------------
@bp.route('/create-from-letter/<int:letter_id>', methods=['POST'])
@login_required
def create_from_letter(letter_id):
    letter = Letter.query.get_or_404(letter_id)

    # Permissions
    if current_user.is_data_entry:
        abort(403)
    if not current_user.is_admin and letter.assignee_id != current_user.id:
        abort(403)
    if letter.case_id:
        flash('This letter is already linked to a case.', 'warning')
        return redirect(url_for('main.letter_detail', id=letter_id))

    section = letter.section or 'MISC'
    ref_number = Case.generate_reference_number(section)

    case = Case(
        reference_number=ref_number,
        title=letter.subject,
        section=section,
        priority=letter.priority,
        deadline_date=letter.deadline_date,
        assignee_id=letter.assignee_id,
        assigned_by_id=letter.assigned_by_id or current_user.id,
        created_by_id=current_user.id,
        status='Assigned' if letter.assignee_id else 'Open',
    )

    db.session.add(case)
    db.session.flush()

    if letter.direction == 'Outward' and not _is_awaiting_response(case.status):
        old_status = case.status
        case.status = 'Awaiting Response'
        case.pause_deadline()
        db.session.add(StatusHistory(
            case_id=case.id, old_status=old_status,
            new_status='Awaiting Response', changed_by_id=current_user.id,
            reason='Outward letter linked on case creation, awaiting response.'
        ))

    # Link letter
    letter.case_id = case.id
    if letter.direction != 'Inward':
        letter.direction = 'Inward'

    # Propagate attachments to case
    for att in letter.attachments.all():
        att.case_id = case.id

    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Created', details=f'Case created from letter #{letter.id}.'
    ))
    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Linked to Case',
        details=f'Linked to new case {case.reference_number}.'
    ))

    # Notifications
    if case.assignee_id and case.assignee_id != current_user.id:
        db.session.add(Notification(
            user_id=case.assignee_id,
            message=f'A new case {case.reference_number} has been created and assigned to you.',
            notification_type='case_created'
        ))
    admins = User.query.filter_by(role='admin', is_active_user=True).all()
    for admin in admins:
        if admin.id != current_user.id:
            db.session.add(Notification(
                user_id=admin.id,
                message=f'New case {case.reference_number} created by {current_user.full_name or current_user.username}.',
                notification_type='case_created'
            ))

    db.session.commit()
    flash(f'Case {case.reference_number} created.', 'success')
    return redirect(url_for('cases.case_detail', case_id=case.id))


# ---------------------------------------------------------------------------
# Link Letter to Case
# ---------------------------------------------------------------------------
@bp.route('/link-letter/<int:letter_id>', methods=['GET', 'POST'])
@login_required
def link_letter(letter_id):
    letter = Letter.query.get_or_404(letter_id)
    if letter.case_id:
        flash('This letter is already linked to a case.', 'warning')
        return redirect(url_for('main.letter_detail', id=letter_id))

    if not current_user.is_admin and not current_user.is_data_entry:
        if letter.assignee_id != current_user.id:
            abort(403)

    form = LinkToCaseForm()
    if form.validate_on_submit():
        case_id = form.case_id.data
        if case_id and case_id > 0:
            case = db.session.get(Case, case_id)
            if not case:
                flash('Case not found.', 'danger')
                return redirect(url_for('main.letter_detail', id=letter_id))

            letter.case_id = case.id

            if _is_awaiting_response(case.status) and letter.direction == 'Inward':
                case.resume_deadline()
                old_status = case.status
                case.status = 'Under Investigation'
                db.session.add(StatusHistory(
                    case_id=case.id, old_status=old_status,
                    new_status='Under Investigation',
                    changed_by_id=current_user.id,
                    reason='Inward letter linked, resuming investigation.'
                ))
            elif not _is_awaiting_response(case.status) and letter.direction == 'Outward':
                old_status = case.status
                case.status = 'Awaiting Response'
                case.pause_deadline()
                db.session.add(StatusHistory(
                    case_id=case.id, old_status=old_status,
                    new_status='Awaiting Response',
                    changed_by_id=current_user.id,
                    reason='Outward letter linked, awaiting response.'
                ))

            db.session.add(CaseActivityLog(
                case_id=case.id, actor_id=current_user.id,
                action='Letter Linked',
                details=f'Letter #{letter.id} linked to case.'
            ))
            db.session.add(ActivityLog(
                letter_id=letter.id, actor_id=current_user.id,
                action='Linked to Case',
                details=f'Linked to case {case.reference_number}.'
            ))
            db.session.commit()
            flash(f'Letter linked to case {case.reference_number}.', 'success')
            return redirect(url_for('cases.case_detail', case_id=case.id))

    return render_template('cases/link_letter.html', form=form, letter=letter)


# ---------------------------------------------------------------------------
# Delete Case
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/delete', methods=['POST'])
@login_required
def delete_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin:
        abort(403)

    # Unlink all letters
    for letter in case.letters.all():
        letter.case_id = None

    db.session.delete(case)
    db.session.commit()
    flash(f'Case {case.reference_number} deleted.', 'info')
    return redirect(url_for('cases.dashboard'))


# ---------------------------------------------------------------------------
# Unlink Letter from Case
# ---------------------------------------------------------------------------
@bp.route('/unlink-letter/<int:letter_id>', methods=['POST'])
@login_required
def unlink_letter(letter_id):
    letter = Letter.query.get_or_404(letter_id)
    if not letter.case_id:
        flash('Letter is not linked to any case.', 'warning')
        return redirect(url_for('main.letter_detail', id=letter_id))

    case = letter.case
    if current_user.is_data_entry:
        abort(403)
    if not current_user.is_admin and case.created_by_id != current_user.id:
        abort(403)

    # Check if this is the last letter
    letter_count = case.letters.count()

    letter.case_id = None
    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Unlinked from Case',
        details=f'Unlinked from case {case.reference_number}.'
    ))
    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Letter Unlinked',
        details=f'Letter #{letter.id} unlinked.'
    ))

    if letter_count <= 1:
        # Last linked letter – remove the now-empty case as part of the same confirmed action
        db.session.delete(case)
        db.session.commit()
        flash('Letter unlinked and empty case deleted.', 'info')
        return redirect(url_for('main.letter_detail', id=letter_id))
    else:
        db.session.commit()
        flash('Letter unlinked from case.', 'info')
        return redirect(url_for('cases.case_detail', case_id=case.id))


# ---------------------------------------------------------------------------
# Add Inward to Case
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/add-inward', methods=['GET', 'POST'])
@login_required
def add_inward_to_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin and not current_user.is_data_entry:
        if case.assignee_id != current_user.id:
            abort(403)

    form = AddLetterForm()
    if form.validate_on_submit():
        hash_val = Letter.generate_hash(form.from_address.data, form.to_address.data, form.subject.data)
        assignee_id = None
        if form.assignee_id.data and form.assignee_id.data > 0:
            assignee_id = form.assignee_id.data
        elif case.assignee_id:
            assignee_id = case.assignee_id

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
            section=case.section,
            case_id=case.id,
            priority=form.priority.data or None,
            status='Assigned' if assignee_id else 'Unassigned',
            assignee_id=assignee_id,
            assigned_by_id=current_user.id if assignee_id else None,
            assignment_date=_utcnow() if assignee_id else None,
            deadline_date=deadline_date,
            created_by_id=current_user.id,
        )

        db.session.add(letter)
        db.session.flush()

        db.session.add(ActivityLog(
            letter_id=letter.id, actor_id=current_user.id,
            action='Created', details=f'Inward letter created for case {case.reference_number}.'
        ))
        db.session.add(CaseActivityLog(
            case_id=case.id, actor_id=current_user.id,
            action='Inward Letter Added',
            details=f'Inward letter #{letter.id} added.'
        ))

        # If case in Awaiting Response, resume
        if _is_awaiting_response(case.status):
            case.resume_deadline()
            old_status = case.status
            case.status = 'Under Investigation'
            db.session.add(StatusHistory(
                case_id=case.id, old_status=old_status,
                new_status='Under Investigation',
                changed_by_id=current_user.id,
                reason='Inward letter received, resuming investigation.'
            ))

        db.session.commit()
        flash('Inward letter added to case.', 'success')
        return redirect(url_for('cases.case_detail', case_id=case.id))

    return render_template('cases/add_inward.html', form=form, case=case)


# ---------------------------------------------------------------------------
# Add Outward to Case
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/add-outward', methods=['GET', 'POST'])
@login_required
def add_outward_to_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin and not current_user.is_data_entry:
        if case.assignee_id != current_user.id:
            abort(403)

    form = AddOutwardLetterForm(case_preset=case)
    if form.validate_on_submit():
        letter = Letter(
            from_address=form.from_address.data,
            sender_name=form.sender_name.data or None,
            to_address=form.to_address.data,
            subject=form.subject.data,
            received_date=form.sent_date.data if form.sent_date.data else None,
            direction='Outward',
            section=case.section,
            case_id=case.id,
            status='Outward',
            deadline_date=(_utcnow() + timedelta(days=form.deadline_days.data)) if form.deadline_days.data else None,
            created_by_id=current_user.id,
        )
        letter.unique_hash = Letter.generate_hash(
            letter.from_address, letter.to_address, letter.subject
        )

        db.session.add(letter)
        db.session.flush()

        db.session.add(ActivityLog(
            letter_id=letter.id, actor_id=current_user.id,
            action='Created', details=f'Outward letter created for case {case.reference_number}.'
        ))
        db.session.add(CaseActivityLog(
            case_id=case.id, actor_id=current_user.id,
            action='Outward Letter Added',
            details=f'Outward letter #{letter.id} added.'
        ))

        if form.mark_awaiting.data and not _is_awaiting_response(case.status):
            old_status = case.status
            case.status = 'Awaiting Response'
            case.pause_deadline()
            db.session.add(StatusHistory(
                case_id=case.id, old_status=old_status,
                new_status='Awaiting Response',
                changed_by_id=current_user.id,
                reason='Outward letter sent, marking awaiting response.'
            ))

        db.session.commit()
        flash('Outward letter added to case.', 'success')
        return redirect(url_for('cases.case_detail', case_id=case.id))

    return render_template('cases/add_outward.html', form=form, case=case)


# ---------------------------------------------------------------------------
# Case Comments
# ---------------------------------------------------------------------------
@bp.route('/<int:case_id>/comment', methods=['POST'])
@login_required
def add_case_comment(case_id):
    case = Case.query.get_or_404(case_id)
    if not current_user.is_admin and not current_user.is_data_entry:
        if case.assignee_id != current_user.id:
            abort(403)

    content = request.form.get('content', '').strip()
    if not content:
        flash('Comment cannot be empty.', 'warning')
        return redirect(url_for('cases.case_detail', case_id=case_id))

    comment = Comment(case_id=case.id, user_id=current_user.id, content=content)
    db.session.add(comment)

    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Comment Added', details=f'Comment: {content[:100]}'
    ))

    if case.assignee_id and case.assignee_id != current_user.id:
        db.session.add(Notification(
            user_id=case.assignee_id,
            message=f'{current_user.full_name or current_user.username} commented on case {case.reference_number}.',
            notification_type='case_comment'
        ))
    if not current_user.is_admin:
        admins = User.query.filter_by(role='admin', is_active_user=True).all()
        for admin in admins:
            if admin.id != current_user.id:
                db.session.add(Notification(
                    user_id=admin.id,
                    message=f'{current_user.full_name or current_user.username} commented on case {case.reference_number}.',
                    notification_type='case_comment'
                ))

    db.session.commit()
    flash('Comment added.', 'success')
    return redirect(url_for('cases.case_detail', case_id=case_id))


@bp.route('/<int:case_id>/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_case_comment(case_id, comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    content = request.form.get('content', '').strip()
    if content:
        comment.content = content
        db.session.commit()
        flash('Comment updated.', 'success')

    return redirect(url_for('cases.case_detail', case_id=case_id))


@bp.route('/<int:case_id>/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_case_comment(case_id, comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'info')
    return redirect(url_for('cases.case_detail', case_id=case_id))
