from flask import Blueprint

bp = Blueprint('data_entry', __name__, template_folder='../templates/data_entry')

from app.data_entry import routes  # noqa: F401, E402
