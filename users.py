# users.py
"""
Users blueprint tailored to the Kredinou admin UI.

Exposes:
  GET    /users/               -> list all users (no pagination)
  GET    /users/<user_id>      -> single user by _id (supports ObjectId or string _id)
  PUT    /users/<user_id>      -> update user (whitelisted fields)
  DELETE /users/<user_id>      -> delete user and cascade related records
  GET    /users/<user_id>/loans-> list loans for user (supports userId stored as string or ObjectId)

Notes:
- Uses `get_db()` from extensions.py to access MongoDB collections.
- Serializes ObjectId and datetime values recursively without mutating DB documents.
- CORS origins reflect the frontend hosts you've provided earlier.
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

# Collections
db = get_db()
users_col = db.users
loans_col = db.loans
repayments_col = db.repayments
withdrawals_col = db.withdrawals

# ----------------------
# Helpers
# ----------------------
def _to_objectid_or_raw(id_str):
    """Try to convert id_str to ObjectId; if invalid, return original string."""
    if not id_str:
        return id_str
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return id_str

def _serialize_value(v):
    """Serialize single primitive values for JSON output."""
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v

def serialize_doc(doc):
    """
    Deep-serialize a MongoDB document (ObjectId -> str, datetime -> ISO).
    Returns a NEW Python structure; does NOT mutate the original doc.
    """
    if doc is None:
        return None

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(i) for i in obj]
        return _serialize_value(obj)

    return _walk(doc)

def _error(msg, status=400):
    return jsonify({"error": msg}), status

# ------------------------
# USERS ENDPOINTS
# ------------------------

@users_bp.route("/", methods=["GET"])
def get_users():
    """
    GET /users/
    Return all users with `loans_count` included.
    """
    try:
        pipeline = [
            # Lookup loans per user
            {
                "$lookup": {
                    "from": "loans",
                    "let": {"uid": "$_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {"$eq": ["$userId", "$$uid"]},  # ObjectId match
                                        {"$eq": ["$userId", {"$toString": "$$uid"}]}  # string match
                                    ]
                                }
                            }
                        },
                        {"$count": "count"}
                    ],
                    "as": "_loanCount"
                }
            },
            # Add loans_count field
            {
                "$addFields": {
                    "loans_count": {"$ifNull": [{"$arrayElemAt": ["$_loanCount.count", 0]}, 0]}
                }
            },
            # Remove temporary array
            {"$project": {"_loanCount": 0}}
        ]

        cursor = users_col.aggregate(pipeline)
        users = [serialize_doc(d) for d in cursor]
        return jsonify(users), 200
    except Exception as exc:
        current_app.logger.exception("get_users aggregation error")
        return _error("Internal server error", 500)


@users_bp.route("/<user_id>", methods=["GET"])
def get_user(user_id):
    """
    GET /users/<user_id>
    Returns a single user; supports ObjectId or string _id.
    """
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
    """
    PUT /users/<user_id>
    Allowed update fields (whitelist):
      email, phone, first_name, middle_name, last_name,
      address, department, commune, loan_limit, verification_status
    """
    try:
        payload = request.get_json() or {}
        allowed = {
            "email", "phone", "first_name", "middle_name", "last_name",
            "address", "department", "commune", "loan_limit", "verification_status"
        }
        update_fields = {k: payload[k] for k in payload.keys() if k in allowed}

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
    """
    DELETE /users/<user_id>
    Deletes user and cascades to related loans, repayments and withdrawals.
    Cascade attempts to match userId in related collections both as string and ObjectId.
    """
    try:
        query_id = _to_objectid_or_raw(user_id)
        user = users_col.find_one({"_id": query_id})
        if not user:
            return _error("User not found", 404)

        # build userId match possibilities for related collections
        matches = [{"userId": user_id}]
        try:
            user_obj = ObjectId(user_id)
            matches.append({"userId": user_obj})
        except Exception:
            user_obj = None

        # cascade deletes
        loans_col.delete_many({"$or": matches})
        repayments_col.delete_many({"$or": matches})
        withdrawals_col.delete_many({"$or": matches})

        # delete the user
        users_col.delete_one({"_id": query_id})

        return jsonify({"message": "User and related records deleted"}), 200
    except Exception as exc:
        current_app.logger.exception("delete_user error")
        return _error("Internal server error", 500)


@users_bp.route("/<user_id>/loans", methods=["GET"])
def get_user_loans(user_id):
    """
    GET /users/<user_id>/loans
    Returns loans for the user; supports userId stored as string or ObjectId.
    """
    try:
        queries = [{"userId": user_id}]
        try:
            user_obj = ObjectId(user_id)
            queries.append({"userId": user_obj})
        except Exception:
            pass

        q = {"$or": queries}
        loans = list(loans_col.find(q).sort("createdAt", -1))
        loans_out = [serialize_doc(l) for l in loans]
        return jsonify(loans_out), 200
    except Exception as exc:
        current_app.logger.exception("get_user_loans error")
        return _error("Internal server error", 500)
