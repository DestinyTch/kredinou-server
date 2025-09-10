from datetime import datetime
from flask import Blueprint, request, jsonify
from bson import ObjectId
from extensions import get_db
from decorators import admin_token_required
from flask_cors import CORS

# Blueprint
admin_withdrawals_bp = Blueprint("admin_withdrawals", __name__, url_prefix="/admin/withdrawals")
# Enable CORS
CORS(
    admin_withdrawals_bp, 
    resources={r"/*": {"origins": "https://destinytch.com.ng"}}, 
    supports_credentials=True,
    methods=["GET", "PATCH", "OPTIONS"]  # explicitly allow OPTIONS
)

# Collections
db = get_db()
withdrawals_collection = db.withdrawals
users_collection = db.users

# -----------------------------
# Route: Summary
# -----------------------------
@admin_withdrawals_bp.route("/summary", methods=["GET"])
@admin_token_required
def withdrawals_summary(current_admin):
    try:
        total_withdrawals = withdrawals_collection.count_documents({})
        pending_count = withdrawals_collection.count_documents({"status": "pending"})
        approved_aggregate = withdrawals_collection.aggregate([
            {"$match": {"status": "approved"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ])
        total_approved_amount = 0
        for r in approved_aggregate:
            total_approved_amount = r.get("total", 0)

        rejected_count = withdrawals_collection.count_documents({"status": "rejected"})

        return jsonify({
            "totalWithdrawals": total_withdrawals,
            "pendingWithdrawals": pending_count,
            "totalApprovedAmount": total_approved_amount,
            "rejectedWithdrawals": rejected_count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Route: Pending withdrawals
# -----------------------------
@admin_withdrawals_bp.route("/pending", methods=["GET"])
@admin_token_required
def list_pending_withdrawals(current_admin):
    try:
        pending = withdrawals_collection.find({"status": "pending"}).sort("requested_at", -1)
        results = []

        for w in pending:
            user = users_collection.find_one({"_id": w["userId"]})
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}" if user else "Unknown"
            results.append({
                "withdrawalId": str(w["_id"]),
                "userId": str(w["userId"]),
                "userName": user_name,
                "email": user.get("email") if user else None,
                "phone": user.get("phone") if user else None,
                "balance": user.get("balance", 0) if user else 0,
                "amount": w["amount"],
                "method": w["payment_method"],
                "accountName": w["account_name"],
                "accountNumber": w["account_number"],
                "status": w["status"],
                "requestedAt": w["requested_at"].isoformat(),
                "adminNotes": w.get("admin_notes")
            })
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Route: Approve withdrawal
# -----------------------------
@admin_withdrawals_bp.route("/approve/<withdrawal_id>", methods=["PUT"])
@admin_token_required
def approve_withdrawal(current_admin, withdrawal_id):
    try:
        withdrawal = withdrawals_collection.find_one({"_id": ObjectId(withdrawal_id)})
        if not withdrawal:
            return jsonify({"error": "Withdrawal not found"}), 404

        if withdrawal["status"] != "pending":
            return jsonify({"error": "Withdrawal is not pending"}), 400

        # Optionally: deduct from user balance
        user = users_collection.find_one({"_id": withdrawal["userId"]})
        if user:
            new_balance = max(user.get("balance", 0) - withdrawal["amount"], 0)
            users_collection.update_one(
                {"_id": withdrawal["userId"]},
                {"$set": {"balance": new_balance}}
            )

        withdrawals_collection.update_one(
            {"_id": ObjectId(withdrawal_id)},
            {"$set": {"status": "approved", "updated_at": datetime.utcnow()}}
        )
        return jsonify({"message": "Withdrawal approved"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Route: Reject withdrawal
# -----------------------------
@admin_withdrawals_bp.route("/reject/<withdrawal_id>", methods=["PUT"])
@admin_token_required
def reject_withdrawal(current_admin, withdrawal_id):
    try:
        reason = request.json.get("reason", "No reason provided")
        withdrawal = withdrawals_collection.find_one({"_id": ObjectId(withdrawal_id)})
        if not withdrawal:
            return jsonify({"error": "Withdrawal not found"}), 404

        if withdrawal["status"] != "pending":
            return jsonify({"error": "Withdrawal is not pending"}), 400

        withdrawals_collection.update_one(
            {"_id": ObjectId(withdrawal_id)},
            {"$set": {"status": "rejected", "admin_notes": reason, "updated_at": datetime.utcnow()}}
        )
        return jsonify({"message": "Withdrawal rejected", "reason": reason}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Route: Full withdrawal history
# -----------------------------
@admin_withdrawals_bp.route("/history", methods=["GET"])
@admin_token_required
def withdrawals_history(current_admin):
    try:
        withdrawals = withdrawals_collection.find().sort("requested_at", -1)
        history = []

        for w in withdrawals:
            user = users_collection.find_one({"_id": w["userId"]})
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}" if user else "Unknown"

            history.append({
                "withdrawalId": str(w["_id"]),
                "userId": str(w["userId"]),
                "userName": user_name,
                "email": user.get("email") if user else None,
                "phone": user.get("phone") if user else None,
                "balance": user.get("balance", 0) if user else 0,
                "amount": w["amount"],
                "method": w["payment_method"],
                "accountName": w["account_name"],
                "accountNumber": w["account_number"],
                "status": w["status"],
                "requestedAt": w["requested_at"].isoformat(),
                "adminNotes": w.get("admin_notes")
            })
        return jsonify(history), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
