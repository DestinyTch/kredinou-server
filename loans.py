from flask import Blueprint, jsonify, request
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from flask_jwt_extended import get_current_user
from extensions import get_db
from decorators import token_required
import logging
from flask_cors import CORS
# Initialize database connection
db = get_db()
loans_collection = db.loans
users_collection = db.users

# Create blueprint
loans_bp = Blueprint('loans', __name__, url_prefix='/api/loans')

from flask import jsonify, request
from datetime import datetime, timedelta
from pytz import timezone
import logging
from bson import ObjectId

# Configure logger
logger = logging.getLogger(__name__)
# --- CORS Preflight (no authentication) ---
# loans.py
from flask import Blueprint, jsonify, request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from bson import ObjectId
from flask_jwt_extended import get_current_user
from extensions import get_db
from decorators import token_required
import logging

# Configure logger
logger = logging.getLogger(__name__)

# Initialize database connection
db = get_db()
loans_collection = db.loans
users_collection = db.users

# Create blueprint
loans_bp = Blueprint('loans', __name__, url_prefix='/api/loans')
CORS(
    loans_bp,
    resources={r"/api/*": {"origins": [
        "https://destinytch.com.ng",  # production
        "http://localhost:8000",      # local dev
        "http://127.0.0.1:8000"       # alt dev
    ]}},
    supports_credentials=True
)

# --- Loan Application (requires authentication) ---
@loans_bp.route('/apply', methods=['POST'])
@token_required
def apply_for_loan(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Required fields
        required_fields = ['loanType', 'amount', 'repaymentPeriod', 'purpose']
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

        # Validate amount
        try:
            amount = float(data["amount"])
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount format"}), 400

        # Repayment period mapping
    period_map = {
    "1 Week": 7,
    "2 Weeks": 14,
    "1 Month": 30,
    "2 Months": 60,
    "3 Months": 90,
    "4 Months": 120,
    "5 Months": 150,
    "6 Months": 180
};


        raw_period = data.get("repaymentPeriod")
        days_to_add = None
        repayment_label = None

        if isinstance(raw_period, str) and raw_period.strip() in period_map:
            repayment_label = raw_period.strip()
            days_to_add = period_map[repayment_label]
        else:
            try:
                months_val = float(raw_period)
                if months_val <= 0:
                    raise ValueError("repayment months must be > 0")
                days_to_add = int(round(30 * months_val))
                if months_val == 0.25:
                    repayment_label = "1 Week"
                elif months_val == 0.5:
                    repayment_label = "2 Weeks"
                elif months_val.is_integer():
                    repayment_label = f"{int(months_val)} Month" + ("s" if months_val != 1 else "")
                else:
                    repayment_label = f"{months_val} Months"
            except Exception:
                return jsonify({"error": "Invalid repayment period format"}), 400

        # Application + due dates
        application_date = datetime.now(timezone.utc)
        due_date = application_date + timedelta(days=days_to_add)

        # Loan document
        loan = {
            "userId": current_user["_id"],
            "user": {
                "fullName": f"{current_user['first_name']} {current_user['last_name']}".strip(),
                "phone": current_user.get("phone", ""),
                "email": current_user.get("email", ""),
                "department": current_user.get("department", ""),
                "commune": current_user.get("commune", ""),
                "address": current_user.get("address", ""),
                "loanLimit": current_user.get("loan_limit", 0)
            },
            "loanType": data["loanType"],
            "amount": amount,
            "purpose": data["purpose"],
            "repaymentPeriod": repayment_label,
            "repaymentPeriodDays": days_to_add,
            "disbursementMethod": data.get("disbursementMethod"),
            "disbursementDetails": {},
            "applicationDate": application_date,
            "dueDate": due_date,
            "status": "pending",
            "repayments": [],
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "currency": "HTG"
        }

        # Handle disbursement details
        use_qr = data.get("useQrCode") or data.get("qrCodeUploaded") or (data.get("disbursementMethod") == "qr_code")
        if use_qr:
            qr_ref = data.get("qrCodeReference") or data.get("qrCodeUploadedReference")
            if qr_ref:
                loan["disbursementDetails"]["qrCode"] = qr_ref
            else:
                loan["disbursementDetails"]["qrCodeUploaded"] = True
        else:
            if data.get("disbursementMethod") == "natcash":
                if not all([data.get("natcashAccount"), data.get("natcashName")]):
                    return jsonify({"error": "Missing Natcash account details"}), 400
                loan["disbursementDetails"] = {
                    "accountNumber": data.get("natcashAccount"),
                    "accountName": data.get("natcashName")
                }
            elif data.get("disbursementMethod") == "moncash":
                if not all([data.get("moncashPhone"), data.get("moncashName")]):
                    return jsonify({"error": "Missing Moncash account details"}), 400
                loan["disbursementDetails"] = {
                    "accountNumber": data.get("moncashPhone"),
                    "accountName": data.get("moncashName")
                }

        # Insert into DB
        result = loans_collection.insert_one(loan)
        loan["_id"] = str(result.inserted_id)

        return jsonify({
            "message": "Loan application submitted successfully",
            "loan": {
                "_id": loan["_id"],
                "loanType": loan["loanType"],
                "amount": loan["amount"],
                "purpose": loan["purpose"],
                "repaymentPeriod": loan["repaymentPeriod"],
                "repaymentPeriodDays": loan["repaymentPeriodDays"],
                "disbursementMethod": loan["disbursementMethod"],
                "disbursementDetails": loan["disbursementDetails"],
                "applicationDate": loan["applicationDate"].isoformat(),
                "dueDate": loan["dueDate"].isoformat(),
                "status": loan["status"],
                "currency": loan["currency"],
                "user": loan["user"]
            }
        }), 201

    except Exception as e:
        logger.error(f"Loan creation error: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to process loan application"}), 500



