import os
import sys

def scan_directory(path, visited=None):
    if visited is None:
        visited = set()
    
    # Add current path to visited to detect cycles
    if path in visited:
        return  # Skip if already visited to avoid recursion in cycles
    
    visited.add(path)
    
    if os.path.islink(path):
        # Handle symlink: resolve and check if it's a directory
        target = os.readlink(path)
        print(f"Symlink detected: {path} -> {target}")
        if os.path.isdir(target):
            # Resolve the symlink and recurse
            target_path = os.path.join(os.path.dirname(path), target)
            scan_directory(target_path, visited)
        else:
            print(f"Symlink points to file, not directory: {path}")
    else:
        if os.path.isdir(path):
            print(f"Scanning directory: {path}")
            for entry in os.listdir(path):
                entry_path = os.path.join(path, entry)
                scan_directory(entry_path, visited)
        else:
            print(f"Found file: {path}")

# Example usage
if __name__ == "__main__":
    start_path = sys.argv[1] if len(sys.argv) > 1 else "./"
    visited_set = set()
    scan_directory(start_path, visited_set)