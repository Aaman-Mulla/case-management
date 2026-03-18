import os
from datetime import timedelta

from flask import (render_template, redirect, url_for, flash, request,
                   current_app, send_file)
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.data_entry import bp
from app.admin.forms import (
    AddLetterForm, EditLetterForm, AddOutwardLetterForm,
    AssignLetterForm, UploadExcelForm
)
from app.models import (
    Letter, User, Section, ActivityLog, Notification,
    _utcnow, db
)
from app.utils.queries import build_letter_filter_query, get_letter_stats, get_distinct_senders
from app.utils.letter_ops import (
    build_inward_letter_from_form, build_outward_letter_from_form,
    perform_assign_letter, perform_unassign_letter,
)
from app.utils.decorators import role_required

data_entry_required = role_required('is_data_entry')


@bp.route('/dashboard')
@data_entry_required
def dashboard():
    query = Letter.query
    query, active_filters = build_letter_filter_query(query)
    stats = get_letter_stats(query)
    letters = query.order_by(Letter.id.asc()).all()
    senders = get_distinct_senders()
    sections = Section.get_choices()
    users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()

    return render_template('data_entry/dashboard.html',
                           letters=letters, stats=stats,
                           active_filters=active_filters,
                           senders=senders, sections=sections,
                           users=users)


@bp.route('/add-inward-letter', methods=['GET', 'POST'])
@data_entry_required
def add_inward_letter():
    form = AddLetterForm()
    if form.validate_on_submit():
        hash_val = Letter.generate_hash(form.from_address.data, form.to_address.data, form.subject.data)
        if Letter.query.filter_by(unique_hash=hash_val).first():
            flash('A letter with the same From, To, and Subject already exists.', 'warning')
            return render_template('data_entry/add_inward_letter.html', form=form)

        build_inward_letter_from_form(form, actor_label='Data Entry')
        db.session.commit()
        flash('Inward letter added successfully.', 'success')
        return redirect(url_for('data_entry.dashboard'))

    return render_template('data_entry/add_inward_letter.html', form=form)


@bp.route('/add-outward-letter', methods=['GET', 'POST'])
@data_entry_required
def add_outward_letter():
    form = AddOutwardLetterForm()
    if form.validate_on_submit():
        build_outward_letter_from_form(form, actor_label='Data Entry')
        db.session.commit()
        flash('Outward letter added successfully.', 'success')
        return redirect(url_for('data_entry.dashboard'))

    return render_template('data_entry/add_outward_letter.html', form=form)


@bp.route('/edit-letter/<int:id>', methods=['GET', 'POST'])
@data_entry_required
def edit_letter(id):
    letter = Letter.query.get_or_404(id)
    form = EditLetterForm(obj=letter)
    if form.validate_on_submit():
        letter.from_address = form.from_address.data
        letter.sender_name = form.sender_name.data or None
        letter.to_address = form.to_address.data
        letter.subject = form.subject.data
        letter.received_date = form.received_date.data if form.received_date.data else letter.received_date
        letter.section = form.section.data or letter.section
        letter.priority = form.priority.data or letter.priority
        if letter.assignee_id and letter.deadline_date is None and form.deadline_days.data:
            letter.deadline_date = _utcnow() + timedelta(days=form.deadline_days.data)
        letter.unique_hash = Letter.generate_hash(letter.from_address, letter.to_address, letter.subject)

        db.session.add(ActivityLog(
            letter_id=letter.id, actor_id=current_user.id,
            action='Edited', details='Letter edited by Data Entry.'
        ))
        db.session.commit()
        flash('Letter updated successfully.', 'success')
        return redirect(url_for('data_entry.dashboard'))

    return render_template('data_entry/edit_letter.html', form=form, letter=letter)


@bp.route('/assign/<int:id>', methods=['GET', 'POST'])
@data_entry_required
def assign_letter(id):
    letter = Letter.query.get_or_404(id)
    form = AssignLetterForm()
    if form.validate_on_submit():
        user_id = form.assignee_id.data
        if user_id and user_id > 0:
            perform_assign_letter(letter, user_id, form.deadline_days.data, actor_label='Data Entry')
            db.session.commit()
            flash('Letter assigned successfully.', 'success')
            return redirect(url_for('data_entry.dashboard'))

    return render_template('data_entry/assign_letter.html', form=form, letter=letter)


@bp.route('/unassign/<int:id>', methods=['POST'])
@data_entry_required
def unassign_letter(id):
    letter = Letter.query.get_or_404(id)
    perform_unassign_letter(letter, actor_label='Data Entry')
    db.session.commit()
    flash('Letter unassigned.', 'info')
    return redirect(url_for('data_entry.dashboard'))


@bp.route('/upload', methods=['GET', 'POST'])
@data_entry_required
def upload():
    form = UploadExcelForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        from app.utils.excel_parser import parse_import_file
        result = parse_import_file(filepath, created_by_id=current_user.id)

        try:
            os.remove(filepath)
        except OSError:
            pass

        flash(f'Import complete: {result["imported"]} imported, '
              f'{result["skipped"]} skipped, {len(result["errors"])} errors.', 'info')
        for err in result['errors'][:10]:
            flash(err, 'warning')
        return redirect(url_for('data_entry.dashboard'))

    return render_template('data_entry/upload.html', form=form)


@bp.route('/export')
@data_entry_required
def export_letters():
    import pandas as pd
    from io import BytesIO

    query, _ = build_letter_filter_query()
    letters = query.order_by(Letter.import_date.desc()).all()

    data = [{
        'ID': l.id, 'Direction': l.direction, 'From': l.from_address,
        'Sender': l.sender_name, 'To': l.to_address, 'Subject': l.subject,
        'Section': l.section, 'Status': l.effective_status, 'Priority': l.priority,
        'Received Date': l.received_date, 'Assignee': l.assignee.full_name if l.assignee else '',
    } for l in letters]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='letters_export.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/bulk-action', methods=['POST'])
@data_entry_required
def bulk_action():
    action = request.form.get('action')
    letter_ids = request.form.getlist('letter_ids')

    if not action or not letter_ids:
        flash('No action or letters selected.', 'warning')
        return redirect(url_for('data_entry.dashboard'))

    letters = Letter.query.filter(Letter.id.in_(letter_ids)).all()

    if action == 'assign':
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
            letter.deadline_date = None
            letter.status = 'Unassigned'
        db.session.commit()
        flash(f'{len(letters)} letter(s) unassigned.', 'info')

    return redirect(url_for('data_entry.dashboard'))
