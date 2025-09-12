from flask import Blueprint, request, jsonify
from flask_cors import CORS
from datetime import datetime
from bson import ObjectId
from extensions import get_db

# -----------------------------
# Blueprint
# -----------------------------
wallet_bp = Blueprint("wallet", __name__)

# -----------------------------
# CORS config for this blueprint
# -----------------------------
CORS(
    wallet_bp,
    resources={r"/*": {"origins": ["http://localhost:8000", "http://127.0.0.1:8000", "https://kredinou.com", "https://www.kredinou.com", "https://destinytch.com.ng", "https://www.destinytch.com.ng"]}},
    supports_credentials=True,
)

# -----------------------------
# Mongo collections
# -----------------------------
db = get_db()
wallets_collection = db.wallets
withdrawals_collection = db.withdrawals
loans_collection = db.loans
users_collection = db.users

# -----------------------------
# Utility: Sync wallets for all completed loans
# -----------------------------
def sync_wallet(user_id):
    loans = list(loans_collection.find({"userId": user_id, "disbursementStatus": "completed"}))
    if not loans:
        return [], 0  # No completed loans

    wallets = []
    total_balance = 0

    for loan in loans:
        wallet = wallets_collection.find_one({"userId": user_id, "loanId": loan["_id"]})
        if not wallet:
            # Create wallet if it doesn't exist
            wallet_data = {
                "userId": user_id,
                "loanId": loan["_id"],
                "balance": loan.get("amount", 0),  # default 0 if missing
                "currency": loan.get("currency", "HTG"),
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            wallets_collection.insert_one(wallet_data)
            balance = wallet_data["balance"]
        else:
            balance = wallet.get("balance", 0)

        total_balance += balance
        wallets.append({
            "loanId": str(loan["_id"]),
            "balance": balance,
            "currency": loan.get("currency", "HTG")
        })

    return wallets, total_balance


@wallet_bp.route("/", methods=["GET", "OPTIONS"])
def get_wallet():
    if request.method == "OPTIONS":
        return '', 200  # allow preflight

    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    wallets, total_balance = sync_wallet(user_id)
    loan_ids = [w["loanId"][:8] + "..." for w in wallets]  # trimmed IDs

    return jsonify({
        "balance": total_balance,  # always a number
        "loanIds": loan_ids
    })
@wallet_bp.route("/withdraw", methods=["POST", "OPTIONS"])
def make_withdrawal():
    if request.method == "OPTIONS":
        return '', 200

    data = request.get_json()
    user_id = data.get("userId")
    amount = data.get("amount")
    account_name = data.get("accountName")
    account_number = data.get("accountNumber")
    service = data.get("service")

    if not all([user_id, amount, account_name, account_number, service]):
        return jsonify({"error": "userId, amount, accountName, accountNumber, and service are required"}), 400

    try:
        amount = float(amount)
    except ValueError:
        return jsonify({"error": "Amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    wallets = list(wallets_collection.find({"userId": user_id}))
    if not wallets:
        return jsonify({"error": "No wallet found"}), 400

    total_balance = sum(w.get("balance", 0) for w in wallets)
    if amount > total_balance:
        return jsonify({"error": f"Amount exceeds total wallet balance ({total_balance})"}), 400

    remaining_amount = amount
    deducted_per_wallet = {}  # Track exactly how much is deducted from each wallet

    # Deduct across wallets
    for wallet in wallets:
        w_balance = wallet.get("balance", 0)
        if w_balance >= remaining_amount:
            new_balance = w_balance - remaining_amount
            wallets_collection.update_one(
                {"_id": wallet["_id"]},
                {"$set": {"balance": new_balance, "updatedAt": datetime.utcnow()}}
            )
            deducted_per_wallet[str(wallet["_id"])] = remaining_amount
            remaining_amount = 0
            break
        else:
            # Deduct entire wallet balance
            wallets_collection.update_one(
                {"_id": wallet["_id"]},
                {"$set": {"balance": 0, "updatedAt": datetime.utcnow()}}
            )
            deducted_per_wallet[str(wallet["_id"])] = w_balance
            remaining_amount -= w_balance

    # Create withdrawal record including exact wallet deductions
    withdrawal = {
        "userId": user_id,
        "walletDeductions": deducted_per_wallet,  # store exact amounts per wallet
        "amount": amount,
        "accountName": account_name,
        "accountNumber": account_number,
        "service": service,
        "status": "pending",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow()
    }
    result = withdrawals_collection.insert_one(withdrawal)

    # Recalculate total balance after deduction
    total_balance_after = sum(w.get("balance", 0) for w in wallets_collection.find({"userId": user_id}))

    return jsonify({
        "message": "Withdrawal request submitted successfully",
        "withdrawalId": str(result.inserted_id),
        "newBalance": total_balance_after
    }), 201

# -----------------------------
# Route: User withdrawal history
# -----------------------------
@wallet_bp.route("/withdrawals", methods=["GET"])
def withdrawal_history():
    user_id = request.args.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    try:
        withdrawals = withdrawals_collection.find({"userId": user_id}).sort("createdAt", -1)
        history = []
        for w in withdrawals:
            created_at = w.get("createdAt")
            loan_ids_display = [lid[:8] + "..." for lid in w.get("loanIds", [])]  # trim loan IDs
            history.append({
                "withdrawalId": str(w["_id"]),
                "loanIds": loan_ids_display,
                "amount": w.get("amount"),
                "accountName": w.get("accountName"),
                "accountNumber": w.get("accountNumber"),
                "service": w.get("service"),
                "status": w.get("status"),
                "createdAt": created_at.isoformat() if created_at else None
            })
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Admin Routes (Open, no auth)
# -----------------------------
@wallet_bp.route("/admin/withdrawals", methods=["GET", "OPTIONS"])
def admin_get_withdrawals():
    if request.method == "OPTIONS":
        return '', 200

    try:
        withdrawals = list(withdrawals_collection.find().sort("createdAt", -1))
        all_requests = []

        for w in withdrawals:
            created_at = w.get("createdAt")
            full_name = "N/A"
            loan_ids = []

            # Map wallet IDs to loans
            wallet_ids = list(w.get("walletDeductions", {}).keys())
            for wid in wallet_ids:
                wallet = wallets_collection.find_one({"_id": ObjectId(wid)})
                if wallet:
                    loan = loans_collection.find_one({"_id": wallet["loanId"]})
                    if loan:
                        # Store loan ID trimmed for display
                        loan_ids.append(str(loan["_id"])[:8] + "...")
                        # Get full name from loan document
                        if "user" in loan and "fullName" in loan["user"]:
                            full_name = loan["user"]["fullName"]

            all_requests.append({
                "withdrawalId": str(w["_id"]),
                "userId": str(w.get("userId")),
                "userFullName": full_name,
                "loanIds": loan_ids,
                "amount": w.get("amount"),
                "accountName": w.get("accountName"),
                "accountNumber": w.get("accountNumber"),
                "service": w.get("service"),
                "status": w.get("status"),
                "createdAt": created_at.isoformat() if created_at else None
            })

        return jsonify(all_requests)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@wallet_bp.route("/admin/withdrawals/<withdrawal_id>/approve", methods=["POST", "OPTIONS"])
def admin_approve_withdrawal(withdrawal_id):
    if request.method == "OPTIONS":
        return '', 200

    withdrawal = withdrawals_collection.find_one({"_id": ObjectId(withdrawal_id)})
    if not withdrawal:
        return jsonify({"error": "Withdrawal not found"}), 404

    withdrawals_collection.update_one(
        {"_id": withdrawal["_id"]},
        {"$set": {"status": "approved", "updatedAt": datetime.utcnow()}}
    )
    return jsonify({"message": "Withdrawal approved"})

@wallet_bp.route("/admin/withdrawals/<withdrawal_id>/reject", methods=["POST", "OPTIONS"])
def admin_reject_withdrawal(withdrawal_id):
    if request.method == "OPTIONS":
        return '', 200

    withdrawal = withdrawals_collection.find_one({"_id": ObjectId(withdrawal_id)})
    if not withdrawal:
        return jsonify({"error": "Withdrawal not found"}), 404

    # Restore only the amounts that were actually deducted
    for wallet_id, deducted_amount in withdrawal.get("walletDeductions", {}).items():
        wallet = wallets_collection.find_one({"_id": ObjectId(wallet_id)})
        if wallet:
            new_balance = wallet.get("balance", 0) + deducted_amount
            wallets_collection.update_one(
                {"_id": wallet["_id"]},
                {"$set": {"balance": new_balance, "updatedAt": datetime.utcnow()}}
            )

    withdrawals_collection.update_one(
        {"_id": withdrawal["_id"]},
        {"$set": {"status": "rejected", "updatedAt": datetime.utcnow()}}
    )

    # Recalculate total balance after restoring
    total_balance_after = sum(w.get("balance", 0) for w in wallets_collection.find({"userId": withdrawal.get("userId")}))

    return jsonify({
        "message": "Withdrawal rejected, balance restored",
        "newBalance": total_balance_after
    })
