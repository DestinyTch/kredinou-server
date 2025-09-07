from datetime import datetime
from flask import Blueprint, request, jsonify
from bson import ObjectId
from extensions import get_db
from decorators import token_required
import cloudinary
from cloudinary.uploader import upload as cloudinary_upload
from flask_cors import CORS


# Blueprint
repayments_bp = Blueprint("repayments", __name__)
CORS(repayments_bp, origins="*", supports_credentials=True)
# Mongo collections
# Initialize database connection
db = get_db()
repayments_collection = db.repayments
loans_collection = db.loans

# -----------------------------
# Route: Submit a repayment
# -----------------------------
@repayments_bp.route("/", methods=["POST"])
@token_required
def submit_repayment(current_user):
    loan_id = request.form.get("loanId")
    amount = request.form.get("amount")
    method = request.form.get("method")
    file = request.files.get("file")

    if not loan_id or not amount or not method or not file:
        return jsonify({"error": "loanId, amount, method, and proof file are required"}), 400

    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "Amount must be a number"}), 400

    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    loan = loans_collection.find_one({"_id": ObjectId(loan_id), "userId": current_user["_id"]})
    if not loan:
        return jsonify({"error": "Loan not found"}), 404

    if loan["status"] not in ["disbursed", "overdue"]:
        return jsonify({"error": "Cannot make payment on this loan"}), 400

    # Calculate pending amount
    verified_repayments = repayments_collection.aggregate([
        {"$match": {"loanId": ObjectId(loan_id), "status": "verified"}},
        {"$group": {"_id": None, "totalPaid": {"$sum": "$amount"}}}
    ])
    total_paid = 0
    for r in verified_repayments:
        total_paid = r.get("totalPaid", 0)

    principal = loan["amount"]
    interest = principal * 0.10
    late_fee = 0
    if datetime.utcnow() > loan["dueDate"]:
        months_late = ((datetime.utcnow() - loan["dueDate"]).days // 30) + 1
        late_fee = principal * 0.05 * months_late

    pending_amount = principal + interest + late_fee - total_paid
    if amount > pending_amount:
        return jsonify({"error": f"Amount exceeds pending balance ({pending_amount})"}), 400

    # Upload proof
    try:
        upload_result = cloudinary_upload(file)
        proof_url = upload_result.get("secure_url")
    except Exception as e:
        return jsonify({"error": f"Failed to upload proof: {str(e)}"}), 500

    repayment = {
        "loanId": ObjectId(loan_id),
        "userId": current_user["_id"],
        "amount": amount,
        "method": method,
        "reference": f"{current_user['first_name']} {current_user['last_name']}",
        "proofUrl": proof_url,
        "status": "pending_verification",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow()
    }

    result = repayments_collection.insert_one(repayment)

    return jsonify({
        "message": "Repayment submitted successfully",
        "repaymentId": str(result.inserted_id),
        "status": repayment["status"]
    }), 201

# -----------------------------
# Route: Get loan status
# -----------------------------
@repayments_bp.route("/status/<loan_id>", methods=["GET"])
@token_required
def loan_status(current_user, loan_id):
    try:
        loan = loans_collection.find_one({"_id": ObjectId(loan_id), "userId": current_user["_id"]})
        if not loan:
            return jsonify({"error": "Loan not found"}), 404

        # Calculate total verified repayments
        verified_repayments = repayments_collection.aggregate([
            {"$match": {"loanId": ObjectId(loan_id), "status": "verified"}},
            {"$group": {"_id": None, "totalPaid": {"$sum": "$amount"}}}
        ])
        total_paid = 0
        for r in verified_repayments:
            total_paid = r.get("totalPaid", 0)

        principal = loan["amount"]
        interest = principal * 0.10
        late_fee = 0
        if datetime.utcnow() > loan["dueDate"]:
            months_late = ((datetime.utcnow() - loan["dueDate"]).days // 30) + 1
            late_fee = principal * 0.05 * months_late

        pending_amount = principal + interest + late_fee - total_paid

        pending_verification_count = repayments_collection.count_documents({
            "loanId": ObjectId(loan_id),
            "status": "pending_verification"
        })

        return jsonify({
            "pendingAmount": pending_amount,
            "totalRepaid": total_paid,
            "dueDate": loan["dueDate"].isoformat(),
            "loanStatus": loan["status"],
            "pendingVerification": pending_verification_count
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Route: List all repayments for user
# -----------------------------
@repayments_bp.route("/history", methods=["GET"])
@token_required
def repayment_history(current_user):
    try:
        repayments = repayments_collection.find({"userId": current_user["_id"]}).sort("createdAt", -1)
        history = []
        for r in repayments:
            history.append({
                "repaymentId": str(r["_id"]),
                "loanId": str(r["loanId"]),
                "amount": r["amount"],
                "method": r["method"],
                "status": r["status"],
                "proofUrl": r.get("proofUrl"),
                "createdAt": r["createdAt"].isoformat()
            })
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
