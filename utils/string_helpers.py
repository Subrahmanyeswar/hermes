def truncate_text(text: str, max_length: int, suffix: str = '...') -> str:
    """Truncate the text to max_length characters, preserving whole words where possible.
    If the text is shorter than max_length, return it unchanged.
    """
    if len(text) <= max_length:
        return text
    
    # Find the last space before max_length
    truncated = text[:max_length]
    # If the truncation doesn't end with a word boundary, find the last space
    last_space = truncated.rfind(' ')
    if last_space == -1:
        # No space found, so we'll just truncate and add the suffix
        return truncated + suffix
    else:
        # Truncate at the last space to preserve words
        return truncated[:last_space] + suffix