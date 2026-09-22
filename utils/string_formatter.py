import re
def slugify(text: str) -> str:
    """Convert text to a lowercase URL-friendly slug by replacing non-alphanumeric characters with hyphens, removing consecutive hyphens, and stripping leading/trailing hyphens."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    return text