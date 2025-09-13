"""
Users blueprint tailored to the Kredinou admin UI.

Exposes:
  GET    /users/                   -> list all users (no pagination)
  GET    /users/<user_id>          -> single user by _id (supports ObjectId or string _id)
  PUT    /users/<user_id>          -> update user (whitelisted fields)
  DELETE /users/<user_id>          -> delete user and cascade related records
  GET    /users/<user_id>/loans    -> list loans for user
  POST   /users/<user_id>/verify-face -> verify user face
  POST   /documents/<doc_id>/verify   -> verify a document
"""

from flask import Blueprint, jsonify, request, current_app
from flask_cors import CORS
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from extensions import get_db

users_bp = Blueprint("users_bp", __name__, url_prefix="/users")
CORS(users_bp, resources={r"/*": {"origins": [
    "https://destinytch.com.ng",
    "https://www.destinytch.com.ng",
    "https://kredinou.com",
    "https://www.kredinou.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]}}, supports_credentials=True)

# ----------------------
# Collections
# ----------------------
db = get_db()
users_col = db.users
loans_col = db.loans
repayments_col = db.repayments
withdrawals_col = db.withdrawals
documents_col = db.documents  # added for document verification

# ----------------------
# Helpers
# ----------------------
def _to_objectid_or_raw(id_str):
    """Try to convert id_str to ObjectId; fallback to string."""
    if not id_str:
        return id_str
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return id_str

def _serialize_value(v):
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v

def serialize_doc(doc):
    """Recursively serialize MongoDB document without mutating it."""
    if doc is None:
        return None
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [serialize_doc(i) for i in doc]
    return _serialize_value(doc)

def _error(msg, status=400):
    return jsonify({"error": msg}), status

# ------------------------
# USERS ENDPOINTS
# ------------------------

@users_bp.route("/", methods=["GET"])
def get_users():
    """List all users with loans_count"""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "loans",
                    "let": {"uid": "$_id"},
                    "pipeline": [
                        {"$match": {"$expr": {"$or": [
                            {"$eq": ["$userId", "$$uid"]},
                            {"$eq": ["$userId", {"$toString": "$$uid"}]}
                        ]}}},
                        {"$count": "count"}
                    ],
                    "as": "_loanCount"
                }
            },
            {"$addFields": {"loans_count": {"$ifNull": [{"$arrayElemAt": ["$_loanCount.count", 0]}, 0]}}},
            {"$project": {"_loanCount": 0}}
        ]
        users = [serialize_doc(d) for d in users_col.aggregate(pipeline)]
        return jsonify(users), 200
    except Exception as exc:
        current_app.logger.exception("get_users error")
        return _error("Internal server error", 500)

@users_bp.route("/<user_id>", methods=["GET"])
def get_user(user_id):
    """Get single user by _id"""
    try:
        query_id = _to_objectid_or_raw(user_id)
        user = users_col.find_one({"_id": query_id})
        if not user:
            return _error("User not found", 404)
        return jsonify(serialize_doc(user)), 200
    except Exception as exc:
        current_app.logger.exception("get_user error")
        return _error("Internal server error", 500)

@users_bp.route("/<user_id>", methods=["PUT"])
def update_user(user_id):
    """Update allowed fields for a user"""
    try:
        payload = request.get_json() or {}
        allowed = {"email", "phone", "first_name", "middle_name", "last_name",
                   "address", "department", "commune", "loan_limit", "verification_status"}
        update_fields = {k: payload[k] for k in payload if k in allowed}
        if not update_fields:
            return _error("No valid fields to update", 400)
        update_fields["updated_at"] = datetime.utcnow()
        query_id = _to_objectid_or_raw(user_id)
        result = users_col.update_one({"_id": query_id}, {"$set": update_fields})
        if result.matched_count == 0:
            return _error("User not found", 404)
        updated = users_col.find_one({"_id": query_id})
        return jsonify(serialize_doc(updated)), 200
    except Exception as exc:
        current_app.logger.exception("update_user error")
        return _error("Internal server error", 500)

@users_bp.route("/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Delete user and cascade related records"""
    try:
        query_id = _to_objectid_or_raw(user_id)
        user = users_col.find_one({"_id": query_id})
        if not user:
            return _error("User not found", 404)

        matches = [{"userId": user_id}]
        try:
            matches.append({"userId": ObjectId(user_id)})
        except Exception:
            pass

        loans_col.delete_many({"$or": matches})
        repayments_col.delete_many({"$or": matches})
        withdrawals_col.delete_many({"$or": matches})

        users_col.delete_one({"_id": query_id})
        return jsonify({"message": "User and related records deleted"}), 200
    except Exception as exc:
        current_app.logger.exception("delete_user error")
        return _error("Internal server error", 500)

@users_bp.route("/<user_id>/loans", methods=["GET"])
def get_user_loans(user_id):
    """List loans for a specific user"""
    try:
        queries = [{"userId": user_id}]
        try:
            queries.append({"userId": ObjectId(user_id)})
        except Exception:
            pass
        loans = list(loans_col.find({"$or": queries}).sort("createdAt", -1))
        return jsonify([serialize_doc(l) for l in loans]), 200
    except Exception as exc:
        current_app.logger.exception("get_user_loans error")
        return _error("Internal server error", 500)

# ------------------------
# FACE VERIFICATION
# ------------------------
@users_bp.route("/<user_id>/verify-face", methods=["POST"])
def verify_user_face(user_id):
    try:
        query_id = _to_objectid_or_raw(user_id)
        user = users_col.find_one({"_id": query_id})
        if not user:
            return _error("User not found", 404)

        if not user.get("face_image") or not user["face_image"].get("url"):
            return _error("No face image uploaded for this user", 400)

        users_col.update_one(
            {"_id": query_id},
            {"$set": {"face_image.verified": True, "face_image.verified_at": datetime.utcnow()}}
        )
        updated_user = users_col.find_one({"_id": query_id})
        return jsonify(serialize_doc(updated_user)), 200
    except Exception as exc:
        current_app.logger.exception("verify_user_face error")
        return _error("Internal server error", 500)

# ------------------------
# DOCUMENT VERIFICATION
# ------------------------
@users_bp.route("/documents/<doc_id>/verify", methods=["POST"])
def verify_document(doc_id):
    try:
        doc_oid = _to_objectid_or_raw(doc_id)
        doc = documents_col.find_one({"_id": doc_oid})
        if not doc:
            return _error("Document not found", 404)
        documents_col.update_one(
            {"_id": doc_oid},
            {"$set": {"verified": True, "verified_at": datetime.utcnow()}}
        )
        updated_doc = documents_col.find_one({"_id": doc_oid})
        return jsonify(serialize_doc(updated_doc)), 200
    except Exception as exc:
        current_app.logger.exception("verify_document error")
        return _error("Internal server error", 500)
