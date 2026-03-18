from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, SelectField, TextAreaField, PasswordField,
                     BooleanField, SubmitField, DateField, DateTimeLocalField, HiddenField, IntegerField)
from wtforms.validators import DataRequired, Email, Optional, Length, EqualTo, ValidationError, NumberRange
import re

from config import DEFAULT_ROC_ADDRESS


class UploadExcelForm(FlaskForm):
    file = FileField('Excel/CSV File', validators=[
        DataRequired(),
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel and CSV files are allowed.')
    ])
    submit = SubmitField('Upload & Import')


class AssignLetterForm(FlaskForm):
    assignee_id = SelectField('Assign To', coerce=int, validators=[DataRequired()])
    deadline_days = IntegerField('Deadline (days)', validators=[Optional(), NumberRange(min=1, max=365, message='Deadline must be between 1 and 365 days.')])
    submit = SubmitField('Assign')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import User
        users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()
        self.assignee_id.choices = [(0, '-- Select User --')] + [(u.id, u.full_name or u.username) for u in users]


class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[Optional(), Email()])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=150)])
    role = SelectField('Role', choices=[
        ('user', 'User'),
        ('data_entry', 'Data Entry'),
        ('admin', 'ROC')
    ], validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords do not match.')
    ])
    submit = SubmitField('Create User')

    def validate_password(self, field):
        password = field.data
        if not re.search(r'[A-Z]', password):
            raise ValidationError('Password must contain at least one uppercase letter.')
        if not re.search(r'[a-z]', password):
            raise ValidationError('Password must contain at least one lowercase letter.')
        if not re.search(r'\d', password):
            raise ValidationError('Password must contain at least one digit.')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError('Password must contain at least one special character.')


class EditUserForm(FlaskForm):
    email = StringField('Email', validators=[Optional(), Email()])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=150)])
    role = SelectField('Role', choices=[
        ('user', 'User'),
        ('data_entry', 'Data Entry'),
        ('admin', 'ROC')
    ], validators=[DataRequired()])
    new_password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[
        Optional(), EqualTo('new_password', message='Passwords do not match.')
    ])
    submit = SubmitField('Update User')


class AddLetterForm(FlaskForm):
    from_address = TextAreaField('From Address', validators=[DataRequired()])
    sender_name = StringField('Sender Name', validators=[Optional()])
    to_address = TextAreaField('To Address', validators=[DataRequired()])
    subject = TextAreaField('Subject', validators=[DataRequired()])
    received_date = DateTimeLocalField('Date Received', validators=[Optional()], format='%Y-%m-%dT%H:%M')
    section = SelectField('Section', validators=[Optional()], choices=[])
    priority = SelectField('Priority', choices=[
        ('', '-- Select Priority --'),
        ('Critical', 'Critical'),
        ('High', 'High'),
        ('Medium', 'Medium'),
        ('Low', 'Low')
    ], default='', validators=[Optional()])
    assignee_id = SelectField('Assign To', coerce=int, validators=[Optional()])
    deadline_days = IntegerField('Deadline (days)', validators=[Optional(), NumberRange(min=1, max=365, message='Deadline must be between 1 and 365 days.')])
    submit = SubmitField('Add Letter')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Section, User
        sections = Section.get_choices()
        self.section.choices = [('', '-- Select Section --')] + list(sections)
        users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()
        self.assignee_id.choices = [(0, '-- No Assignment --')] + [(u.id, u.full_name or u.username) for u in users]
        # Prefill to_address
        if not self.to_address.data:
            self.to_address.data = DEFAULT_ROC_ADDRESS


