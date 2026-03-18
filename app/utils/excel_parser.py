"""Excel/CSV import parser for letters."""

import hashlib
from datetime import datetime

import pandas as pd
from app import db
from app.models import Letter, User, ActivityLog, Notification, _utcnow


COLUMN_MAPPING = {
    'from address': 'from_address',
    'from': 'from_address',
    'to address': 'to_address',
    'to': 'to_address',
    'subject': 'subject',
    'sender name': 'sender_name',
    'sender': 'sender_name',
    'date received': 'received_date',
    'date': 'received_date',
    'priority': 'priority',
    'section': 'section',
    'direction': 'direction',
    'assigned to': 'assigned_to',
    'assignee': 'assigned_to',
}

VALID_PRIORITIES = {'Critical', 'High', 'Medium', 'Low'}


def parse_import_file(filepath, created_by_id=None):
    """Parse an Excel or CSV file and import letters.

    Returns dict with keys: imported, skipped, errors, total
    """
    result = {
        'imported': 0,
        'skipped': 0,
        'errors': [],
        'total': 0,
    }

    try:
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath, sheet_name=0)
    except Exception as e:
        result['errors'].append(f'Failed to read file: {str(e)}')
        return result

    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    col_map = {}
    for col in df.columns:
        if col in COLUMN_MAPPING:
            col_map[col] = COLUMN_MAPPING[col]

    if 'from_address' not in col_map.values() or 'subject' not in col_map.values():
        result['errors'].append('Missing required columns: From Address, Subject')
        return result

    df = df.rename(columns=col_map)
    result['total'] = len(df)

    for idx, row in df.iterrows():
        try:
            from_addr = str(row.get('from_address', '')).strip()
            to_addr = str(row.get('to_address', '')).strip()
            subject = str(row.get('subject', '')).strip()

            if not from_addr or not subject:
                result['errors'].append(f'Row {idx + 2}: Missing required fields')
                continue

            # Check for duplicates
            hash_val = Letter.generate_hash(from_addr, to_addr, subject)
            existing = Letter.query.filter_by(unique_hash=hash_val).first()
            if existing:
                result['skipped'] += 1
                continue

            direction = str(row.get('direction', 'Inward')).strip()
            if direction not in ('Inward', 'Outward'):
                direction = 'Inward'

            priority = str(row.get('priority', '')).strip() if pd.notna(row.get('priority')) else None
            if priority and priority not in VALID_PRIORITIES:
                priority = None

            section = str(row.get('section', '')).strip() if pd.notna(row.get('section')) else None

            sender_name = str(row.get('sender_name', '')).strip() if pd.notna(row.get('sender_name')) else None

            received_date = None
            if 'received_date' in row and pd.notna(row['received_date']):
                try:
                    received_date = pd.to_datetime(row['received_date']).to_pydatetime().replace(tzinfo=None)
                except Exception:
                    pass

            letter = Letter(
                from_address=from_addr,
                to_address=to_addr,
                subject=subject,
                sender_name=sender_name,
                unique_hash=hash_val,
                received_date=received_date,
                direction=direction,
                section=section,
                priority=priority,
                status='Outward' if direction == 'Outward' else 'Unassigned',
                created_by_id=created_by_id,
            )

            # Handle assignment
            assigned_to = str(row.get('assigned_to', '')).strip() if pd.notna(row.get('assigned_to')) else None
            if assigned_to and direction != 'Outward':
                user = User.query.filter(
                    db.or_(
                        User.username == assigned_to,
                        User.full_name == assigned_to
                    ),
                    User.is_active_user == True
                ).first()
                if user:
                    letter.assignee_id = user.id
                    letter.assigned_by_id = created_by_id
                    letter.assignment_date = _utcnow()
                    letter.status = 'Assigned'

            db.session.add(letter)
            db.session.flush()

            # Activity log
            db.session.add(ActivityLog(
                letter_id=letter.id,
                actor_id=created_by_id,
                action='Imported',
                details=f'Imported from file (row {idx + 2})',
            ))

            result['imported'] += 1

        except Exception as e:
            result['errors'].append(f'Row {idx + 2}: {str(e)}')

    db.session.commit()

    # Notify admins about import
    if created_by_id and result['imported'] > 0:
        admin_users = User.query.filter_by(role='admin', is_active_user=True).all()
        creator = db.session.get(User, created_by_id)
        creator_name = creator.full_name if creator else 'Unknown'
        for admin in admin_users:
            if admin.id != created_by_id:
                db.session.add(Notification(
                    user_id=admin.id,
                    message=f'{creator_name} imported {result["imported"]} letter(s).',
                    notification_type='import'
                ))
        db.session.commit()

    return result
