import os
from datetime import timedelta

class AuthConfig:
    """Configuration for JWT authentication."""
    
    SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'default_secret_key')
    """Secret key for signing JWTs. Use environment variable for security."""
    
    ALGORITHM = 'HS256'
    """Algorithm to use for signing and verifying JWTs."""
    
    ACCESS_TOKEN_EXPIRE_MINUTES = 15
    """Duration in minutes for which access tokens are valid."""