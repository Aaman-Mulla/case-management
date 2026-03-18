from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse

from app.auth import bp
from app.auth.forms import LoginForm, ChangePasswordForm
from app.models import User
from app import db, limiter

# SEC-4: Rate limit login POST only to prevent brute-force attacks
_login_limit = (
    limiter.limit(
        lambda: current_app.config.get('LOGIN_RATE_LIMIT', '6 per minute'),
        methods=['POST'],
    )
    if limiter else (lambda f: f)
)


@bp.route('/login', methods=['GET', 'POST'])
@_login_limit
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('auth.login'))
        if not user.is_active_user:
            flash('Your account is inactive. Please contact ROC.', 'warning')
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if next_page and urlparse(next_page).netloc == '':
            return redirect(next_page)
        return _redirect_by_role(user)
    return render_template('auth/login.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('auth.change_password'))
        if form.current_password.data == form.new_password.data:
            flash('New password cannot be the same as current password.', 'warning')
            return redirect(url_for('auth.change_password'))
        current_user.set_password(form.new_password.data)
        db.session.commit()
        current_app.logger.info(f'User {current_user.username} changed password.')
        flash('Password changed successfully.', 'success')
        return _redirect_by_role(current_user)
    return render_template('auth/change_password.html', form=form)


def _redirect_by_role(user):
    if user.is_admin:
        return redirect(url_for('admin.dashboard'))
    elif user.is_data_entry:
        return redirect(url_for('data_entry.dashboard'))
    else:
        return redirect(url_for('main.dashboard'))
