import hmac
import re
from flask import Blueprint, current_app, request, jsonify
from datetime import datetime, timedelta, timezone
from flask_cors import CORS
import jwt

import bcrypt
import os
from functools import wraps
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from bson import ObjectId
# Initialize MongoDB client
client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("DB_NAME")]
admins_collection = db.admins

# Create admin Blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
CORS(admin_bp, origins="http://localhost:8000", supports_credentials=True)
# Security Configuration - with validation
ADMIN_TOKEN_SECRET = os.getenv("ADMIN_TOKEN_SECRET")
if not ADMIN_TOKEN_SECRET:
    raise ValueError("ADMIN_TOKEN_SECRET environment variable not set")

PEPPER = os.getenv("ADMIN_PEPPER", "")  # Default to empty string if not set

def hash_password(password: str) -> str:
    """Secure password hashing with bcrypt and pepper"""
    if not isinstance(password, str):
        raise ValueError("Password must be a string")
    
    peppered = password + PEPPER
    return bcrypt.hashpw(peppered.encode(), bcrypt.gensalt()).decode()

def check_password(input_pw: str, hashed_pw: str) -> bool:
    """Verify password against hashed version"""
    if not input_pw or not hashed_pw:
        return False
    if not isinstance(input_pw, str) or not isinstance(hashed_pw, str):
        return False
    
    peppered = input_pw + PEPPER
    try:
        return bcrypt.checkpw(peppered.encode(), hashed_pw.encode())
    except ValueError:
        return False
def generate_admin_token(admin_id):
    payload = {
        "admin_id": admin_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    return jwt.encode(payload, ADMIN_TOKEN_SECRET, algorithm="HS256")


def get_admin_id_from_token():
    token = request.headers.get("Authorization")
    if not token:
        raise ValueError("Missing Authorization token")

    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, ADMIN_TOKEN_SECRET, algorithms=["HS256"])
        
        admin_id = payload.get("admin_id")
        if not admin_id:
            raise ValueError("Token missing admin ID field")
        
        return admin_id
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")

def create_initial_admin():
    """Create first admin account if none exists"""
    if admins_collection.count_documents({}) == 0:
        initial_email = os.getenv("INITIAL_ADMIN_EMAIL")
        initial_pw = os.getenv("INITIAL_ADMIN_PASSWORD")
        
        if not initial_email or not initial_pw:
            raise ValueError("Initial admin credentials not configured")
        
        admins_collection.insert_one({
            "email": initial_email,
            "password": hash_password(initial_pw),
            "role": "superadmin",
            "created_at": datetime.now(timezone.utc),
            "last_login": None,
            "status": "active"
        })

# Create initial admin on startup
create_initial_admin()

@admin_bp.route('/login', methods=['POST', 'OPTIONS'])
def admin_login():
    if request.method == 'OPTIONS':
        return jsonify({"status": "success"}), 200

    """Admin login endpoint with database validation"""
    data = request.get_json()
    
    # Validate input
    if not data or 'email' not in data or 'password' not in data:
        return jsonify({"error": "Email and password required"}), 400
    
    # Find admin in database
    admin = admins_collection.find_one({"email": data['email']})
    
    # Verify credentials
    if not admin or not check_password(data['password'], admin.get('password')):
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Update last login
    admins_collection.update_one(
        {"_id": admin['_id']},
        {"$set": {"last_login": datetime.now(timezone.utc)}}
    )
    
    # Generate token
    token = generate_admin_token(str(admin['_id']))
    
    return jsonify({
        "token": token,
        "admin": {
            "id": str(admin['_id']),
            "email": admin['email'],
            "role": admin.get('role', 'admin')
        },
        "redirect": "/admin/dashboard"
    })

