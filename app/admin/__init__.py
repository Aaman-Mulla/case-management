from flask import Blueprint

bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from app.admin import routes  # noqa: F401, E402
