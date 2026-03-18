import os
import uuid
from io import BytesIO
from datetime import datetime, timedelta

from flask import request, jsonify, current_app, send_file
from flask_login import login_required, current_user

from app.api import bp
from app.models import (
    Letter, Case, User, Notification, Reminder, Attachment,
    ActivityLog, CaseActivityLog, Comment, StatusHistory,
    _utcnow, db
)
from app import csrf

# SEC-5: MIME type to allowed-extensions mapping for content validation
MIME_WHITELIST = {
    'application/pdf': {'pdf'},
    'image/jpeg': {'jpg', 'jpeg'},
    'image/png': {'png'},
}


def _validate_file_content(file_storage, ext):
    """SEC-5: Validate that file content MIME matches declared extension."""
    header = file_storage.read(16)
    file_storage.seek(0)

    # PDF: starts with %PDF
    if ext == 'pdf':
        if not header.startswith(b'%PDF'):
            return False
    # JPEG: starts with FF D8 FF
    elif ext in ('jpg', 'jpeg'):
        if not header.startswith(b'\xff\xd8\xff'):
            return False
    # PNG: starts with 89 50 4E 47
    elif ext == 'png':
        if not header.startswith(b'\x89PNG'):
            return False
    return True


# ---------------------------------------------------------------------------
# Letters
# ---------------------------------------------------------------------------
@bp.route('/letters')
@login_required
def get_letters():
    if current_user.is_admin or current_user.is_data_entry:
        letters = Letter.query.order_by(Letter.import_date.desc()).limit(500).all()
    else:
        letters = Letter.query.filter_by(assignee_id=current_user.id).order_by(Letter.import_date.desc()).all()

    return jsonify([{
        'id': l.id,
        'direction': l.direction,
        'from_address': l.from_address,
        'to_address': l.to_address,
        'subject': l.subject,
        'sender_name': l.sender_name,
        'status': l.effective_status,
        'priority': l.priority,
        'section': l.section,
        'received_date': l.received_date.isoformat() if l.received_date else None,
        'deadline_date': l.deadline_date.isoformat() if l.deadline_date else None,
        'assignee': l.assignee.full_name if l.assignee else None,
        'case_id': l.case_id,
    } for l in letters])


