from flask import Blueprint, jsonify, request
from datetime import datetime
from extensions import get_db
from decorators import token_required
from flask_cors import CORS
import logging

logger = logging.getLogger(__name__)
db = get_db()
loans_collection = db.loans
withdrawals_collection = db.withdrawals

withdrawals_bp = Blueprint('withdrawals', __name__, url_prefix='/api/withdrawals')
CORS(withdrawals_bp, origins="*", supports_credentials=True)

@withdrawals_bp.route('/balance', methods=['GET'])
@token_required
def get_balance(current_user):
    try:
        user_id = current_user['_id']  # corrected

        loans = list(loans_collection.find({
            "userId": user_id,
            "status": "disbursed"
        }))
        total_balance = sum(loan.get("amount", 0) for loan in loans)
        return jsonify({"balance": total_balance}), 200

    except Exception as e:
        logger.exception("Error fetching balance")
        return jsonify({"error": "Internal server error"}), 500

@withdrawals_bp.route('/history', methods=['GET'])
@token_required
def get_withdrawal_history(current_user):
    try:
        user_id = current_user['_id']  # corrected
        withdrawals = list(withdrawals_collection.find({'userId': user_id}).sort('requested_at', -1))
        result = []

        for w in withdrawals:
            result.append({
                "id": str(w['_id']),
                "requestedAt": w['requested_at'].isoformat(),
                "amount": w['amount'],
                "method": w['payment_method'],
                "accountName": w['account_name'],
                "accountNumber": w['account_number'],
                "status": w['status'],
                "adminNotes": w.get('admin_notes')
            })
        return jsonify(result), 200

    except Exception as e:
        logger.exception("Error fetching withdrawal history")
        return jsonify([]), 200  # Return empty array to avoid frontend .forEach error

@withdrawals_bp.route('', methods=['POST'])
@token_required
def create_withdrawal(current_user):
    try:
        user_id = current_user['_id']
        data = request.get_json()

        required_fields = ['amount', 'paymentMethod', 'accountName', 'accountNumber']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"{field} is required"}), 400

        try:
            amount = float(data['amount'])
            if amount <= 0:
                return jsonify({"error": "Amount must be greater than 0"}), 400
        except ValueError:
            return jsonify({"error": "Invalid amount"}), 400

        payment_method = data['paymentMethod']
        if payment_method not in ['MonCash', 'NatCash']:
            return jsonify({"error": "Invalid payment method"}), 400

        loans = list(loans_collection.find({
            "userId": user_id,
            "status": "disbursed"
        }))
        available_balance = sum(loan['amount'] for loan in loans)

        if amount > available_balance:
            return jsonify({"error": "Insufficient balance"}), 400

        withdrawal = {
            "userId": user_id,
            "amount": amount,
            "payment_method": payment_method,
            "account_name": data['accountName'],
            "account_number": data['accountNumber'],
            "status": "pending",
            "requested_at": datetime.utcnow(),
            "admin_notes": None
        }

        result = withdrawals_collection.insert_one(withdrawal)
        withdrawal['_id'] = str(result.inserted_id)
        withdrawal['requestedAt'] = withdrawal['requested_at'].isoformat()

        return jsonify({"message": "Withdrawal request submitted", "data": withdrawal}), 201

    except Exception as e:
        logger.exception("Error creating withdrawal")
        return jsonify({"error": "Failed to create withdrawal"}), 500
