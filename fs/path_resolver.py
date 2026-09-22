import pathlib

class PathResolver:
    """A utility class to handle file paths across different operating systems. Uses pathlib.Path to ensure correct path formatting, especially on Windows."""
    
    def __init__(self, base_dir):
        """Initialize the PathResolver with a base directory."""
        self.base_dir = pathlib.Path(base_dir)
    
    def get_absolute_path(self, *parts):
        """Get the absolute path by joining parts to the base directory."""
        return self.base_dir.joinpath(*parts)
    
    def exists(self, *parts):
        """Check if a path exists."""
        path = self.get_absolute_path(*parts)
        return path.exists()
    
    # Optional: Add more methods if needed, but this covers the basic path handling.

# Example usage
if __name__ == "__main__":
    resolver = PathResolver("data")
    print(resolver.get_absolute_path("file.txt"))  # Demonstrates correct path handling