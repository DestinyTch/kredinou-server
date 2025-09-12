from datetime import datetime
from flask import Blueprint, request, jsonify
from bson import ObjectId
from extensions import get_db
from decorators import admin_token_required  # <-- new decorator to restrict admin routes
from flask_cors import CORS
# Blueprint
admin_repayments_bp = Blueprint("admin_repayments", __name__)
CORS(admin_repayments_bp, resources={r"/*": {"origins": "*"}})

# Collections
db = get_db()
repayments_collection = db.repayments
loans_collection = db.loans
users_collection = db.users



@admin_repayments_bp.route("/summary", methods=["GET"])
def summary():
    try:
        # Total repayments
        total_repayments = repayments_collection.count_documents({})

        # Pending verifications
        pending_count = repayments_collection.count_documents({"status": "pending_verification"})

        # Verified repayments (total amount)
        verified_repayments = repayments_collection.aggregate([
            {"$match": {"status": "verified"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ])
        total_verified_amount = 0
        for r in verified_repayments:
            total_verified_amount = r.get("total", 0)

        # Active loans
        active_loans = loans_collection.count_documents({"status": {"$in": ["disbursed", "overdue"]}})

        # Completed loans
        completed_loans = loans_collection.count_documents({ "status": {"$in": ["completed", "repaid"]}})

        return jsonify({
            "totalRepayments": total_repayments,
            "pendingVerifications": pending_count,
            "totalVerifiedAmount": total_verified_amount,
            "activeLoans": active_loans,
            "completedLoans": completed_loans
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# -----------------------------
# Route: List all pending repayments
# -----------------------------
@admin_repayments_bp.route("/pending", methods=["GET"])

def list_pending():
    pending = repayments_collection.find({"status": "pending_verification"}).sort("createdAt", -1)
    results = []
    for r in pending:
        results.append({
            "repaymentId": str(r["_id"]),
            "loanId": str(r["loanId"]),
            "userId": str(r["userId"]),
            "amount": r["amount"],
            "method": r["method"],
            "proofUrl": r.get("proofUrl"),
            "createdAt": r["createdAt"].isoformat()
        })
    return jsonify(results), 200

# -----------------------------
# Route: Approve repayment
# -----------------------------
@admin_repayments_bp.route("/approve/<repayment_id>", methods=["PUT"])

def approve_repayment(repayment_id):
    repayment = repayments_collection.find_one({"_id": ObjectId(repayment_id)})
    if not repayment:
        return jsonify({"error": "Repayment not found"}), 404

    if repayment["status"] != "pending_verification":
        return jsonify({"error": "Repayment is not pending"}), 400

    # Mark repayment as verified
    repayments_collection.update_one(
        {"_id": ObjectId(repayment_id)},
        {"$set": {"status": "verified", "updatedAt": datetime.utcnow()}}
    )

    # Optional: check if loan fully repaid
    loan = loans_collection.find_one({"_id": repayment["loanId"]})
    if loan:
        # Sum all verified repayments
        verified_total = repayments_collection.aggregate([
            {"$match": {"loanId": loan["_id"], "status": "verified"}},
            {"$group": {"_id": None, "totalPaid": {"$sum": "$amount"}}}
        ])
        total_paid = 0
        for r in verified_total:
            total_paid = r.get("totalPaid", 0)

        principal = loan["amount"]
        interest = principal * 0.10
        late_fee = 0
        if datetime.utcnow() > loan["dueDate"]:
            months_late = ((datetime.utcnow() - loan["dueDate"]).days // 30) + 1
            late_fee = principal * 0.05 * months_late

        total_due = principal + interest + late_fee
        if total_paid >= total_due:
            loans_collection.update_one(
                {"_id": loan["_id"]},
                {"$set": {"status": "repaid"}}
            )

    return jsonify({"message": "Repayment approved and verified"}), 200

# -----------------------------
# Route: Reject repayment
# -----------------------------
@admin_repayments_bp.route("/reject/<repayment_id>", methods=["PUT"])

def reject_repayment(repayment_id):
    reason = request.json.get("reason", "No reason provided")

    repayment = repayments_collection.find_one({"_id": ObjectId(repayment_id)})
    if not repayment:
        return jsonify({"error": "Repayment not found"}), 404

    if repayment["status"] != "pending_verification":
        return jsonify({"error": "Repayment is not pending"}), 400

    repayments_collection.update_one(
        {"_id": ObjectId(repayment_id)},
        {"$set": {"status": "rejected", "rejectionReason": reason, "updatedAt": datetime.utcnow()}}
    )

    return jsonify({"message": "Repayment rejected", "reason": reason}), 200

@admin_repayments_bp.route("/history", methods=["GET"])

def repayment_history():
    try:
        repayments = repayments_collection.find().sort("createdAt", -1)

        history = []
        for r in repayments:
            # Get user details
            user = users_collection.find_one({"_id": r["userId"]})
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}" if user else "Unknown"

            history.append({
                "repaymentId": str(r["_id"]),
                "loanId": str(r["loanId"]),
                "userId": str(r["userId"]),
                "userName": user_name,
                "amount": r["amount"],
                "method": r["method"],
                "status": r["status"],
                "proofUrl": r.get("proofUrl"),
                "createdAt": r["createdAt"].isoformat(),
                "updatedAt": r["updatedAt"].isoformat() if "updatedAt" in r else None
            })

        return jsonify(history), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
