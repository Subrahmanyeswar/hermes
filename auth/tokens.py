import jwt
import datetime
from typing import Dict, Any, Optional


def create_token(user_id: int, expiry_seconds: int) -> str:
    """
    Create a JWT token for the given user with the specified expiry in seconds.
    Args:
        user_id: The ID of the user.
        expiry_seconds: The expiry time in seconds.
    Returns:
        str: The encoded JWT token.
    Raises:
        ValueError: If expiry_seconds is not positive.
        RuntimeError: If token encoding fails.
    """
    if expiry_seconds <= 0:
        raise ValueError("Expiry must be positive")
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=expiry_seconds)
    }
    secret_key = "supersecretkey"  # In a real application, this should be fetched securely
    try:
        token = jwt.encode(payload, secret_key, algorithm="HS256")
        return token
    except jwt.PyJWTError as e:
        raise RuntimeError("Failed to encode token") from e

if __name__ == "__main__":
    # Example usage for testing
    try:
        token = create_token(123, 3600)
        print(f"Token created: {token}")
    except Exception as e:
        print(f"Error: {e}")