@bp.route('/letters/<int:id>')
@login_required
def get_letter(id):
    letter = Letter.query.get_or_404(id)
    if not current_user.is_admin and not current_user.is_data_entry:
        if letter.assignee_id != current_user.id:
            return jsonify({'error': 'Forbidden'}), 403

    return jsonify({
        'id': letter.id,
        'direction': letter.direction,
        'from_address': letter.from_address,
        'to_address': letter.to_address,
        'subject': letter.subject,
        'sender_name': letter.sender_name,
        'status': letter.effective_status,
        'priority': letter.priority,
        'section': letter.section,
        'received_date': letter.received_date.isoformat() if letter.received_date else None,
        'deadline_date': letter.deadline_date.isoformat() if letter.deadline_date else None,
        'assignee': letter.assignee.full_name if letter.assignee else None,
        'case_id': letter.case_id,
        'case_ref': letter.case.reference_number if letter.case else None,
    })


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@bp.route('/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).limit(20).all()

    return jsonify([{
        'id': n.id,
        'message': n.message,
        'type': n.notification_type,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat() if n.created_at else None,
        'letter_id': n.letter_id,
    } for n in notifications])


@bp.route('/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).count()
    return jsonify({'count': count})


@bp.route('/notifications/mark-read/<int:id>', methods=['POST'])
@login_required
def mark_notification_read(id):
    notification = Notification.query.get_or_404(id)
    if notification.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    notification.is_read = True
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@bp.route('/stats')
@login_required
def get_stats():
    from app.utils.queries import get_letter_stats
    if current_user.is_admin or current_user.is_data_entry:
        stats = get_letter_stats()
    else:
        stats = get_letter_stats(Letter.query.filter_by(assignee_id=current_user.id))
    return jsonify(stats)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
@bp.route('/letters/<int:id>/attachments', methods=['GET'])
@login_required
def get_letter_attachments(id):
    letter = Letter.query.get_or_404(id)
    attachments = letter.attachments.all()
    return jsonify([{
        'id': a.id,
        'filename': a.original_filename,
        'size': a.file_size_display,
        'content_type': a.content_type,
        'uploaded_at': a.uploaded_at.isoformat() if a.uploaded_at else None,
        'uploaded_by': a.uploaded_by.full_name if a.uploaded_by else None,
    } for a in attachments])


@bp.route('/letters/<int:id>/attachments', methods=['POST'])
@login_required
@csrf.exempt
def upload_letter_attachment(id):
    letter = Letter.query.get_or_404(id)
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in current_app.config.get('ALLOWED_EXTENSIONS', set()):
        return jsonify({'error': f'File type .{ext} not allowed. Allowed: PDF, JPG, PNG'}), 400

    # SEC-5: Validate file content matches declared extension
    if not _validate_file_content(file, ext):
        return jsonify({'error': 'File content does not match its extension. Upload rejected.'}), 400

    stored_name = f'{uuid.uuid4().hex}.{ext}'
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
    file.save(filepath)
    file_size = os.path.getsize(filepath)

    attachment = Attachment(
        letter_id=letter.id,
        case_id=letter.case_id,
        original_filename=file.filename,
        stored_filename=stored_name,
        content_type=file.content_type,
        file_size=file_size,
        uploaded_by_id=current_user.id,
    )
    db.session.add(attachment)
    db.session.add(ActivityLog(
        letter_id=letter.id, actor_id=current_user.id,
        action='Attachment Uploaded',
        details=f'File: {file.filename}'
    ))
    db.session.commit()

    return jsonify({
        'id': attachment.id,
        'filename': attachment.original_filename,
        'size': attachment.file_size_display,
    }), 201


@bp.route('/attachments/<int:id>/download')
@login_required
def download_attachment(id):
    attachment = Attachment.query.get_or_404(id)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.stored_filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, download_name=attachment.original_filename, as_attachment=True)


@bp.route('/attachments/<int:id>/delete', methods=['POST', 'DELETE'])
@login_required
@csrf.exempt
def delete_attachment(id):
    attachment = Attachment.query.get_or_404(id)
    if not current_user.is_admin and attachment.uploaded_by_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.stored_filename)
    try:
        os.remove(filepath)
    except OSError:
        pass

    if attachment.letter_id:
        db.session.add(ActivityLog(
            letter_id=attachment.letter_id, actor_id=current_user.id,
            action='Attachment Deleted',
            details=f'File: {attachment.original_filename}'
        ))

    db.session.delete(attachment)
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/cases/<int:id>/attachments', methods=['POST'])
@login_required
@csrf.exempt
def upload_case_attachment(id):
    case = Case.query.get_or_404(id)
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in current_app.config.get('ALLOWED_EXTENSIONS', set()):
        return jsonify({'error': f'File type .{ext} not allowed'}), 400

    # SEC-5: Validate file content matches declared extension
    if not _validate_file_content(file, ext):
        return jsonify({'error': 'File content does not match its extension. Upload rejected.'}), 400

    stored_name = f'{uuid.uuid4().hex}.{ext}'
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
    file.save(filepath)
    file_size = os.path.getsize(filepath)

    attachment = Attachment(
        case_id=case.id,
        original_filename=file.filename,
        stored_filename=stored_name,
        content_type=file.content_type,
        file_size=file_size,
        uploaded_by_id=current_user.id,
    )
    db.session.add(attachment)
    db.session.add(CaseActivityLog(
        case_id=case.id, actor_id=current_user.id,
        action='Attachment Uploaded',
        details=f'File: {file.filename}'
    ))
    db.session.commit()

    return jsonify({
        'id': attachment.id,
        'filename': attachment.original_filename,
        'size': attachment.file_size_display,
    }), 201


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
@bp.route('/reminders', methods=['POST'])
@login_required
@csrf.exempt
def create_reminder():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    remind_at_str = data.get('remind_at')
    if not remind_at_str:
        return jsonify({'error': 'remind_at is required'}), 400

    try:
        remind_at = datetime.fromisoformat(remind_at_str)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    reminder = Reminder(
        user_id=current_user.id,
        letter_id=data.get('letter_id'),
        case_id=data.get('case_id'),
        remind_at=remind_at,
        message=data.get('message', ''),
    )
    db.session.add(reminder)
    db.session.commit()

    return jsonify({'id': reminder.id, 'status': 'created'}), 201


