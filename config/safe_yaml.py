import yaml


def safe_load_yaml(content: str) -> dict במילים:
    """
    Safely load a YAML string and return the parsed dictionary.
    If an error occurs during parsing, return an error dictionary.
    
    Args:
        content (str): The YAML content to parse.
    
    Returns:
        dict: The parsed dictionary or an error dictionary.
    """
    try:
        # Attempt to parse the YAML content safely
        return yaml.safe_load(content)
    except yaml.YAMLError as e:
        # Handle YAML parsing errors gracefully
        return {'error': f'YAML parsing failed: {str(e)}'}