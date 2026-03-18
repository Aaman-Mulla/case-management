"""Shared query helpers for dashboards."""

from flask import request
from app import db
from app.models import Letter, Case, _utcnow


def build_letter_filter_query(query=None):
    """Build and apply standard filters to a Letter query.
    Returns (query, active_filters_dict).
    """
    if query is None:
        query = Letter.query

    active_filters = {}

    status = request.args.get('status', '').strip()
    if status:
        query = query.filter(Letter.status == status)
        active_filters['status'] = status

    priority = request.args.get('priority', '').strip()
    if priority:
        query = query.filter(Letter.priority == priority)
        active_filters['priority'] = priority

    assignee = request.args.get('assignee', '').strip()
    if assignee:
        query = query.filter(Letter.assignee_id == int(assignee))
        active_filters['assignee'] = assignee

    sender_name = request.args.get('sender_name', '').strip()
    if sender_name:
        query = query.filter(Letter.sender_name == sender_name)
        active_filters['sender_name'] = sender_name

    direction = request.args.get('direction', '').strip()
    if direction:
        query = query.filter(Letter.direction == direction)
        active_filters['direction'] = direction

    section = request.args.get('section', '').strip()
    if section:
        # Use outerjoin to include standalone letters (no case)
        query = query.outerjoin(Letter.case).filter(
            db.or_(Case.section == section, Letter.section == section)
        )
        active_filters['section'] = section

    q = request.args.get('q', '').strip()
    if q:
        search = f'%{q}%'
        query = query.filter(db.or_(
            Letter.from_address.ilike(search),
            Letter.to_address.ilike(search),
            Letter.subject.ilike(search)
        ))
        active_filters['q'] = q

    return query, active_filters


def get_letter_stats(query=None):
    """Compute dashboard stat counts using SQL aggregation.
    BUG-12/PERF-3: Uses SQL COUNT+CASE instead of loading all letters into Python.
    """
    if query is None:
        query = Letter.query

    now = _utcnow()

    # Build subquery from the provided query's filters
    base = query.with_entities(
        db.func.count(Letter.id).label('total'),
        db.func.sum(db.case(
            (Letter.status.in_(['Unassigned', 'Pending']), 1), else_=0
        )).label('unassigned'),
        db.func.sum(db.case(
            (Letter.status.in_(['Assigned', 'In Progress']), 1), else_=0
        )).label('in_progress'),
        db.func.sum(db.case(
            (Letter.status.in_(['Resolved', 'Closed']), 1), else_=0
        )).label('resolved'),
        db.func.sum(db.case(
            (db.and_(
                Letter.deadline_date.isnot(None),
                Letter.deadline_date < now,
                ~Letter.status.in_(['Resolved', 'Closed', 'Outward'])
            ), 1), else_=0
        )).label('overdue'),
        db.func.sum(db.case(
            (Letter.priority == 'Critical', 1), else_=0
        )).label('p0'),
        db.func.sum(db.case(
            (Letter.priority == 'High', 1), else_=0
        )).label('p1'),
        db.func.sum(db.case(
            (Letter.priority == 'Medium', 1), else_=0
        )).label('p2'),
        db.func.sum(db.case(
            (Letter.priority == 'Low', 1), else_=0
        )).label('p3'),
    ).first()

    return {
        'total': base.total or 0,
        'unassigned': base.unassigned or 0,
        'in_progress': base.in_progress or 0,
        'resolved': base.resolved or 0,
        'overdue': base.overdue or 0,
        'p0': base.p0 or 0,
        'p1': base.p1 or 0,
        'p2': base.p2 or 0,
        'p3': base.p3 or 0,
    }


def get_distinct_senders():
    """Return sorted list of distinct non-null sender names."""
    senders = db.session.query(Letter.sender_name).filter(
        Letter.sender_name.isnot(None),
        Letter.sender_name != ''
    ).distinct().all()
    return sorted([s[0] for s in senders])