@bp.route('/reminders', methods=['GET'])
@login_required
def get_reminders():
    reminders = Reminder.query.filter_by(user_id=current_user.id).order_by(Reminder.remind_at.desc()).all()
    return jsonify([{
        'id': r.id,
        'letter_id': r.letter_id,
        'case_id': r.case_id,
        'remind_at': r.remind_at.isoformat() if r.remind_at else None,
        'message': r.message,
        'is_triggered': r.is_triggered,
    } for r in reminders])


@bp.route('/reminders/<int:id>/dismiss', methods=['POST'])
@login_required
@csrf.exempt
def dismiss_reminder(id):
    reminder = Reminder.query.get_or_404(id)
    if reminder.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403
    reminder.is_triggered = True
    db.session.commit()
    return jsonify({'status': 'dismissed'})


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@bp.route('/analytics/letters')
@login_required
def analytics_letters():
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    def _parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None

    def _apply_filters(query, start_date, end_date, section, direction, status):
        if start_date:
            query = query.filter(Letter.import_date >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            query = query.filter(Letter.import_date < datetime.combine(end_date + timedelta(days=1), datetime.min.time()))
        if section:
            query = query.filter(Letter.section == section)
        if direction:
            query = query.filter(Letter.direction == direction)
        if status:
            query = query.filter(Letter.status == status)
        return query

    def _compute_snapshot(start_date, end_date, section, direction, status):
        resolved_statuses = ('Resolved', 'Closed')

        base_query = _apply_filters(Letter.query, start_date, end_date, section, direction, status)

        total = base_query.count()
        resolved_count = base_query.filter(Letter.status.in_(resolved_statuses)).count()
        open_count = max(total - resolved_count, 0)

        overdue_count = base_query.filter(
            Letter.deadline_date.isnot(None),
            Letter.deadline_date < _utcnow(),
            ~Letter.status.in_(('Resolved', 'Closed', 'Outward'))
        ).count()

        avg_turnaround_days = db.session.query(
            db.func.avg(db.func.julianday(Letter.resolution_date) - db.func.julianday(Letter.import_date))
        ).filter(
            Letter.resolution_date.isnot(None),
            Letter.import_date.isnot(None)
        )
        avg_turnaround_days = _apply_filters(avg_turnaround_days, start_date, end_date, section, direction, status).scalar()
        avg_turnaround_days = round(float(avg_turnaround_days or 0), 1)

        resolved_rate = round((resolved_count / total) * 100, 1) if total else 0
        sla_breach_rate = round((overdue_count / total) * 100, 1) if total else 0

        by_status_rows = base_query.with_entities(
            Letter.status, db.func.count(Letter.id)
        ).group_by(Letter.status).all()
        by_status = {row[0] or 'Unknown': row[1] for row in by_status_rows}

        by_priority_rows = base_query.with_entities(
            db.func.coalesce(Letter.priority, 'None'), db.func.count(Letter.id)
        ).group_by(Letter.priority).all()
        by_priority = {row[0]: row[1] for row in by_priority_rows}

        by_section_rows = base_query.with_entities(
            db.func.coalesce(Letter.section, 'Unclassified'), db.func.count(Letter.id)
        ).group_by(Letter.section).all()
        by_section = {row[0]: row[1] for row in by_section_rows}

        by_direction_rows = base_query.with_entities(
            db.func.coalesce(Letter.direction, 'Unknown'), db.func.count(Letter.id)
        ).group_by(Letter.direction).all()
        by_direction = {row[0]: row[1] for row in by_direction_rows}

        monthly_rows = base_query.with_entities(
            db.func.strftime('%Y-%m', Letter.import_date).label('month'),
            db.func.count(Letter.id)
        ).filter(
            Letter.import_date.isnot(None)
        ).group_by('month').order_by('month').all()
        monthly_trends = [{'month': row[0], 'count': row[1]} for row in monthly_rows if row[0]]

        return {
            'total': total,
            'open_count': open_count,
            'resolved_count': resolved_count,
            'overdue_count': overdue_count,
            'resolved_rate': resolved_rate,
            'sla_breach_rate': sla_breach_rate,
            'avg_turnaround_days': avg_turnaround_days,
            'by_status': by_status,
            'by_priority': by_priority,
            'by_section': by_section,
            'by_direction': by_direction,
            'monthly_trends': monthly_trends,
        }

    start_date = _parse_date((request.args.get('start_date') or '').strip())
    end_date = _parse_date((request.args.get('end_date') or '').strip())
    section = (request.args.get('section') or '').strip() or None
    direction = (request.args.get('direction') or '').strip() or None
    status = (request.args.get('status') or '').strip() or None

    snapshot = _compute_snapshot(start_date, end_date, section, direction, status)

    comparison = None
    if start_date and end_date and end_date >= start_date:
        days = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        previous = _compute_snapshot(prev_start, prev_end, section, direction, status)

        def _delta(current_value, previous_value):
            return round((current_value or 0) - (previous_value or 0), 1)

        comparison = {
            'current_start': start_date.isoformat(),
            'current_end': end_date.isoformat(),
            'previous_start': prev_start.isoformat(),
            'previous_end': prev_end.isoformat(),
            'delta': {
                'total': _delta(snapshot['total'], previous['total']),
                'resolved_rate': _delta(snapshot['resolved_rate'], previous['resolved_rate']),
                'sla_breach_rate': _delta(snapshot['sla_breach_rate'], previous['sla_breach_rate']),
                'avg_turnaround_days': _delta(snapshot['avg_turnaround_days'], previous['avg_turnaround_days']),
            }
        }

    available_sections = [r[0] for r in db.session.query(Letter.section).filter(Letter.section.isnot(None)).distinct().order_by(Letter.section).all()]
    available_statuses = [r[0] for r in db.session.query(Letter.status).filter(Letter.status.isnot(None)).distinct().order_by(Letter.status).all()]
    available_directions = [r[0] for r in db.session.query(Letter.direction).filter(Letter.direction.isnot(None)).distinct().order_by(Letter.direction).all()]

    return jsonify({
        **snapshot,
        'comparison': comparison,
        'filters': {
            'start_date': start_date.isoformat() if start_date else '',
            'end_date': end_date.isoformat() if end_date else '',
            'section': section or '',
            'direction': direction or '',
            'status': status or '',
        },
        'available_filters': {
            'sections': available_sections,
            'statuses': available_statuses,
            'directions': available_directions,
        }
    })


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------
@bp.route('/workload')
@login_required
def workload():
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    # PERF-5: Use single aggregation query instead of N+1 per-user queries
    letter_stats = db.session.query(
        User.id,
        User.username,
        User.full_name,
        db.func.count(Letter.id).label('total'),
        db.func.sum(db.case((Letter.status == 'Resolved', 1), else_=0)).label('resolved'),
        db.func.sum(db.case((Letter.status.in_(['Assigned', 'In Progress']), 1), else_=0)).label('in_progress'),
    ).outerjoin(Letter, Letter.assignee_id == User.id).filter(
        User.is_active_user == True,
        User.role == 'user'
    ).group_by(User.id).all()

    # Case counts in a single query
    case_stats = db.session.query(
        Case.assignee_id,
        db.func.count(Case.id).label('cases'),
    ).filter(Case.assignee_id.isnot(None)).group_by(Case.assignee_id).all()
    case_map = {row[0]: row[1] for row in case_stats}

    data = []
    for row in letter_stats:
        data.append({
            'user_id': row.id,
            'username': row.username,
            'full_name': row.full_name,
            'total': row.total or 0,
            'resolved': row.resolved or 0,
            'in_progress': row.in_progress or 0,
            'cases': case_map.get(row.id, 0),
        })

    return jsonify(data)


# ---------------------------------------------------------------------------
# Audit Exports
# ---------------------------------------------------------------------------
@bp.route('/letters/<int:id>/audit/excel')
@login_required
def letter_audit_excel(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403
    import pandas as pd
    letter = Letter.query.get_or_404(id)
    logs = letter.activity_logs.order_by(ActivityLog.timestamp.desc()).all()

    data = [{
        'Timestamp': log.timestamp,
        'Action': log.action,
        'Details': log.details,
        'Actor': log.actor.full_name if log.actor else 'System',
    } for log in logs]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name=f'letter_{id}_audit.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/letters/<int:id>/audit/pdf')
@login_required
def letter_audit_pdf(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    letter = Letter.query.get_or_404(id)
    logs = letter.activity_logs.order_by(ActivityLog.timestamp.desc()).all()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f'Audit Trail — Letter #{id}', styles['Title']))
    elements.append(Paragraph(f'Subject: {letter.subject}', styles['Normal']))
    elements.append(Spacer(1, 12))

    table_data = [['Timestamp', 'Action', 'Details', 'Actor']]
    for log in logs:
        table_data.append([
            log.timestamp.strftime('%Y-%m-%d %H:%M') if log.timestamp else '',
            log.action,
            (log.details or '')[:80],
            log.actor.full_name if log.actor else 'System',
        ])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    elements.append(table)

    doc.build(elements)
    output.seek(0)
    return send_file(output, download_name=f'letter_{id}_audit.pdf',
                     as_attachment=True, mimetype='application/pdf')


