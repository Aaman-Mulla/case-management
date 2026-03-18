from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.main import bp
from app.models import (
    Letter, User, Notification, ActivityLog, Comment,
    StatusHistory, _utcnow, db
)
from app.utils.queries import get_distinct_senders


@bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        elif current_user.is_data_entry:
            return redirect(url_for('data_entry.dashboard'))
        else:
            return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/dashboard')
@login_required
def dashboard():
    query = Letter.query.filter_by(assignee_id=current_user.id)

    # Filters
    status = request.args.get('status', '').strip()
    priority = request.args.get('priority', '').strip()
    sender_name = request.args.get('sender_name', '').strip()
    q = request.args.get('q', '').strip()

    active_filters = {}
    if status:
        query = query.filter(Letter.status == status)
        active_filters['status'] = status
    if priority:
        query = query.filter(Letter.priority == priority)
        active_filters['priority'] = priority
    if sender_name:
        query = query.filter(Letter.sender_name == sender_name)
        active_filters['sender_name'] = sender_name
    if q:
        search = f'%{q}%'
        query = query.filter(db.or_(
            Letter.from_address.ilike(search),
            Letter.to_address.ilike(search),
            Letter.subject.ilike(search)
        ))
        active_filters['q'] = q

    letters = query.order_by(Letter.id.asc()).all()

    now = _utcnow()
    stats = {
        'total': len(letters),
        'resolved': sum(1 for l in letters if l.status in ('Resolved', 'Closed')),
        'overdue': sum(1 for l in letters if l.deadline_date and now > l.deadline_date and l.status not in ('Resolved', 'Closed', 'Outward')),
        'in_progress': sum(1 for l in letters if l.status in ('Assigned', 'In Progress')),
    }

    senders = get_distinct_senders()

    return render_template('main/dashboard.html',
                           letters=letters, stats=stats,
                           active_filters=active_filters,
                           senders=senders)


@bp.route('/letter/<int:id>')
@login_required
def letter_detail(id):
    letter = Letter.query.get_or_404(id)

    # Access control: regular users can only see their assigned letters
    if not current_user.is_admin and not current_user.is_data_entry:
        if letter.assignee_id != current_user.id:
            abort(403)

    comments = letter.comments.order_by(Comment.created_at.desc()).all()
    attachments = letter.attachments.all()
    activity_logs = letter.activity_logs.order_by(ActivityLog.timestamp.desc()).all()
    status_history = letter.status_history.order_by(StatusHistory.changed_at.desc()).all()

    return render_template('main/letter_detail.html',
                           letter=letter, comments=comments,
                           attachments=attachments,
                           activity_logs=activity_logs,
                           status_history=status_history)


@bp.route('/letter/<int:id>/update-status', methods=['POST'])
@login_required
def update_letter_status(id):
    letter = Letter.query.get_or_404(id)

    if not current_user.is_admin and not current_user.is_data_entry:
        if letter.assignee_id != current_user.id:
            abort(403)

    new_status = request.form.get('status')
    reason = request.form.get('reason', '').strip()

    valid_statuses = ['Assigned', 'In Progress', 'Resolved']
    if new_status not in valid_statuses:
        flash('Invalid status.', 'danger')
        return redirect(url_for('main.letter_detail', id=id))

    old_status = letter.status
    letter.status = new_status

    if new_status == 'Resolved':
        letter.resolution_date = _utcnow()
    elif old_status == 'Resolved' and new_status != 'Resolved':
        letter.resolution_date = None

    db.session.add(StatusHistory(
        letter_id=letter.id, old_status=old_status,
        new_status=new_status, changed_by_id=current_user.id,
        reason=reason or None
    ))
    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Status Changed',
        details=f'Status changed from {old_status} to {new_status}.'
    ))

    # Notify admin if changed by normal user
    if not current_user.is_admin:
        admins = User.query.filter_by(role='admin', is_active_user=True).all()
        for admin in admins:
            db.session.add(Notification(
                user_id=admin.id, letter_id=letter.id,
                message=f'Letter #{letter.id} status changed to {new_status} by {current_user.full_name or current_user.username}.',
                notification_type='status_change'
            ))

    db.session.commit()
    flash(f'Status updated to {new_status}.', 'success')
    return redirect(url_for('main.letter_detail', id=id))


@bp.route('/letter/<int:id>/comment', methods=['POST'])
@login_required
def add_letter_comment(id):
    letter = Letter.query.get_or_404(id)

    if not current_user.is_admin and not current_user.is_data_entry:
        if letter.assignee_id != current_user.id:
            abort(403)

    content = request.form.get('content', '').strip()
    if not content:
        flash('Comment cannot be empty.', 'warning')
        return redirect(url_for('main.letter_detail', id=id))

    comment = Comment(
        letter_id=letter.id,
        user_id=current_user.id,
        content=content
    )
    db.session.add(comment)

    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Comment Added', details=f'Comment: {content[:100]}'
    ))

    # Notify relevant users
    if letter.assignee_id and letter.assignee_id != current_user.id:
        db.session.add(Notification(
            user_id=letter.assignee_id, letter_id=letter.id,
            message=f'{current_user.full_name or current_user.username} commented on letter #{letter.id}.',
            notification_type='comment'
        ))
    if not current_user.is_admin:
        admins = User.query.filter_by(role='admin', is_active_user=True).all()
        for admin in admins:
            if admin.id != current_user.id:
                db.session.add(Notification(
                    user_id=admin.id, letter_id=letter.id,
                    message=f'{current_user.full_name or current_user.username} commented on letter #{letter.id}.',
                    notification_type='comment'
                ))

    db.session.commit()
    flash('Comment added.', 'success')
    return redirect(url_for('main.letter_detail', id=id))


@bp.route('/comment/<int:id>/edit', methods=['POST'])
@login_required
def edit_comment(id):
    comment = Comment.query.get_or_404(id)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    content = request.form.get('content', '').strip()
    if not content:
        flash('Comment cannot be empty.', 'warning')
    else:
        comment.content = content
        db.session.commit()
        flash('Comment updated.', 'success')

    if comment.letter_id:
        return redirect(url_for('main.letter_detail', id=comment.letter_id))
    return redirect(url_for('main.dashboard'))


@bp.route('/comment/<int:id>/delete', methods=['POST'])
@login_required
def delete_comment(id):
    comment = Comment.query.get_or_404(id)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    letter_id = comment.letter_id
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'info')

    if letter_id:
        return redirect(url_for('main.letter_detail', id=letter_id))
    return redirect(url_for('main.dashboard'))


@bp.route('/notifications/mark-read/<int:id>', methods=['POST'])
@login_required
def mark_notification_read(id):
    notification = Notification.query.get_or_404(id)
    if notification.user_id != current_user.id:
        abort(403)
    notification.is_read = True
    db.session.commit()
    return {'status': 'ok'}


@bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'info')
    return redirect(request.referrer or url_for('main.dashboard'))
