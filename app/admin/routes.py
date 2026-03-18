import os
from datetime import datetime, timedelta

from flask import (render_template, redirect, url_for, flash, request,
                   current_app, send_file)
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.admin import bp
from app.admin.forms import (
    AddLetterForm, EditLetterForm, AddOutwardLetterForm, AssignLetterForm,
    UploadExcelForm, CreateUserForm, EditUserForm, AssignCaseForm, LinkToCaseForm
)
from app.models import (
    Letter, User, Section, ActivityLog, Notification, Case,
    Comment, Attachment, StatusHistory, _utcnow, db
)
from app.utils.queries import build_letter_filter_query, get_letter_stats, get_distinct_senders
from app.utils.letter_ops import (
    build_inward_letter_from_form, build_outward_letter_from_form,
    perform_assign_letter, perform_unassign_letter,
)
from app.utils.decorators import role_required
from config import SLA_DAYS

admin_required = role_required('is_admin')


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route('/dashboard')
@admin_required
def dashboard():
    query = Letter.query
    query, active_filters = build_letter_filter_query(query)
    stats = get_letter_stats(query)
    letters = query.order_by(Letter.id.asc()).all()
    senders = get_distinct_senders()
    sections = Section.get_choices()
    users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()

    # SLA compliance
    sla_stats = _compute_sla_stats()

    return render_template('admin/dashboard.html',
                           letters=letters, stats=stats,
                           active_filters=active_filters,
                           senders=senders, sections=sections,
                           users=users, sla_stats=sla_stats)


def _compute_sla_stats():
    """Compute SLA compliance summary using SQL aggregation (PERF-2)."""
    now = _utcnow()
    result = {'compliant': 0, 'breached': 0, 'total': 0}

    # Get letters with valid priority and import_date (BUG-11: skip null import_date)
    letters_q = db.session.query(
        Letter.priority,
        Letter.status,
        Letter.import_date,
        Letter.resolution_date,
    ).filter(
        Letter.status.notin_(['Outward']),
        Letter.priority.isnot(None),
        Letter.import_date.isnot(None),
        Letter.priority.in_(list(SLA_DAYS.keys()))
    ).all()

    for priority, status, import_date, resolution_date in letters_q:
        sla = SLA_DAYS.get(priority)
        if not sla:
            continue
        result['total'] += 1
        if status in ('Resolved', 'Closed'):
            if resolution_date and import_date:
                days_taken = (resolution_date - import_date).days
                if days_taken <= sla:
                    result['compliant'] += 1
                else:
                    result['breached'] += 1
            else:
                result['compliant'] += 1
        else:
            days_elapsed = (now - import_date).days
            if days_elapsed > sla:
                result['breached'] += 1
            else:
                result['compliant'] += 1
    return result


# ---------------------------------------------------------------------------
# Add inward letter
# ---------------------------------------------------------------------------
@bp.route('/add-inward-letter', methods=['GET', 'POST'])
@admin_required
def add_inward_letter():
    form = AddLetterForm()
    if form.validate_on_submit():
        hash_val = Letter.generate_hash(form.from_address.data, form.to_address.data, form.subject.data)
        if Letter.query.filter_by(unique_hash=hash_val).first():
            flash('A letter with the same From, To, and Subject already exists.', 'warning')
            return render_template('admin/add_inward_letter.html', form=form)

        build_inward_letter_from_form(form, actor_label='ROC')
        db.session.commit()
        flash('Inward letter added successfully.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/add_inward_letter.html', form=form)


# ---------------------------------------------------------------------------
# Add outward letter
# ---------------------------------------------------------------------------
@bp.route('/add-outward-letter', methods=['GET', 'POST'])
@admin_required
def add_outward_letter():
    form = AddOutwardLetterForm()
    if form.validate_on_submit():
        build_outward_letter_from_form(form, actor_label='ROC')
        db.session.commit()
        flash('Outward letter added successfully.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/add_outward_letter.html', form=form)


