from flask import Blueprint, jsonify
from flask_cors import CORS
from bson import ObjectId
from datetime import datetime
from extensions import get_db
from pymongo import ASCENDING

dashboard_bp = Blueprint("dashboard_bp", __name__)
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
# DASHBOARD SUMMARY
# ------------------------
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

# ------------------------
# DASHBOARD CHART DATA
# ------------------------
@dashboard_bp.route("/admin/dashboard/chart-data", methods=["GET"])
def dashboard_chart_data():
    try:
        # Aggregate loans by disbursed date
        loans_pipeline = [
            {"$match": {"disbursedAt": {"$ne": None}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$disbursedAt"}},
                "total": {"$sum": "$amount"}
            }},
            {"$sort": {"_id": ASCENDING}}
        ]
        loans_data = list(loans_col.aggregate(loans_pipeline))

        # Aggregate repayments by date
        repayments_pipeline = [
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
                "total": {"$sum": "$amount"}
            }},
            {"$sort": {"_id": ASCENDING}}
        ]
        repayments_data = list(repayments_col.aggregate(repayments_pipeline))

        # Aggregate withdrawals by createdAt
        withdrawals_pipeline = [
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt"}},
                "total": {"$sum": "$amount"}
            }},
            {"$sort": {"_id": ASCENDING}}
        ]
        withdrawals_data = list(withdrawals_col.aggregate(withdrawals_pipeline))

        return jsonify({
            "loans": loans_data,
            "repayments": repayments_data,
            "withdrawals": withdrawals_data
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