class EditLetterForm(FlaskForm):
    from_address = TextAreaField('From Address', validators=[DataRequired()])
    sender_name = StringField('Sender Name', validators=[Optional()])
    to_address = TextAreaField('To Address', validators=[DataRequired()])
    subject = TextAreaField('Subject', validators=[DataRequired()])
    received_date = DateTimeLocalField('Date Received', validators=[Optional()], format='%Y-%m-%dT%H:%M')
    section = SelectField('Section', validators=[Optional()], choices=[])
    priority = SelectField('Priority', choices=[
        ('', '-- Select Priority --'),
        ('Critical', 'Critical'),
        ('High', 'High'),
        ('Medium', 'Medium'),
        ('Low', 'Low')
    ], default='', validators=[Optional()])
    deadline_days = IntegerField('Set Deadline (days)', validators=[Optional(), NumberRange(min=1, max=365, message='Deadline must be between 1 and 365 days.')])
    submit = SubmitField('Update Letter')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Section
        sections = Section.get_choices()
        self.section.choices = [('', '-- Select Section --')] + list(sections)


class AddOutwardLetterForm(FlaskForm):
    case_id = SelectField('Link to Case (optional)', coerce=int, validators=[Optional()])
    from_address = TextAreaField('From Address', validators=[DataRequired()])
    sender_name = StringField('Sender Name', validators=[Optional()])
    to_address = TextAreaField('To Address', validators=[DataRequired()])
    subject = TextAreaField('Subject', validators=[DataRequired()])
    section = SelectField('Section', validators=[Optional()], choices=[])
    sent_date = DateField('Date Sent', validators=[Optional()], format='%Y-%m-%d')
    mark_awaiting = BooleanField('Mark case as Awaiting Response (pause deadline)')
    deadline_days = IntegerField('Deadline (days)', validators=[Optional(), NumberRange(min=1, max=365, message='Deadline must be between 1 and 365 days.')])
    submit = SubmitField('Add Outward Letter')

    def __init__(self, *args, case_preset=None, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Section, Case
        sections = Section.get_choices()
        self.section.choices = [('', '-- Select Section --')] + list(sections)
        cases = Case.query.filter(Case.status != 'Closed').order_by(Case.reference_number).all()
        self.case_id.choices = [(0, '-- Standalone (No Case) --')] + [
            (c.id, f'{c.reference_number} — {c.title or "Untitled"}') for c in cases
        ]
        # Prefill from_address
        if not self.from_address.data:
            self.from_address.data = DEFAULT_ROC_ADDRESS
        # If case preset
        if case_preset:
            self.case_id.data = case_preset.id
            self.section.data = case_preset.section


class AssignCaseForm(FlaskForm):
    assignee_id = SelectField('Assign To', coerce=int, validators=[DataRequired()])
    deadline_days = IntegerField('Deadline (days)', validators=[Optional(), NumberRange(min=1, max=365, message='Deadline must be between 1 and 365 days.')])
    submit = SubmitField('Assign Case')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import User
        users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()
        self.assignee_id.choices = [(0, '-- Select User --')] + [(u.id, u.full_name or u.username) for u in users]


class CreateCaseForm(FlaskForm):
    """UX-2: Standalone case creation form."""
    title = StringField('Title', validators=[DataRequired(), Length(max=300)])
    description = TextAreaField('Description')
    section = SelectField('Section', validators=[DataRequired()])
    priority = SelectField('Priority', choices=[('', '-- Select --'), ('Critical', 'Critical'), ('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')], default='')
    assignee_id = SelectField('Assign To', coerce=int)
    submit = SubmitField('Create Case')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Section, User
        sections = Section.get_choices()
        self.section.choices = [('', '-- Select Section --')] + sections
        users = User.query.filter_by(is_active_user=True, role='user').order_by(User.full_name).all()
        self.assignee_id.choices = [(0, '-- Select User --')] + [(u.id, u.full_name or u.username) for u in users]


class LinkToCaseForm(FlaskForm):
    case_id = SelectField('Select Case', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Link to Case')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Case
        cases = Case.query.filter(Case.status != 'Closed').order_by(Case.reference_number).all()
        self.case_id.choices = [(0, '-- Select Case --')] + [
            (c.id, f'{c.reference_number} — {c.title or "Untitled"}') for c in cases
        ]
