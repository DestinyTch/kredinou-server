import logging
from functools import wraps
from flask import request, jsonify
from pymongo import MongoClient
from config import Config
import jwt
from datetime import datetime, timedelta, timezone
from bson import ObjectId

# Configure logging
logger = logging.getLogger(__name__)

# DB setup with enhanced configuration
mongo_client = MongoClient(
    Config.MONGO_URI,
    connectTimeoutMS=5000,
    socketTimeoutMS=30000,
    serverSelectionTimeoutMS=5000,
    maxPoolSize=50,
    retryWrites=True,
    retryReads=True
)
db = mongo_client.get_database(Config.MONGO_DB_NAME)
users_collection = db.users

def token_required(f):
    """
    JWT token authentication decorator
    ---
    parameters:
      - name: Authorization
        in: header
        type: string
        required: true
        description: Bearer token
    responses:
      401:
        description: Unauthorized (missing or invalid token)
      404:
        description: User not found
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get token from header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("Missing authorization header")
            return jsonify({'error': 'Authorization token is missing'}), 401

        # Verify token format
        try:
            token_parts = auth_header.split()
            if len(token_parts) != 2 or token_parts[0].lower() != 'bearer':
                logger.warning("Invalid token format")
                return jsonify({'error': 'Invalid token format'}), 401
                
            token = token_parts[1]
        except Exception as e:
            logger.error(f"Token parsing error: {str(e)}")
            return jsonify({'error': 'Invalid token format'}), 401

        # Verify and decode token
        try:
            payload = jwt.decode(
                token,
                Config.SECRET_KEY,
                algorithms=[Config.JWT_ALGORITHM],
                options={
                    'require_exp': True,
                    'verify_exp': True,
                    'verify_aud': False
                }
            )
            
            # Validate user ID format
            if not ObjectId.is_valid(payload.get('user_id')):
                logger.warning(f"Invalid user ID format in token: {payload.get('user_id')}")
                return jsonify({'error': 'Invalid token claims'}), 401

            # Get user from database
            current_user = users_collection.find_one({'_id': ObjectId(payload['user_id'])})
            if not current_user:
                logger.warning(f"User not found for ID: {payload['user_id']}")
                return jsonify({'error': 'User not found'}), 404

            # Check if user is active
            if current_user.get('status') != 'active':
                logger.warning(f"Inactive user attempt: {payload['user_id']}")
                return jsonify({'error': 'Account is not active'}), 403

        except jwt.ExpiredSignatureError:
            logger.warning("Expired token attempt")
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            logger.error(f"Token verification error: {str(e)}")
            return jsonify({'error': 'Token verification failed'}), 401

        # Add user to kwargs for the route
        kwargs['current_user'] = current_user
        return f(*args, **kwargs)
    
    return decorated


def generate_jwt_token(user_id):
    """
    Generate a JWT token for a user
    ---
    parameters:
      - user_id: User ID to include in token
    returns:
      JWT token string
    """
    try:
        payload = {
            'user_id': str(user_id),
            'exp': datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRATION_HOURS),
            'iat': datetime.now(timezone.utc),
            'iss': Config.JWT_ISSUER
        }
        return jwt.encode(
            payload,
            Config.SECRET_KEY,
            algorithm=Config.JWT_ALGORITHM
        )
    except Exception as e:
        logger.error(f"Token generation error: {str(e)}")
        raise