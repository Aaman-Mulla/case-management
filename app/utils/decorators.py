"""Reusable Flask authorization decorator factories."""

import functools

from flask import abort
from flask_login import current_user, login_required


def role_required(permission_attr: str):
    """Return a decorator that aborts with 403 unless the logged-in user has
    the given boolean property.

    Usage::

        from app.utils.decorators import role_required

        admin_required    = role_required('is_admin')
        de_required       = role_required('is_data_entry')

        @bp.route('/dashboard')
        @admin_required
        def dashboard(): ...
    """
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            if not getattr(current_user, permission_attr, False):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