@bp.route('/cases/<int:id>/audit/excel')
@login_required
def case_audit_excel(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403
    import pandas as pd
    case = Case.query.get_or_404(id)
    logs = case.case_activity_logs.order_by(CaseActivityLog.timestamp.desc()).all()

    data = [{
        'Timestamp': log.timestamp,
        'Action': log.action,
        'Details': log.details,
        'Actor': log.actor.full_name if log.actor else 'System',
    } for log in logs]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name=f'case_{id}_audit.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/cases/<int:id>/audit/pdf')
@login_required
def case_audit_pdf(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    case = Case.query.get_or_404(id)
    logs = case.case_activity_logs.order_by(CaseActivityLog.timestamp.desc()).all()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f'Audit Trail — Case {case.reference_number}', styles['Title']))
    elements.append(Paragraph(f'Title: {case.title or ""}', styles['Normal']))
    elements.append(Spacer(1, 12))

    table_data = [['Timestamp', 'Action', 'Details', 'Actor']]
    for log in logs:
        table_data.append([
            log.timestamp.strftime('%Y-%m-%d %H:%M') if log.timestamp else '',
            log.action,
            (log.details or '')[:80],
            log.actor.full_name if log.actor else 'System',
        ])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    elements.append(table)

    doc.build(elements)
    output.seek(0)
    return send_file(output, download_name=f'case_{id}_audit.pdf',
                     as_attachment=True, mimetype='application/pdf')


# ---------------------------------------------------------------------------
# Bulk Case Actions
# ---------------------------------------------------------------------------
@bp.route('/cases/bulk-action', methods=['POST'])
@login_required
@csrf.exempt
def cases_bulk_action():
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    action = data.get('action')
    case_ids = data.get('case_ids', [])

    if not action or not case_ids:
        return jsonify({'error': 'Missing action or case_ids'}), 400

    cases = Case.query.filter(Case.id.in_(case_ids)).all()

    if action == 'delete':
        for case in cases:
            for letter in case.letters.all():
                letter.case_id = None
            db.session.delete(case)
        db.session.commit()
        return jsonify({'status': 'ok', 'deleted': len(cases), 'message': f'{len(cases)} case(s) deleted.'})

    elif action == 'assign':
        assignee_id = data.get('assignee_id')
        if not assignee_id:
            return jsonify({'error': 'Missing assignee_id'}), 400
        for case in cases:
            case.assignee_id = assignee_id
            case.assigned_by_id = current_user.id
        db.session.commit()
        return jsonify({'status': 'ok', 'assigned': len(cases), 'message': f'{len(cases)} case(s) assigned.'})

    return jsonify({'error': 'Unknown action'}), 400
