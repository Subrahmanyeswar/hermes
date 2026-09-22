import os
from typing import List

def list_directory(path: str, include_hidden: bool = False) -> List[str]:
    """
    List files in the specified directory.
    If include_hidden is False, dotfiles (starting with '.') are excluded by default.
    """
    if not os.path.isdir(path):
        raise ValueError(f"{path} is not a directory")
    
    entries = os.listdir(path)
    if not include_hidden:
        entries = [entry for entry in entries if not entry.startswith('.')]  # Filter out dotfiles
    return entries

# Example usage
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            files = list_directory(path)
嶙            print("Files:", files)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python file_lister.py <directory_path>")