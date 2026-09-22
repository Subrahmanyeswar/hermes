import jwt
import datetime
from typing import Dict, Any, Optional

def encode_token(payload: Dict[str, Any]) -> str:
    """Encodes a payload into a JWT token with an expiration."""
    try:
        expiration = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
        payload.update({"exp": expiration})
        secret_key = "your_secret_key"  # Should be configured securely
        return jwt.encode(payload, secret_key, algorithm="HS256")
    except Exception as e:
        raise ValueError(f"Failed to encode token: {e}")

def decode_token(token: str) -> Dict[str, Any]:
    """Decodes and verifies a JWT token."""
    try:
        secret_key = "your_secret_key"
        return jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")