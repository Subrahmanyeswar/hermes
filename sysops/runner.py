import subprocess
from typing import List

def run_command_safely(args: List[str]) -> subprocess.CompletedProcess:
    """
    Run a command safely using subprocess.run with shell=False and validate parameters.
    
    Args:
        args: List of command arguments
    
    Returns:
        subprocess.CompletedProcess: The result of the command execution
    
    Raises:
        ValueError: If args is not a list of strings or contains empty strings
    """
    # Validate input
    if not isinstance(args, list):
        raise ValueError("args must be a list of strings")
    for arg in args:
        if not isinstance(arg, str):
            raise ValueError("All elements in args must be strings")
        if len(arg) == 0:
            raise ValueError("All elements in args must be non-empty strings")
    
    # Run the command
    result = subprocess.run(args, shell=False, capture_output=True, text=True)
    
    # Return the result
    return result