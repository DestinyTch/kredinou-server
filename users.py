# users.py
from flask import Blueprint, jsonify, request
from flask_cors import CORS
from datetime import datetime
from bson import ObjectId

users_bp = Blueprint("users_bp", __name__, url_prefix="/users")
CORS(users_bp, resources={r"/*": {"origins": [
    "https://destinytch.com.ng",
    "https://www.destinytch.com.ng",
    "https://kredinou.com",
    "https://www.kredinou.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]}}, supports_credentials=True)

# MongoDB collections
from extensions import get_db
db = get_db()
users_col = db.users

# --- Helper to serialize MongoDB docs ---
def serialize_doc(doc):
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        elif isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc

# ------------------------
# USERS ENDPOINTS
# ------------------------

# Get all users
@users_bp.route("/", methods=["GET"])
def get_users():
    users = list(users_col.find({}))
    users = [serialize_doc(u) for u in users]
    return jsonify(users), 200

# Get a single user
@users_bp.route("/<user_id>", methods=["GET"])
def get_user(user_id):
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(serialize_doc(user)), 200

# Update user (example: email, phone)
@users_bp.route("/<user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json()
    update_fields = {}

    if "email" in data:
        update_fields["email"] = data["email"]
    if "phone" in data:
        update_fields["phone"] = data["phone"]

    if not update_fields:
        return jsonify({"error": "No valid fields to update"}), 400

    result = users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})
    if result.matched_count == 0:
        return jsonify({"error": "User not found"}), 404

    updated_user = users_col.find_one({"_id": ObjectId(user_id)})
    return jsonify(serialize_doc(updated_user)), 200

# Delete user
@users_bp.route("/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    result = users_col.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 0:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"message": "User deleted"}), 200