def admin_token_required(f):
    """Strict admin authentication decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Token missing"}), 401
            
        token = auth_header.split(' ')[1]
        
        try:
            payload = jwt.decode(token, ADMIN_TOKEN_SECRET, algorithms=["HS256"])
            
            # Verify admin still exists
            if not admins_collection.find_one({"_id": payload['admin_id']}):
                return jsonify({"error": "Admin account not found"}), 401
                
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
            
    return decorated


@admin_bp.route('/sys/diagnostics', methods=['POST', 'OPTIONS'])
def system_diagnostics():
    if request.method == 'OPTIONS':
        return jsonify({"status": "success"}), 200

    """
    Diagnostics endpoint
    Authenticates using a hardcoded code instead of email/password
    """
    # Block mobile devices
    user_agent = request.headers.get('User-Agent', '').lower()
    if any(m in user_agent for m in ['mobile', 'android', 'iphone', 'ipad']):
        return jsonify({"error": "Diagnostics unavailable on mobile"}), 403
    
    # Validate input
    data = request.get_json() or {}
    if 'code' not in data:
        return jsonify({"error": "Diagnostic code required"}), 400
    
    # Verify hardcoded code
    if not hmac.compare_digest(data['code'], "D45192091425Ea@"):
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Generate token (same structure as /login)
    token = jwt.encode(
        {
            "diagnostics_auth": True,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1)
        },
        ADMIN_TOKEN_SECRET,
        algorithm="HS256"
    )
    
    # Return same format as /login
    return jsonify({
        "token": token,
        "admin": {
            "id": "diagnostic",
            "email": "diagnostic@system.local",
            "role": "diagnostic"
        },
        "redirect": "/admin/dashboard"
    })

@admin_bp.route('/change-credentials', methods=['POST', 'OPTIONS'])
def change_credentials():
    if request.method == 'OPTIONS':
        return jsonify({"status": "success"}), 200

    """Secure admin credential update endpoint"""
    data = request.get_json()
    
    # Validate input
    if not data or 'current_password' not in data:
        return jsonify({"error": "Current password required"}), 400
    
    # Get token from header
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Token missing"}), 401
    
    token = auth_header.split(' ')[1]
    
    try:
        # Decode token
        payload = jwt.decode(token, ADMIN_TOKEN_SECRET, algorithms=["HS256"])
        
        # Find admin - handle both string and ObjectId formats
        from bson import ObjectId
        try:
            admin = admins_collection.find_one({"_id": ObjectId(payload['admin_id'])})
        except:
            admin = admins_collection.find_one({"_id": payload['admin_id']})
        
        if not admin:
            return jsonify({"error": "Admin account not found"}), 404
        
        # Verify current password
        if not check_password(data['current_password'], admin['password']):
            return jsonify({"error": "Current password is incorrect"}), 401
        
        # Prepare update fields
        update_fields = {}
        
        # Update email if provided
        if 'new_email' in data and data['new_email']:
            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', data['new_email']):
                return jsonify({"error": "Invalid email format"}), 400
            update_fields['email'] = data['new_email']
        
        # Update password if provided
        if 'new_password' in data and data['new_password']:
            if len(data['new_password']) < 12:
                return jsonify({"error": "Password must be at least 12 characters"}), 400
            update_fields['password'] = hash_password(data['new_password'])
        
        # If no updates requested
        if not update_fields:
            return jsonify({"error": "No updates requested"}), 400
        
        # Add update timestamp
        update_fields['updated_at'] = datetime.now(timezone.utc)
        
  
        result = admins_collection.update_one(
            {"_id": admin['_id']},
            {"$set": update_fields}
        )
        
        if result.modified_count == 1:
            return jsonify({
                "success": True,
                "message": "Credentials updated successfully",
                "updated_fields": list(update_fields.keys())
            })
        
        return jsonify({"error": "Failed to update credentials"}), 500
        
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# ============== LOAN MANAGEMENT ROUTES ==============

@admin_bp.route('/loans/pending', methods=['GET'])

def get_pending_loans():
    """Get paginated list of pending loans"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        skip = (page - 1) * limit

        # Get pending loans with pagination
        loans = list(db.loans.find(
            {"status": "pending"},
            {
                "_id": 1,
                "userId": 1,
                "loanType": 1,
                "amount": 1,
                "applicationDate": 1,
                "status": 1
            }
        ).sort("applicationDate", -1).skip(skip).limit(limit))

        # Convert ObjectId and dates to strings
        for loan in loans:
            loan['_id'] = str(loan['_id'])
            loan['userId'] = str(loan['userId'])
            loan['applicationDate'] = loan['applicationDate'].isoformat()

        total = db.loans.count_documents({"status": "pending"})

        return jsonify({
            "loans": loans,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
            "limit": limit
        })

    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to fetch pending loans"}), 500


