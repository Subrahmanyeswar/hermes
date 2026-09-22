import os
from pathlib import Path

class WorkspaceScanner:
    """A class to scan the workspace directory for Python files."""

    def __init__(self, base_dir):
        """Initialize the scanner with the base directory."""
        self.base_dir = base_dir

    def scan(self):
        """Scan the workspace and return a list of Python file paths."""
        file_paths = []
        try:
            for root, dirs, files in os.walk(self.base_dir):
                for file in files:
                    if file.endswith('.py'):
                        full_path = os.path.join(root, file)
                        file_paths.append(full_path)
        except Exception as e:
            print(f"Error scanning workspace: {e}")
        return file_paths

if __name__ == "__main__":
    # Example usage: scan the current directory
    scanner = WorkspaceScanner(os.getcwd())
    files = scanner.scan()
    print("Scanned files:", files)