# ---------------------------------------------------------------------------
# Edit letter
# ---------------------------------------------------------------------------
@bp.route('/edit-letter/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_letter(id):
    letter = Letter.query.get_or_404(id)
    form = EditLetterForm(obj=letter)
    if form.validate_on_submit():
        changes = []
        if letter.from_address != form.from_address.data:
            changes.append('from_address')
        if letter.subject != form.subject.data:
            changes.append('subject')

        letter.from_address = form.from_address.data
        letter.sender_name = form.sender_name.data or None
        letter.to_address = form.to_address.data
        letter.subject = form.subject.data
        letter.received_date = form.received_date.data if form.received_date.data else letter.received_date
        letter.section = form.section.data or letter.section
        letter.priority = form.priority.data or letter.priority
        if letter.assignee_id and letter.deadline_date is None and form.deadline_days.data:
            letter.deadline_date = _utcnow() + timedelta(days=form.deadline_days.data)
            changes.append('deadline_date')

        # Update hash
        letter.unique_hash = Letter.generate_hash(letter.from_address, letter.to_address, letter.subject)

        db.session.add(ActivityLog(
            letter_id=letter.id, actor_id=current_user.id,
            action='Edited', details=f'Fields updated: {", ".join(changes) if changes else "metadata"}'
        ))
        db.session.commit()
        flash('Letter updated successfully.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/edit_letter.html', form=form, letter=letter)


# ---------------------------------------------------------------------------
# Export letters
# ---------------------------------------------------------------------------
@bp.route('/export')
@admin_required
def export_letters():
    import pandas as pd
    from io import BytesIO

    query, _ = build_letter_filter_query()
    letters = query.order_by(Letter.import_date.desc()).all()

    data = []
    for l in letters:
        data.append({
            'ID': l.id,
            'Direction': l.direction,
            'From': l.from_address,
            'Sender': l.sender_name,
            'To': l.to_address,
            'Subject': l.subject,
            'Section': l.section,
            'Status': l.effective_status,
            'Priority': l.priority,
            'Received Date': l.received_date,
            'Import Date': l.import_date,
            'Deadline': l.deadline_date,
            'Assignee': l.assignee.full_name if l.assignee else '',
        })

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='letters_export.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------------------------------------------------------------------
# Upload / Import
# ---------------------------------------------------------------------------
@bp.route('/upload', methods=['GET', 'POST'])
@admin_required
def upload():
    form = UploadExcelForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        from app.utils.excel_parser import parse_import_file
        result = parse_import_file(filepath, created_by_id=current_user.id)

        # Clean up uploaded file
        try:
            os.remove(filepath)
        except OSError:
            pass

        flash(f'Import complete: {result["imported"]} imported, '
              f'{result["skipped"]} skipped, {len(result["errors"])} errors.', 'info')
        for err in result['errors'][:10]:
            flash(err, 'warning')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/upload.html', form=form)


# ---------------------------------------------------------------------------
# Assign / Unassign
# ---------------------------------------------------------------------------
@bp.route('/assign/<int:id>', methods=['GET', 'POST'])
@admin_required
def assign_letter(id):
    letter = Letter.query.get_or_404(id)
    form = AssignLetterForm()
    if form.validate_on_submit():
        user_id = form.assignee_id.data
        if user_id and user_id > 0:
            perform_assign_letter(letter, user_id, form.deadline_days.data, actor_label='ROC')
            db.session.commit()
            flash('Letter assigned successfully.', 'success')
            return redirect(url_for('admin.dashboard'))

    return render_template('admin/assign_letter.html', form=form, letter=letter)


@bp.route('/unassign/<int:id>', methods=['POST'])
@admin_required
def unassign_letter(id):
    letter = Letter.query.get_or_404(id)
    perform_unassign_letter(letter, actor_label='ROC')
    db.session.commit()
    flash('Letter unassigned.', 'info')
    return redirect(url_for('admin.dashboard'))


# ---------------------------------------------------------------------------
# Delete letter
# ---------------------------------------------------------------------------
@bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete_letter(id):
    letter = Letter.query.get_or_404(id)
    db.session.delete(letter)
    db.session.commit()
    flash('Letter deleted.', 'info')
    return redirect(url_for('admin.dashboard'))


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------
@bp.route('/bulk-action', methods=['POST'])
@admin_required
def bulk_action():
    action = request.form.get('action')
    letter_ids = request.form.getlist('letter_ids')

    if not action or not letter_ids:
        flash('No action or letters selected.', 'warning')
        return redirect(url_for('admin.dashboard'))

    letters = Letter.query.filter(Letter.id.in_(letter_ids)).all()

    if action == 'delete':
        for letter in letters:
            db.session.delete(letter)
        db.session.commit()
        flash(f'{len(letters)} letter(s) deleted.', 'info')

    elif action == 'assign':
        assignee_id = request.form.get('bulk_assignee_id')
        if assignee_id:
            assignee_id = int(assignee_id)
            for letter in letters:
                letter.assignee_id = assignee_id
                letter.assigned_by_id = current_user.id
                letter.assignment_date = _utcnow()
                if letter.status == 'Unassigned':
                    letter.status = 'Assigned'
                db.session.add(Notification(
                    user_id=assignee_id, letter_id=letter.id,
                    message=f'You have been assigned letter: "{letter.subject[:50]}".',
                    notification_type='assignment'
                ))
            db.session.commit()
            flash(f'{len(letters)} letter(s) assigned.', 'success')

    elif action == 'unassign':
        for letter in letters:
            letter.assignee_id = None
            letter.assigned_by_id = None
            letter.assignment_date = None
            letter.status = 'Unassigned'
        db.session.commit()
        flash(f'{len(letters)} letter(s) unassigned.', 'info')

    redirect_to = request.form.get('redirect_to')
    if redirect_to == 'inward_registry':
        return redirect(url_for('admin.inward_registry'))
    elif redirect_to == 'outward_registry':
        return redirect(url_for('admin.outward_registry'))
    return redirect(url_for('admin.dashboard'))


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------
@bp.route('/users')
@admin_required
def manage_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/manage_users.html', users=users)


@bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already exists.', 'danger')
            return render_template('admin/create_user.html', form=form)
        user = User(
            username=form.username.data,
            email=form.email.data or None,
            full_name=form.full_name.data or None,
            role=form.role.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'User "{user.username}" created successfully.', 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/create_user.html', form=form)


@bp.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    form = EditUserForm(obj=user)
    if form.validate_on_submit():
        user.email = form.email.data or None
        user.full_name = form.full_name.data or None
        user.role = form.role.data
        if form.new_password.data:
            user.set_password(form.new_password.data)
        db.session.commit()
        flash(f'User "{user.username}" updated.', 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/edit_user.html', form=form, user=user)


@bp.route('/users/toggle/<int:id>', methods=['POST'])
@admin_required
def toggle_user(id):
    user = User.query.get_or_404(id)
    user.is_active_user = not user.is_active_user
    db.session.commit()
    status = 'activated' if user.is_active_user else 'deactivated'
    flash(f'User "{user.username}" {status}.', 'info')
    return redirect(url_for('admin.manage_users'))


@bp.route('/users/delete/<int:id>', methods=['POST'])
@admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.manage_users'))
    # Unassign letters and cases
    Letter.query.filter_by(assignee_id=user.id).update({'assignee_id': None, 'status': 'Unassigned'})
    Case.query.filter_by(assignee_id=user.id).update({'assignee_id': None})
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'info')
    return redirect(url_for('admin.manage_users'))


@bp.route('/users/bulk-action', methods=['POST'])
@admin_required
def bulk_user_action():
    action = request.form.get('action')
    user_ids = request.form.getlist('user_ids')

    if not action or not user_ids:
        flash('No action or users selected.', 'warning')
        return redirect(url_for('admin.manage_users'))

    users = User.query.filter(User.id.in_(user_ids)).all()
    # Never modify current user via bulk
    users = [u for u in users if u.id != current_user.id]

    if action == 'activate':
        for u in users:
            u.is_active_user = True
        db.session.commit()
        flash(f'{len(users)} user(s) activated.', 'success')

    elif action == 'deactivate':
        for u in users:
            u.is_active_user = False
        db.session.commit()
        flash(f'{len(users)} user(s) deactivated.', 'info')

    elif action == 'delete':
        count = 0
        for u in users:
            Letter.query.filter_by(assignee_id=u.id).update(
                {'assignee_id': None, 'status': 'Unassigned'})
            Case.query.filter_by(assignee_id=u.id).update(
                {'assignee_id': None})
            db.session.delete(u)
            count += 1
        db.session.commit()
        flash(f'{count} user(s) deleted.', 'info')

    return redirect(url_for('admin.manage_users'))


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@bp.route('/analytics')
@admin_required
def analytics():
    return render_template('admin/analytics.html')


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------
@bp.route('/workload')
@admin_required
def workload():
    search_q = (request.args.get('q') or '').strip().lower()
    sort_by = (request.args.get('sort') or 'overdue').strip().lower()
    valid_sorts = {'overdue', 'in_progress', 'total', 'resolved', 'cases', 'name'}
    if sort_by not in valid_sorts:
        sort_by = 'overdue'

    # PERF-5: Use SQL aggregation instead of N+1 per-user queries
    letter_stats = db.session.query(
        User.id,
        User.username,
        User.full_name,
        db.func.count(Letter.id).label('total'),
        db.func.sum(db.case((Letter.status == 'Resolved', 1), else_=0)).label('resolved'),
        db.func.sum(db.case((Letter.status.in_(['Assigned', 'In Progress']), 1), else_=0)).label('in_progress'),
        db.func.sum(db.case((
            db.and_(
                Letter.deadline_date < _utcnow(),
                ~Letter.status.in_(['Resolved', 'Closed', 'Outward'])
            ), 1), else_=0)).label('overdue'),
    ).outerjoin(Letter, Letter.assignee_id == User.id).filter(
        User.is_active_user == True,
        User.role == 'user'
    ).group_by(User.id).all()

    case_counts = db.session.query(
        Case.assignee_id,
        db.func.count(Case.id).label('cases'),
    ).filter(Case.assignee_id.isnot(None)).group_by(Case.assignee_id).all()
    case_map = {row[0]: row[1] for row in case_counts}

    workload_data = []
    for row in letter_stats:
        display_name = (row.full_name or '').strip() or (row.username or '').strip() or f'User #{row.id}'
        username = (row.username or '').strip()
        if search_q and search_q not in display_name.lower() and search_q not in username.lower():
            continue
        workload_data.append({
            'user_id': row.id,
            'display_name': display_name,
            'username': username,
            'total': row.total or 0,
            'resolved': row.resolved or 0,
            'in_progress': row.in_progress or 0,
            'overdue': row.overdue or 0,
            'cases': case_map.get(row.id, 0),
        })

    if sort_by == 'name':
        workload_data.sort(key=lambda item: item['display_name'].lower())
    else:
        workload_data.sort(key=lambda item: item.get(sort_by, 0), reverse=True)

    summary = {
        'users': len(workload_data),
        'total': sum(item['total'] for item in workload_data),
        'in_progress': sum(item['in_progress'] for item in workload_data),
        'overdue': sum(item['overdue'] for item in workload_data),
    }

    return render_template(
        'admin/workload.html',
        workload_data=workload_data,
        summary=summary,
        search_q=search_q,
        sort_by=sort_by,
    )


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------
def _parse_registry_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _resolve_registry_date_bounds():
    start_raw = (request.args.get('start_date') or request.args.get('date_from') or '').strip()
    end_raw = (request.args.get('end_date') or request.args.get('date_to') or '').strip()
    range_key = (request.args.get('range') or '').strip().lower()

    start_date = _parse_registry_date(start_raw)
    end_date = _parse_registry_date(end_raw)

    today = _utcnow().date()
    if range_key == 'today':
        start_date = today
        end_date = today
    elif range_key == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif range_key == 'month':
        start_date = today.replace(day=1)
        end_date = today

    return start_date, end_date


def _apply_registry_date_filters(query, start_date, end_date):
    # Use import_date for filtering—this reflects when the letter was added to the system
    # which is what quick-range filters (today/week/month) should show
    date_expr = Letter.import_date
    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time())
        query = query.filter(date_expr >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        query = query.filter(date_expr < end_dt)
    return query


@bp.route('/inward-registry')
@admin_required
def inward_registry():
    query = Letter.query.filter_by(direction='Inward')
    start_date, end_date = _resolve_registry_date_bounds()
    query = _apply_registry_date_filters(query, start_date, end_date)
    section = (request.args.get('section') or '').strip()
    status = (request.args.get('status') or '').strip()
    if section:
        query = query.filter(Letter.section == section)
    if status:
        query = query.filter(Letter.status == status)

    letters = query.order_by(db.func.coalesce(Letter.received_date, Letter.import_date).desc()).all()

    # Section counts
    section_counts = {}
    for letter in letters:
        sec = letter.section or 'Unclassified'
        section_counts[sec] = section_counts.get(sec, 0) + 1

    return render_template('admin/inward_registry.html',
                           letters=letters, section_counts=section_counts,
                           start_date=start_date.isoformat() if start_date else '',
                           end_date=end_date.isoformat() if end_date else '')


@bp.route('/inward-registry/export')
@admin_required
def export_inward_registry():
    import pandas as pd
    from io import BytesIO

    query = Letter.query.filter_by(direction='Inward')
    start_date, end_date = _resolve_registry_date_bounds()
    query = _apply_registry_date_filters(query, start_date, end_date)
    section = (request.args.get('section') or '').strip()
    status = (request.args.get('status') or '').strip()
    if section:
        query = query.filter(Letter.section == section)
    if status:
        query = query.filter(Letter.status == status)

    letters = query.order_by(db.func.coalesce(Letter.received_date, Letter.import_date).desc()).all()
    data = [{
        'ID': l.id, 'From': l.from_address, 'Sender': l.sender_name,
        'To': l.to_address, 'Subject': l.subject, 'Section': l.section,
        'Status': l.effective_status, 'Priority': l.priority,
        'Date Received': l.received_date, 'Assignee': l.assignee.full_name if l.assignee else ''
    } for l in letters]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='inward_registry.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/outward-registry')
@admin_required
def outward_registry():
    query = Letter.query.filter_by(direction='Outward')
    start_date, end_date = _resolve_registry_date_bounds()
    query = _apply_registry_date_filters(query, start_date, end_date)
    section = (request.args.get('section') or '').strip()
    status = (request.args.get('status') or '').strip()
    if section:
        query = query.filter(Letter.section == section)
    if status:
        query = query.filter(Letter.status == status)

    letters = query.order_by(db.func.coalesce(Letter.received_date, Letter.import_date).desc()).all()

    section_counts = {}
    for letter in letters:
        sec = letter.section or 'Unclassified'
        section_counts[sec] = section_counts.get(sec, 0) + 1

    return render_template('admin/outward_registry.html',
                           letters=letters, section_counts=section_counts,
                           start_date=start_date.isoformat() if start_date else '',
                           end_date=end_date.isoformat() if end_date else '')


@bp.route('/outward-registry/export')
@admin_required
def export_outward_registry():
    import pandas as pd
    from io import BytesIO

    query = Letter.query.filter_by(direction='Outward')
    start_date, end_date = _resolve_registry_date_bounds()
    query = _apply_registry_date_filters(query, start_date, end_date)
    section = (request.args.get('section') or '').strip()
    status = (request.args.get('status') or '').strip()
    if section:
        query = query.filter(Letter.section == section)
    if status:
        query = query.filter(Letter.status == status)

    letters = query.order_by(db.func.coalesce(Letter.received_date, Letter.import_date).desc()).all()
    data = [{
        'ID': l.id, 'From': l.from_address, 'Sender': l.sender_name,
        'To': l.to_address, 'Subject': l.subject, 'Section': l.section,
        'Date Sent': l.received_date
    } for l in letters]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='outward_registry.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------------------------------------------------------------------
# Section management
# ---------------------------------------------------------------------------
@bp.route('/sections')
@admin_required
def manage_sections():
    # Cleanup legacy liquidation code so old entry is removed from section management
    Letter.query.filter_by(section='LIGDN').update({'section': 'LIQDN'})
    Case.query.filter_by(section='LIGDN').update({'section': 'LIQDN'})
    Section.query.filter_by(code='LIGDN').delete(synchronize_session='fetch')
    db.session.commit()

    # Handle column sorting
    sort_by = (request.args.get('sort_by') or '').lower()
    sort_order = (request.args.get('sort_order') or 'asc').lower()
    
    # Valid sortable columns
    sortable_columns = {
        'order': Section.display_order,
        'code': Section.code,
        'name': Section.name,
        'status': Section.is_active,
    }
    
    # Default sort
    if sort_by not in sortable_columns:
        sort_by = 'code'
        sort_order = 'asc'
    
    # Build query with sorting
    query = Section.query
    sort_column = sortable_columns[sort_by]
    
    if sort_order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    sections = query.all()
    
    return render_template('admin/manage_sections.html',
                          sections=sections,
                          sort_by=sort_by,
                          sort_order=sort_order)


@bp.route('/sections/add', methods=['POST'])
@admin_required
def add_section():
    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    if not code or not name:
        flash('Code and name are required.', 'danger')
        return redirect(url_for('admin.manage_sections'))
    if Section.query.filter_by(code=code).first():
        flash('Section code already exists.', 'warning')
        return redirect(url_for('admin.manage_sections'))
    max_order = db.session.query(db.func.max(Section.display_order)).scalar() or 0
    section = Section(code=code, name=name, display_order=max_order + 1)
    db.session.add(section)
    db.session.commit()
    flash(f'Section "{code}" added.', 'success')
    return redirect(url_for('admin.manage_sections'))


@bp.route('/sections/<int:id>/edit', methods=['POST'])
@admin_required
def edit_section(id):
    section = Section.query.get_or_404(id)
    new_code = request.form.get('code', '').strip().upper()
    new_name = request.form.get('name', '').strip()

    if not new_name:
        flash('Section name is required.', 'danger')
        return redirect(url_for('admin.manage_sections'))

    # Update code if changed (with validation)
    if new_code and new_code != section.code:
        existing = Section.query.filter_by(code=new_code).first()
        if existing:
            flash(f'Section code "{new_code}" already exists.', 'warning')
            return redirect(url_for('admin.manage_sections'))
        # Update references in letters and cases
        Letter.query.filter_by(section=section.code).update({'section': new_code})
        Case.query.filter_by(section=section.code).update({'section': new_code})
        section.code = new_code

    section.name = new_name
    section.description = request.form.get('description', '').strip() or None
    db.session.commit()
    flash('Section updated.', 'success')
    return redirect(url_for('admin.manage_sections'))


@bp.route('/sections/<int:id>/toggle', methods=['POST'])
@admin_required
def toggle_section(id):
    section = Section.query.get_or_404(id)
    section.is_active = not section.is_active
    db.session.commit()
    flash(f'Section "{section.code}" {"activated" if section.is_active else "deactivated"}.', 'info')
    return redirect(url_for('admin.manage_sections'))


@bp.route('/sections/reorder', methods=['POST'])
@admin_required
def reorder_sections():
    order = request.json.get('order', [])
    for idx, section_id in enumerate(order):
        section = db.session.get(Section, int(section_id))
        if section:
            section.display_order = idx
    db.session.commit()
    return {'status': 'ok'}


@bp.route('/sections/<int:id>/delete', methods=['POST'])
@admin_required
def delete_section(id):
    section = Section.query.get_or_404(id)
    # Check in use
    letter_count = Letter.query.filter_by(section=section.code).count()
    case_count = Case.query.filter_by(section=section.code).count()
    if letter_count > 0 or case_count > 0:
        flash(f'Cannot delete section "{section.code}" — it is in use by {letter_count} letter(s) and {case_count} case(s).', 'danger')
        return redirect(url_for('admin.manage_sections'))
    db.session.delete(section)
    db.session.commit()
    flash(f'Section "{section.code}" deleted.', 'info')
    return redirect(url_for('admin.manage_sections'))


@bp.route('/sections/bulk-action', methods=['POST'])
@admin_required
def bulk_section_action():
    action = request.form.get('action')
    section_ids = request.form.getlist('section_ids')

    if not action or not section_ids:
        flash('No action or sections selected.', 'warning')
        return redirect(url_for('admin.manage_sections'))

    sections = Section.query.filter(Section.id.in_(section_ids)).all()

    if action == 'activate':
        for s in sections:
            s.is_active = True
        db.session.commit()
        flash(f'{len(sections)} section(s) activated.', 'success')

    elif action == 'deactivate':
        for s in sections:
            s.is_active = False
        db.session.commit()
        flash(f'{len(sections)} section(s) deactivated.', 'info')

    elif action == 'delete':
        deleted = 0
        blocked = 0
        for s in sections:
            letter_count = Letter.query.filter_by(section=s.code).count()
            case_count = Case.query.filter_by(section=s.code).count()
            if letter_count > 0 or case_count > 0:
                blocked += 1
                continue
            db.session.delete(s)
            deleted += 1
        db.session.commit()
        msg = f'{deleted} section(s) deleted.'
        if blocked:
            msg += f' {blocked} skipped (in use).'
        flash(msg, 'info')

    return redirect(url_for('admin.manage_sections'))


# ---------------------------------------------------------------------------
# Unlink letter from case (admin route - redirects to cases unlink)
# ---------------------------------------------------------------------------
@bp.route('/unlink-letter/<int:id>', methods=['POST'])
@admin_required
def unlink_letter(id):
    return redirect(url_for('cases.unlink_letter', letter_id=id), code=307)
