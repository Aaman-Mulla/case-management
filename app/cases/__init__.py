from flask import Blueprint

bp = Blueprint('cases', __name__, template_folder='../templates/cases')

from app.cases import routes  # noqa: F401, E402
