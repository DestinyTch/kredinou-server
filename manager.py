from flask import Blueprint, jsonify
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
loans_col = db.loans
repayments_col = db.repayments
withdrawals_col = db.withdrawals

# Helper to serialize MongoDB documents
def serialize_doc(doc):
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        elif isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc

# ------------------------
# Dashboard summary endpoint
# ------------------------
@manager_bp.route("/dashboard/summary", methods=["GET"])
def dashboard_summary():
    total_users = users_col.count_documents({})
    total_loans = loans_col.count_documents({})
    total_loan_amount = sum([loan["amount"] for loan in loans_col.find({})])
    total_repayments = sum([rep["amount"] for rep in repayments_col.find({})])
    total_withdrawals = sum([wd["amount"] for wd in withdrawals_col.find({})])

    return jsonify({
        "total_users": total_users,
        "total_loans": total_loans,
        "total_loan_amount": total_loan_amount,
        "total_repayments": total_repayments,
        "total_withdrawals": total_withdrawals
    })

# ------------------------
# Dashboard chart endpoint
# ------------------------
@manager_bp.route("/dashboard/chart-data", methods=["GET"])
def dashboard_chart_data():
    """Return daily aggregates for loans, repayments, withdrawals"""
    def aggregate_by_date(col, field="amount"):
        pipeline = [
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt"}},
                "total": {"$sum": f"${field}"}
            }},
            {"$sort": {"_id": 1}}
        ]
        return list(col.aggregate(pipeline))

    loans_data = aggregate_by_date(loans_col, "amount")
    repayments_data = aggregate_by_date(repayments_col, "amount")
    withdrawals_data = aggregate_by_date(withdrawals_col, "amount")

    return jsonify({
        "loans": loans_data,
        "repayments": repayments_data,
        "withdrawals": withdrawals_data
    })
