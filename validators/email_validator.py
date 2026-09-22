import re

def is_valid_email(email: str) -> bool:
    """
    Validate if the given string is a valid email address following RFC 5322 basic pattern.
    
    Args:
        email (str): The email address to validate.
        
    Returns:
        bool: True if valid, False otherwise.
    """
    # RFC 5322 basic pattern regex
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.fullmatch(pattern, email) is not None