from typing import Optional, Dict

def parse_auth_header(headers: Dict[str, str]) -> Optional[str]:
    # Convert header keys to lowercase for case-insensitive matching
    lower_headers = {k.lower(): v for k, v in headers.items()}
    # Check if 'authorization' key exists in the lowercase dictionary
    if 'authorization' in lower_headers:
        return lower_headers['authorization']
    else:
        return None