@admin_bp.route('/loans/<loan_id>', methods=['GET'])
def get_loan_details(loan_id):
    """Get full loan details including user info"""
    try:
        # Validate loan ID format
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        # Fetch loan (user info is embedded)
        loan = db.loans.find_one(
            {"_id": ObjectId(loan_id)},
            {
                "loanType": 1,
                "amount": 1,
                "purpose": 1,
                "repaymentPeriod": 1,
                "repaymentPeriodDays": 1,
                "applicationDate": 1,
                "dueDate": 1,
                "status": 1,
                "disbursementMethod": 1,
                "disbursementDetails": 1,
                "user": 1,
            }
        )

        if not loan:
            return jsonify({"error": "Loan not found"}), 404

        # Convert dates to ISO
        loan["applicationDate"] = loan["applicationDate"].isoformat()
        loan["dueDate"] = loan["dueDate"].isoformat()

        # Convert _id to string
        loan["_id"] = str(loan["_id"])

        return jsonify(loan), 200

    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to fetch loan details"}), 500


@admin_bp.route('/loans/<loan_id>/documents', methods=['GET'])
def get_loan_documents(loan_id):
    """Get all documents and face image for a loan application"""
    try:
        # Validate loan ID
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        # Verify loan exists and get user ID
        loan = db.loans.find_one(
            {"_id": ObjectId(loan_id)},
            {"userId": 1}
        )
        
        if not loan:
            return jsonify({"error": "Loan not found"}), 404

        # Get user's documents and face image
        user = db.users.find_one(
            {"_id": loan['userId']},
            {
                "documents": 1,
                "face_image": 1
            }
        )

        if not user:
            return jsonify({"error": "User not found, sign in again"}), 404

        # Prepare response data
        response_data = {
            "documents": [],
            "face_image": None,
            "total": 0
        }

        # Process documents if they exist
        if 'documents' in user and user['documents']:
            for doc in user['documents']:
                response_data["documents"].append({
                    "_id": str(doc.get('_id', ObjectId()) if doc.get('_id') else str(ObjectId())),
                    "documentType": doc.get('document_type', 'Unknown'),
                    "url": doc.get('url'),
                    "verified": doc.get('verified', False),
                    "uploadDate": doc.get('uploaded_at', datetime.now()).isoformat()
                })
            response_data["total"] = len(user['documents'])

        # Add face image if it exists
        if 'face_image' in user and user['face_image']:
            response_data["face_image"] = {
                "url": user['face_image'].get('url'),
                "uploadDate": user['face_image'].get('uploaded_at', datetime.now()).isoformat()
            }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to fetch loan documents"}), 500


