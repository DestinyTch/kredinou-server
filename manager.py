from flask import Blueprint, jsonify, request
from flask_cors import CORS
from datetime import datetime
from bson import ObjectId

manager_bp = Blueprint("manager_bp", __name__)
CORS(manager_bp, resources={r"/*": {"origins": [
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

# Helper to serialize MongoDB documents
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

# GET all users
@manager_bp.route("/users", methods=["GET"])
def get_users():
    try:
        users = list(users_col.find({}))
        users = [serialize_doc(u) for u in users]
        return jsonify(users), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# GET single user by ID
@manager_bp.route("/users/<user_id>", methods=["GET"])
def get_user(user_id):
    try:
        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify(serialize_doc(user)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# UPDATE user (e.g., update email or phone)
@manager_bp.route("/users/<user_id>", methods=["PUT"])
def update_user(user_id):
    try:
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# DELETE user
@manager_bp.route("/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        result = users_col.delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"message": "User deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