# --- Loan history and details (unchanged, but ensure token_required supplies current_user) ---
@loans_bp.route("/history", methods=["GET"])
@token_required
def get_loan_history(current_user):
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, max(1, int(request.args.get('per_page', 100))))

        query = {"userId": current_user["_id"]}
        total_loans = loans_collection.count_documents(query)

        loans = list(loans_collection.find(
            query,
            {"userId": 0, "createdAt": 0, "updatedAt": 0}
        ).sort("applicationDate", -1)
          .skip((page - 1) * per_page)
          .limit(per_page))

        formatted_loans = []
        for loan in loans:
            formatted_loans.append({
                "_id": str(loan["_id"]),
                "loanType": loan["loanType"],
                "amount": loan["amount"],
                "purpose": loan.get("purpose", ""),
                "repaymentPeriod": loan.get("repaymentPeriod"),
                "disbursementMethod": loan.get("disbursementMethod"),
                "disbursementDetails": loan.get("disbursementDetails"),
                "applicationDate": loan["applicationDate"].isoformat(),
                "dueDate": loan["dueDate"].isoformat(),
                "status": loan["status"],
                "currency": loan.get("currency", "HTG")
            })

        return jsonify({
            "loans": formatted_loans,
            "pagination": {
                "total": total_loans,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_loans + per_page - 1) // per_page
            }
        }), 200

    except Exception as e:
        logger.error(f"Loan history error: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Failed to fetch loan history",
            "message": str(e)
        }), 500
