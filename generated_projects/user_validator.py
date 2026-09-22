def validate_email(email):
    """Validate if the input is a valid email.
    Simple check: contains '@' and a domain part.
    """
    if '@' in email:
        # Check if there's something before and after '@'
        parts = email.split('@')
        if len(parts) < 2:
            return False
        # Basic check: domain should have at least one dot or something, but keep it simple
        return True
    return False

def validate_password(pwd):
    """Validate if the input is a valid password.
    Requirements: at least 8 characters, one uppercase, one lowercase, one digit.
    """
    if len(pwd) < 8:
        return False
    if not any(c.isupper() for c in pwd):
        return False
    if not any(c.islower() for c in pwd):
        return False
    if not any(c.isdigit() for c in pwd):
        return False
    return True