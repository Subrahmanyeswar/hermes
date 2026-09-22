import re


def validate_password(password):
    """Validate password complexity.

    Args:
        password (str): The password to validate.

    Returns:
        bool: True if password meets requirements, False otherwise.
    """
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[0-9]', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True

class UserService:
    """Service class for user-related operations."""

    def register_user(self, username, password):
        """Register a new user.

        Args:
            username (str): The username.
            password (str): The password.

        Raises:
            ValueError: If password does not meet complexity requirements.
        """
        if not validate_password(password):
            raise ValueError("Password must be at least 8 characters, include an uppercase letter, a digit, and a symbol.")
        # Assume other registration logic here, such as saving to database
        print(f"User {username} registered successfully.")  # Placeholder for actual implementation