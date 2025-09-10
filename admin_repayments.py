

# -----------------------------
# WITHDRAWALS ROUTES
# -----------------------------
@admin_repayments_bp.route("/withdrawals", methods=["GET"])

def list_withdrawals():
    try:
        withdrawals = withdrawals_collection.find().sort("requested_at", -1)
        results = []
        for w in withdrawals:
            user = users_collection.find_one({"_id": w["userId"]})
            user_name = f"{user.get('first_name','')} {user.get('last_name','')}" if user else "Unknown"
            results.append({
                "withdrawalId": str(w["_id"]),
                "userId": str(w["userId"]),
                "userName": user_name,
                "email": user.get("email") if user else None,
                "phone": user.get("phone") if user else None,
                "balance": user.get("balance",0) if user else 0,
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

@admin_repayments_bp.route("/withdrawals/<withdrawal_id>", methods=["PATCH"])

def update_withdrawal(, withdrawal_id):
    try:
        data = request.json
        status = data.get("status")
        reason = data.get("reason", "")
        withdrawal = withdrawals_collection.find_one({"_id": ObjectId(withdrawal_id)})
        if not withdrawal:
            return jsonify({"error": "Withdrawal not found"}), 404

        if withdrawal["status"] != "pending":
            return jsonify({"error": "Withdrawal is not pending"}), 400

        updates = {"status": status, "updated_at": datetime.utcnow()}
        if status == "rejected":
            updates["admin_notes"] = reason
        elif status == "approved":
            user = users_collection.find_one({"_id": withdrawal["userId"]})
            if user:
                new_balance = max(user.get("balance",0) - withdrawal["amount"], 0)
                users_collection.update_one({"_id": withdrawal["userId"]}, {"$set": {"balance": new_balance}})

        withdrawals_collection.update_one({"_id": ObjectId(withdrawal_id)}, {"$set": updates})
        withdrawal.update(updates)

        return jsonify({
            "withdrawalId": str(withdrawal["_id"]),
            "status": withdrawal["status"],
            "adminNotes": withdrawal.get("admin_notes")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_repayments_bp.route("/withdrawals/history", methods=["GET"])

def withdrawals_history():
    try:
        withdrawals = withdrawals_collection.find().sort("requested_at", -1)
        history = []
        for w in withdrawals:
            user = users_collection.find_one({"_id": w["userId"]})
            user_name = f"{user.get('first_name','')} {user.get('last_name','')}" if user else "Unknown"
            history.append({
                "withdrawalId": str(w["_id"]),
                "userId": str(w["userId"]),
                "userName": user_name,
                "email": user.get("email") if user else None,
                "phone": user.get("phone") if user else None,
                "balance": user.get("balance",0) if user else 0,
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