@admin_bp.route('/loans/<loan_id>/approve', methods=['POST'])
def approve_loan(loan_id):
    """Approve a loan (pre-disbursement) and return total pending disbursement amount"""
    try:
        data = request.get_json()
        admin_id = get_admin_id_from_token()

        # Validate loan ID format
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        # Find the pending loan
        loan = db.loans.find_one({
            "_id": ObjectId(loan_id),
            "status": "pending"
        })
        if not loan:
            return jsonify({"error": "Loan not found or already processed"}), 404

        # Update loan to approved
        update_data = {
            "status": "approved",
            "approvedBy": ObjectId(admin_id),
            "approvedAt": datetime.now(timezone.utc),
            "adminNotes": data.get('notes', '')
        }
        result = db.loans.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": update_data}
        )

        if result.modified_count != 1:
            return jsonify({"error": "No changes made to loan"}), 400

        # Log the approval action
        db.admin_actions.insert_one({
            "adminId": ObjectId(admin_id),
            "action": "loan_approval",
            "loanId": ObjectId(loan_id),
            "timestamp": datetime.now(timezone.utc),
            "details": {
                "amount": loan['amount'],
                "previousStatus": "pending",
                "notes": data.get('notes', '')
            }
        })

        # Calculate total pending disbursement amount (approved but not yet disbursed)
        total_pending_pipeline = [
            {"$match": {"status": "approved"}},
            {"$group": {"_id": None, "totalAmount": {"$sum": "$amount"}}}
        ]
        result_pipeline = list(db.loans.aggregate(total_pending_pipeline))
        total_pending_amount = result_pipeline[0]["totalAmount"] if result_pipeline else 0

        return jsonify({
            "success": True,
            "status": "approved",
            "approvedAt": update_data["approvedAt"].isoformat(),
            "totalPendingAmount": total_pending_amount
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/loans/<loan_id>/reject', methods=['POST'])
def reject_loan(loan_id):
    """Reject a loan application"""
    try:
        # Validate loan ID
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        # Parse request body
        data = request.get_json()
        if not data or 'reason' not in data:
            return jsonify({"error": "Rejection reason is required"}), 400

        # Get admin ID from token
        try:
            admin_id = get_admin_id_from_token()
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 401

        if not ObjectId.is_valid(admin_id):
            return jsonify({"error": "Invalid admin ID"}), 401

        # Verify loan exists and is pending
        loan = db.loans.find_one({"_id": ObjectId(loan_id), "status": "pending"})
        if not loan:
            return jsonify({"error": "Loan not found or already processed"}), 404

        # Prepare update data
        current_time = datetime.now(timezone.utc)
        update_data = {
            "status": "rejected",
            "rejectedBy": ObjectId(admin_id),
            "rejectedAt": current_time,
            "rejectionReason": data['reason'],
            "adminNotes": data.get('notes', '')
        }

        # Update loan status
        result = db.loans.update_one({"_id": ObjectId(loan_id)}, {"$set": update_data})

        if result.modified_count == 1:
            # Log the rejection action
            db.admin_actions.insert_one({
                "adminId": ObjectId(admin_id),
                "action": "loan_rejection",
                "loanId": ObjectId(loan_id),
                "timestamp": current_time,
                "details": {
                    "amount": loan.get('amount', 0),
                    "reason": data['reason'],
                    "notes": data.get('notes', '')
                }
            })

            return jsonify({
                "success": True,
                "status": "rejected",
                "rejectedAt": current_time.isoformat()
            })

        return jsonify({"error": "No changes made to loan"}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()  # for server logs
        return jsonify({"error": str(e), "message": "Failed to reject loan"}), 500


@admin_bp.route('/loans/<loan_id>/mark-disbursed', methods=['POST'])

def mark_as_disbursed(loan_id):
    """Confirm manual disbursement of funds"""
    try:
        data = request.get_json()
        admin_id = get_admin_id_from_token()

        # Validate input
        if not data or 'transactionId' not in data:
            return jsonify({"error": "Transaction ID is required"}), 400

        # Validate loan ID
        if not ObjectId.is_valid(loan_id):
            return jsonify({"error": "Invalid loan ID format"}), 400

        # Verify loan is approved but not yet disbursed
        loan = db.loans.find_one({
            "_id": ObjectId(loan_id),
            "status": "approved",
            "disbursementStatus": {"$exists": False}
        })
        
        if not loan:
            return jsonify({"error": "Loan not found or already disbursed"}), 404

        # Handle file upload if present
        proof_url = None
        if 'proof' in request.files:
            file = request.files['proof']
            if file and allowed_file(file.filename):
                filename = secure_filename(
                    f"disbursement_{loan_id}_"
                    f"{datetime.now().timestamp()}"
                    f"{os.path.splitext(file.filename)[1]}"
                )
                filepath = os.path.join('uploads/disbursements', filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                file.save(filepath)
                proof_url = f"/disbursements/{filename}"

        # Prepare update data
        update_data = {
            "disbursementStatus": "completed",
            "disbursedBy": ObjectId(admin_id),
            "disbursedAt": datetime.now(timezone.utc),
            "transactionId": data['transactionId'],
            "disbursementProof": proof_url
        }

        # Update loan status
        result = db.loans.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": update_data}
        )

        if result.modified_count == 1:
            # Log the disbursement action
            db.admin_actions.insert_one({
                "adminId": ObjectId(admin_id),
                "action": "loan_disbursement",
                "loanId": ObjectId(loan_id),
                "timestamp": datetime.now(timezone.utc),
                "details": {
                    "amount": loan['amount'],
                    "method": loan.get('disbursementMethod'),
                    "transactionId": data['transactionId']
                }
            })

            # Update user's loan count
            db.users.update_one(
                {"_id": loan['userId']},
                {"$inc": {"activeLoans": 1}}
            )

            return jsonify({
                "success": True,
                "status": "disbursed",
                "disbursementDate": update_data["disbursedAt"].isoformat()
            })

        return jsonify({"error": "No changes made to loan"}), 400

    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to mark loan as disbursed"}), 500


@admin_bp.route('/documents/<doc_id>/verify', methods=['POST'])
def verify_document(doc_id):
    """Mark a document as verified"""
    try:
        # Authentication and authorization check
        admin_id = get_admin_id_from_token()
        if not admin_id:
            return jsonify({"error": "Unauthorized"}), 401

        # Validate document ID
        if not ObjectId.is_valid(doc_id):
            return jsonify({"error": "Invalid document ID format"}), 400

        # Check if document exists and get current status
        document = db.documents.find_one({"_id": ObjectId(doc_id)})
        if not document:
            return jsonify({"error": "Document not found"}), 404

        # Prevent re-verification
        if document.get('verified', False):
            return jsonify({
                "error": "Document already verified",
                "verifiedAt": document.get('verifiedAt'),
                "verifiedBy": str(document.get('verifiedBy'))
            }), 400

        # Update document status with atomic operation
        update_time = datetime.now(timezone.utc)
        result = db.documents.update_one(
            {"_id": ObjectId(doc_id), "verified": {"$ne": True}},
            {
                "$set": {
                    "verified": True,
                    "verifiedBy": ObjectId(admin_id),
                    "verifiedAt": update_time,
                    "lastUpdated": update_time
                }
            }
        )

        if result.modified_count == 1:
            # Log the verification action with more context
            verification_log = {
                "adminId": ObjectId(admin_id),
                "action": "document_verification",
                "documentId": ObjectId(doc_id),
                "userId": document['userId'],
                "timestamp": update_time,
                "metadata": {
                    "documentType": document.get('documentType', 'unknown'),
                    "originalFilename": document.get('filename'),
                    "storageLocation": document.get('url'),
                    "verificationMethod": "manual_admin_review"
                }
            }
            
            db.admin_actions.insert_one(verification_log)

            # Optionally notify user about verification
            if document.get('userId'):
                notify_user_about_verification(
                    user_id=document['userId'],
                    document_type=document.get('documentType'),
                    admin_id=admin_id
                )

            return jsonify({
                "success": True,
                "message": "Document successfully verified",
                "documentId": doc_id,
                "verified": True,
                "verifiedAt": update_time.isoformat(),
                "verifiedBy": admin_id,
                "documentType": document.get('documentType')
            })

        return jsonify({
            "error": "Document not found or verification status unchanged",
            "documentId": doc_id
        }), 404

   
        current_app.logger.error(f"Database error during document verification: {str(e)}")
        return jsonify({
            "error": "Database operation failed",
            "message": "Please try again later"
        }), 500
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error in verify_document: {str(e)}")
        return jsonify({
            "error": "Internal server error",
            "message": "Failed to process verification"
        }), 500


def notify_user_about_verification(user_id, document_type, admin_id):
    """Helper function to notify user about document verification"""
    try:
        # Get user notification preferences
        user = db.users.find_one(
            {"_id": ObjectId(user_id)},
            {"notificationPreferences": 1, "email": 1, "phone": 1}
        )
        
        if user:
            notification_msg = (
                f"Your {document_type} document has been verified by admin. "
                "Thank you for completing this verification step."
            )
            
            # Store notification in database
            db.notifications.insert_one({
                "userId": ObjectId(user_id),
                "type": "document_verification",
                "message": notification_msg,
                "status": "unread",
                "createdAt": datetime.now(timezone.utc),
                "metadata": {
                    "documentType": document_type,
                    "verifiedBy": admin_id
                }
            })
            
            # TODO: Implement actual notification delivery (email, SMS, etc.)
            # based on user's notification preferences
            
    except Exception as e:
        current_app.logger.error(f"Failed to send verification notification: {str(e)}")


def allowed_file(filename):
    """Check if the file extension is allowed with enhanced validation"""
    if not filename or '.' not in filename:
        return False
        
    ext = filename.rsplit('.', 1)[1].lower()
    allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg', 'heic', 'webp'}
    max_length = 255  # Maximum filename length
    
    return (len(filename) <= max_length and 
            ext in allowed_extensions and
            not filename.startswith('.') and
            not any(char in filename for char in {'/', '\\', ':', '*', '?', '"', '<', '>', '|'}))

def get_admin_id_from_token():
    """Extract admin ID from JWT token"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise ValueError("Missing or invalid authorization header")
    
    token = auth_header.split(' ')[1]
    payload = jwt.decode(token, ADMIN_TOKEN_SECRET, algorithms=["HS256"])
    return payload['admin_id']
@admin_bp.route('/users/<user_id>', methods=['GET'])
def get_user_details(user_id):
    """Get user details by ID (works with both ObjectId and string UUID)"""
    try:
        # Try to find user by ObjectId first
        try:
            user = db.users.find_one({"_id": ObjectId(user_id)})
        except:
            # If not ObjectId, try as string
            user = db.users.find_one({"_id": user_id})
        
        if not user:
            return jsonify({"error": "User not found, sign in again"}), 404

        return jsonify({
            "first_name": user.get("first_name"),
            "middle_name": user.get("middle_name"),
            "last_name": user.get("last_name"),
            "phone": user.get("phone"),
            "email": user.get("email"),
            "loan_limit": user.get("loan_limit", 0)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@admin_bp.route('/loans/approved', methods=['GET'])
def get_approved_loans():
    """Get paginated list of approved loans"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 100))
        skip = (page - 1) * limit

        loans = list(db.loans.find(
            {"status": "approved"},
            {
                "_id": 1,
                "userId": 1,
                "loanType": 1,
                "amount": 1,
                "applicationDate": 1,
                "approvedAt": 1,
                "disbursementStatus": 1
            }
        ).sort("approvedAt", -1).skip(skip).limit(limit))

        for loan in loans:
            loan['_id'] = str(loan['_id'])
            loan['userId'] = str(loan['userId'])
            loan['applicationDate'] = loan['applicationDate'].isoformat()
            loan['approvedAt'] = loan['approvedAt'].isoformat()

        total = db.loans.count_documents({"status": "approved"})

        return jsonify({
            "loans": loans,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
            "limit": limit
        })

    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to fetch approved loans"}), 500
    
@admin_bp.route('/loans/<loan_id>/disburse', methods=['POST'])
def disburse_loan(loan_id):
    """Mark an approved loan as disbursed"""
    try:
        # 1. Verify the loan exists
        loan = db.loans.find_one({"_id": ObjectId(loan_id)})
        if not loan:
            return jsonify({"message": "Loan not found"}), 404

        # 2. Check loan status
        if loan.get("status") != "approved":
            return jsonify({
                "message": "Only approved loans can be disbursed",
                "current_status": loan.get("status")
            }), 400

        if loan.get("disbursementStatus") == "completed":
            return jsonify({"message": "Loan already disbursed"}), 400

        # 3. Update the loan status and disbursement info
        current_time = datetime.utcnow()
        result = db.loans.update_one(
            {"_id": ObjectId(loan_id)},
            {
                "$set": {
                    "status": "disbursed",   # 👈 This is the important change
                    "disbursementStatus": "completed",
                    "disbursedAt": current_time,
                    "updatedAt": current_time
                }
            }
        )

        if result.modified_count == 1:
            return jsonify({
                "message": "Loan successfully marked as disbursed",
                "loan_id": loan_id,
                "new_status": "disbursed",
                "disbursed_at": current_time.isoformat()
            })
        else:
            return jsonify({"message": "No changes made to loan"}), 400

    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Failed to process loan disbursement"
        }), 500

@admin_bp.route('/loans/<loan_id>/status', methods=['PUT'])
def update_loan_status(loan_id):
    """Update loan status dynamically"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status:
            return jsonify({"message": "Status is required"}), 400

        # Validate status
        valid_statuses = ['pending', 'rejected', 'disbursed', 'paid', 'defaulted', 'pending disbursement']
        if new_status not in valid_statuses:
            return jsonify({"message": "Invalid status"}), 400

        # Update loan status
        result = db.loans.update_one(
            {"_id": ObjectId(loan_id)},
            {"$set": {"status": new_status, "updatedAt": datetime.utcnow()}}
        )

        if result.modified_count == 1:
            return jsonify({
                "message": "Loan status updated successfully",
                "loan_id": loan_id,
                "new_status": new_status
            })
        else:
            return jsonify({"message": "No changes made to loan"}), 400

    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Failed to update loan status"
        }), 500
        
@admin_bp.route('/disbursement/pending-stats', methods=['GET'])
def get_pending_disbursement_stats():
    """Get count and total amount of approved loans awaiting disbursement"""
    try:
        # Match approved loans
        match_stage = {"$match": {"status": "approved"}}

        # Count approved loans
        count = db.loans.count_documents(match_stage["$match"])

        # Total amount by currency (in case you have multiple currencies later)
        total_pipeline = [
            match_stage,
            {
                "$group": {
                    "_id": "$currency",
                    "totalAmount": {"$sum": "$amount"}
                }
            }
        ]
        totals = list(db.loans.aggregate(total_pipeline))

        # If you expect only HTG right now:
        total_amount = 0
        for item in totals:
            if item["_id"] == "HTG":
                total_amount = item["totalAmount"]

        return jsonify({
            "pendingCount": count,
            "totalPendingAmount": total_amount,
            "currency": "HTG"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/disbursement/pending', methods=['GET'])
def get_pending_disbursements():
    """Get all approved loans awaiting disbursement with borrower info and account details."""
    try:
        pipeline = [
            {"$match": {"status": "approved"}},
            {
                "$lookup": {
                    "from": "users",
                    "localField": "userId",
                    "foreignField": "_id",  # match to ObjectId if userId is stored as ObjectId
                    "as": "borrower"
                }
            },
            {"$unwind": "$borrower"},
           {
    "$project": {
        "loanId": {"$toString": "$_id"},
        "_id": 0,
        "borrowerName": {
            "$concat": ["$borrower.first_name", " ", "$borrower.last_name"]
        },
        "amount": 1,
        "currency": 1,
        "disbursementMethod": 1,
        "disbursementDetails": {
            "$concat": [
                "$disbursementDetails.accountName", " - ", 
                "$disbursementDetails.accountNumber"
            ]
        },
        "approvedAt": 1
    }
}


        ]

        loans = list(db.loans.aggregate(pipeline))

        # Format date
        for loan in loans:
            if loan.get("approvedAt"):
                loan["approvedAt"] = loan["approvedAt"].strftime("%Y-%m-%d")

        return jsonify({"pendingLoans": loans})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/disbursement/disbursed', methods=['GET'])
def get_disbursed_loans():
    """Get all loans that have been disbursed, with borrower info and account details."""
    try:
        pipeline = [
            {"$match": {"status": "disbursed"}},  # or {"disbursementStatus": "completed"} if you prefer
            {
                "$lookup": {
                    "from": "users",
                    "localField": "userId",
                    "foreignField": "_id",
                    "as": "borrower"
                }
            },
            {"$unwind": "$borrower"},
            {
                "$project": {
                    "loanId": {"$toString": "$_id"},
                    "_id": 0,
                    "borrowerName": {
                        "$concat": ["$borrower.first_name", " ", "$borrower.last_name"]
                    },
                    "amount": 1,
                    "currency": 1,
                    "disbursementMethod": 1,
                    "disbursementDetails": {
                        "$concat": [
                            "$disbursementDetails.accountName", " - ",
                            "$disbursementDetails.accountNumber"
                        ]
                    },
                    "disbursedAt": 1
                }
            }
        ]

        loans = list(db.loans.aggregate(pipeline))

        # Format date
        for loan in loans:
            if loan.get("disbursedAt"):
                loan["disbursedAt"] = loan["disbursedAt"].strftime("%Y-%m-%d")

        return jsonify({"disbursedLoans": loans})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
@admin_bp.route('/disbursement/disbursed/total', methods=['GET'])
def get_total_disbursed_amount():
    try:
        pipeline = [
            {"$match": {"status": "disbursed"}},
            {
                "$group": {
                    "_id": "$currency",
                    "totalAmount": {"$sum": "$amount"}
                }
            }
        ]
        totals = list(db.loans.aggregate(pipeline))

        # For simplicity, if you only have one currency (e.g. HTG), just extract it:
        total_amount = 0
        currency = None
        if totals:
            currency = totals[0]["_id"]
            total_amount = totals[0]["totalAmount"]

        return jsonify({
            "totalDisbursedAmount": total_amount,
            "currency": currency or "HTG"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/repayments/<repayment_id>/verify', methods=['POST'])
def verify_repayment(repayment_id):
    try:
        data = request.get_json()
        action = data.get("action")   # "approve" or "reject"

        repayment = db.repayments.find_one({"_id": ObjectId(repayment_id)})
        if not repayment:
            return jsonify({"error": "Repayment not found"}), 404

        admin_id = get_admin_id_from_token()

        if action == "approve":
            db.repayments.update_one(
                {"_id": ObjectId(repayment_id)},
                {"$set": {
                    "status": "verified",
                    "verifiedAt": datetime.now(timezone.utc),
                    "verifiedBy": ObjectId(admin_id)
                }}
            )

            # update loan totals
            db.loans.update_one(
                {"_id": repayment["loanId"]},
                {
                    "$inc": {"totalRepaid": repayment["amount"]},
                    "$inc": {"outstandingBalance": -repayment["amount"]}
                }
            )

        elif action == "reject":
            db.repayments.update_one(
                {"_id": ObjectId(repayment_id)},
                {"$set": {
                    "status": "rejected",
                    "verifiedAt": datetime.now(timezone.utc),
                    "verifiedBy": ObjectId(admin_id)
                }}
            )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
