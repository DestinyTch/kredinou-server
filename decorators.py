from flask import current_app, jsonify, request
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from extensions import get_db
from functools import wraps

def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Token missing"), 401

        token = auth.split(" ", 1)[1]
        try:
            data = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )
            db = get_db()
            user = db.users.find_one({"_id": data["user_id"]})
            if not user:
                return jsonify(error="User not found, sign in again"), 404
        except ExpiredSignatureError:
            return jsonify(error="Token expired", logout=True), 401
        except InvalidTokenError:
            return jsonify(error="Token invalid"), 401
        except Exception as e:
            current_app.logger.error(f"Token validation error: {str(e)}")
            return jsonify(error="Token invalid"), 401

        return f(user, *args, **kwargs)
    return wrapper

def admin_token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Token missing"), 401

        token = auth.split(" ", 1)[1]
        try:
            data = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )
            db = get_db()
            admin = db.users.find_one({"_id": data["user_id"], "is_admin": True})
            if not admin:
                return jsonify(error="Admin not found or access denied"), 403
        except ExpiredSignatureError:
            return jsonify(error="Token expired", logout=True), 401
        except InvalidTokenError:
            return jsonify(error="Token invalid"), 401
        except Exception as e:
            current_app.logger.error(f"Token validation error: {str(e)}")
            return jsonify(error="Token invalid"), 401

        return f(admin, *args, **kwargs)
    return wrapper