@loans_bp.route("/active", methods=["GET"])
@token_required
def get_active_loan(current_user):
    try:
        # Define what counts as active
        active_statuses = ["approved", "disbursed"]

        loan = loans_collection.find_one(
            {"userId": current_user["_id"], "status": {"$in": active_statuses}},
            sort=[("applicationDate", -1)]
        )

        if not loan:
            return jsonify({"error": "No active loan"}), 404

        formatted_loan = {
            "_id": str(loan["_id"]),
            "loanType": loan["loanType"],
            "amount": loan["amount"],
            "purpose": loan.get("purpose", ""),
            "repaymentPeriod": loan.get("repaymentPeriod"),
            "disbursementMethod": loan.get("disbursementMethod"),
            "disbursementDetails": loan.get("disbursementDetails"),
            "applicationDate": loan["applicationDate"].isoformat(),
            "dueDate": loan["dueDate"].isoformat(),
            "status": loan["status"],
            "currency": loan.get("currency", "HTG")
        }

        return jsonify(formatted_loan), 200

    except Exception as e:
        logger.error(f"Active loan fetch error: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Failed to fetch active loan",
            "message": str(e)
        }), 500


@loans_bp.route("/<loan_id>", methods=["GET"])
@token_required
def get_loan_details(current_user, loan_id):
    try:
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        loan = loans_collection.find_one({
            "_id": ObjectId(loan_id),
            "userId": current_user["_id"]
        })

        if not loan:
            return jsonify({"error": "Loan not found"}), 404

        response_data = {
            "_id": str(loan["_id"]),
            "loanType": loan["loanType"],
            "amount": loan["amount"],
            "purpose": loan.get("purpose", ""),
            "repaymentPeriod": loan.get("repaymentPeriod"),
            "disbursementMethod": loan.get("disbursementMethod"),
            "disbursementDetails": loan.get("disbursementDetails"),
            "applicationDate": loan["applicationDate"].isoformat(),
            "dueDate": loan["dueDate"].isoformat(),
            "status": loan["status"],
            "repayments": loan.get("repayments", []),
            "currency": loan.get("currency", "HTG")
        }

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Loan details error: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Failed to fetch loan details",
            "message": str(e)
        }), 500





# Admin Endpoints
@loans_bp.route("/admin/all", methods=["GET"])
@token_required
def get_all_loans(current_user):
    """Admin endpoint to get all loans (paginated)"""
    try:
        # Verify admin role
        if current_user.get("role") != "admin":
            return jsonify({"error": "Unauthorized"}), 403

        # Pagination parameters
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 200))))
        status_filter = request.args.get('status')

        # Build query
        query = {}
        if status_filter:
            query["status"] = status_filter.lower()

        # Get total count
        total = loans_collection.count_documents(query)

        # Get paginated results with user details
        pipeline = [
            {"$match": query},
            {"$sort": {"applicationDate": -1}},
            {"$skip": (page - 1) * per_page},
            {"$limit": per_page},
            {"$lookup": {
                "from": "users",
                "localField": "userId",
                "foreignField": "_id",
                "as": "user"
            }},
            {"$unwind": "$user"},
            {"$project": {
                "_id": 1,
                "loanType": 1,
                "amount": 1,
                "purpose": 1,
                "status": 1,
                "applicationDate": 1,
                "dueDate": 1,
                "repaymentPeriod": 1,
                "disbursementMethod": 1,
                "user.first_name": 1,
                "user.last_name": 1,
                "user.email": 1
            }}
        ]

        loans = list(loans_collection.aggregate(pipeline))

        # Format response
        formatted_loans = []
        for loan in loans:
            formatted_loan = {
                "_id": str(loan["_id"]),
                "loanType": loan["loanType"],
                "amount": loan["amount"],
                "purpose": loan.get("purpose", ""),
                "status": loan["status"],
                "applicationDate": loan["applicationDate"].isoformat(),
                "dueDate": loan["dueDate"].isoformat(),
                "repaymentPeriod": loan["repaymentPeriod"],
                "disbursementMethod": loan["disbursementMethod"],
                "disbursementDetails": loan.get("disbursementDetails", {}),
                "applicantName": f"{loan['user']['first_name']} {loan['user']['last_name']}",
                "applicantEmail": loan["user"]["email"]
            }
            formatted_loans.append(formatted_loan)

        return jsonify({
            "loans": formatted_loans,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page
            }
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Failed to fetch loans",
            "message": str(e)

        }), 500





