from flask import Blueprint, jsonify, request
from flask_cors import CORS
from datetime import datetime
from bson import ObjectId
from bson.son import SON
from extensions import get_db

dashboard_bp = Blueprint("dashboard_bp", __name__)

# Enable CORS for allowed frontend domains
CORS(dashboard_bp, resources={r"/*": {"origins": [
    "https://destinytch.com.ng",
    "https://www.destinytch.com.ng",
    "https://kredinou.com",
    "https://www.kredinou.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]}}, supports_credentials=True)

# MongoDB collections
db = get_db()
users_col = db.users
loans_col = db.loans
withdrawals_col = db.withdrawals
repayments_col = db.repayments  # Assuming you have a repayments collection

# -------------------------
# Helper to serialize MongoDB documents
# -------------------------
def serialize_doc(doc):
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        elif isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc

# -------------------------
# USERS ROUTES
# -------------------------
@dashboard_bp.route("/users", methods=["GET"])
def get_users():
    try:
        users = list(users_col.find({}))
        users = [serialize_doc(u) for u in users]
        return jsonify(users), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/users/<user_id>", methods=["GET"])
def get_user(user_id):
    try:
        user = users_col.find_one({"_id": ObjectId(user_id)})
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify(serialize_doc(user)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/users/<user_id>", methods=["PUT"])
def update_user(user_id):
    try:
        data = request.get_json()
        update_fields = {}
        for field in ["email", "phone", "loan_limit", "verification_status", "status"]:
            if field in data:
                update_fields[field] = data[field]

        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400

        result = users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})
        if result.matched_count == 0:
            return jsonify({"error": "User not found"}), 404

        updated_user = users_col.find_one({"_id": ObjectId(user_id)})
        return jsonify(serialize_doc(updated_user)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        result = users_col.delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"message": "User deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# LOANS ROUTES
# -------------------------
@dashboard_bp.route("/loans", methods=["GET"])
def get_loans():
    try:
        loans = list(loans_col.find({}))
        loans = [serialize_doc(l) for l in loans]
        return jsonify(loans), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    try:
        loan = loans_col.find_one({"_id": loan_id})
        if not loan:
            return jsonify({"error": "Loan not found"}), 404
        return jsonify(serialize_doc(loan)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# WITHDRAWALS ROUTES
# -------------------------
@dashboard_bp.route("/withdrawals", methods=["GET"])
def get_withdrawals():
    try:
        withdrawals = list(withdrawals_col.find({}))
        withdrawals = [serialize_doc(w) for w in withdrawals]
        return jsonify(withdrawals), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/withdrawals/<withdrawal_id>", methods=["GET"])
def get_withdrawal(withdrawal_id):
    try:
        withdrawal = withdrawals_col.find_one({"_id": ObjectId(withdrawal_id)})
        if not withdrawal:
            return jsonify({"error": "Withdrawal not found"}), 404
        return jsonify(serialize_doc(withdrawal)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# DASHBOARD SUMMARY & CHART ROUTES
# -------------------------
@dashboard_bp.route("/admin/dashboard/summary", methods=["GET"])
def dashboard_summary():
    try:
        total_users = users_col.count_documents({})
        total_loans = loans_col.count_documents({})
        total_repayments = repayments_col.count_documents({})
        total_withdrawals = withdrawals_col.count_documents({})

        return jsonify({
            "total_users": total_users,
            "total_loans": total_loans,
            "total_repayments": total_repayments,
            "total_withdrawals": total_withdrawals
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/admin/dashboard/chart-data", methods=["GET"])
def dashboard_chart_data():
    try:
        def aggregate_daily(collection, field="amount"):
            pipeline = [
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "total": {"$sum": f"${field}"}
                }},
                {"$sort": SON([("_id", 1)])}
            ]
            return list(db[collection].aggregate(pipeline))

        loans = aggregate_daily("loans", field="loan_limit")
        repayments = aggregate_daily("repayments")
        withdrawals = aggregate_daily("withdrawals")

        return jsonify({
            "loans": loans,
            "repayments": repayments,
            "withdrawals": withdrawals
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
