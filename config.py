import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

class Config:
    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')  # Always use env var in production
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB upload limit
    
    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
    
    # MongoDB Configuration
    MONGO_URI = os.getenv('MONGO_URI')
    MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'kredi_app')
    MONGO_CONNECT_TIMEOUT_MS = 30000
    MONGO_MAX_POOL_SIZE = 50
    
    # Email Configuration (Brevo)
    BREVO_SMTP_SERVER = os.getenv('BREVO_SMTP_SERVER')
    BREVO_SMTP_PORT = int(os.getenv('BREVO_SMTP_PORT', 587))
    BREVO_SMTP_LOGIN = os.getenv('BREVO_SMTP_LOGIN')
    BREVO_SMTP_PASSWORD = os.getenv('BREVO_SMTP_PASSWORD')
    BREVO_SENDER_EMAIL = os.getenv('BREVO_SENDER_EMAIL')
    BREVO_SENDER_NAME = os.getenv('BREVO_SENDER_NAME')
    
    # SMS Configuration (Twilio)
    SMS_CONFIG = {
        'account_sid': os.getenv('TWILIO_ACCOUNT_SID'),
        'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
        'from_number': os.getenv('TWILIO_PHONE_NUMBER'),
        'api_url': 'https://api.twilio.com/2010-04-01/Accounts'
    }
    
    # Security
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION_HOURS = 24
    
    # Application Settings
    DEFAULT_LOAN_LIMIT = 2000
    UPLOAD_FOLDER = 'uploads'  # For local uploads if needed
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx'}