from datetime import datetime
from flask import Blueprint, request, jsonify
from bson import ObjectId
from extensions import get_db
from decorators import admin_token_required
from flask_cors import CORS

# Blueprint
admin_withdrawals_bp = Blueprint("admin_withdrawals", __name__, url_prefix="/admin/withdrawals")
print("HI")
