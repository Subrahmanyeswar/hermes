# utils/cleaner.py

def clean_string(text):
    """
    Clean the input string by removing leading/trailing spaces and collapsing multiple spaces.
    
    Args:
        text (str): The input string to clean.
    
    Returns:
        str: The cleaned string.
    
    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(text, str):
        raise TypeError("Input must be a string")
    # Remove leading and trailing spaces
    cleaned = text.strip()
    # Collapse multiple spaces
    cleaned = ' '.join(cleaned.split())
    return cleaned

# Example usage (for testing, but not part of the module)
if __name__ == "__main__":
    print(clean_string("  Hello   World  "))  # Should print "Hello World"