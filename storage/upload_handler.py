import os

def handle_upload(file_path):
    """
    Handle file upload by checking the file size and rejecting files larger than 10MB.
    Args:
        file_path (str): Path to the file to be uploaded.
    Returns:
        str: Error message if file is too large or not found, otherwise the file content.
    """
    max_size = 10 * 1024 * 1024  # 10MB in bytes
    
    if not os.path.exists(file_path):
        return f"File not found: {file_path}", 404
    
    file_size = os.path.getsize(file_path)
    if file_size > max_size:
        return f"File too large. Max size is 10MB.", 413  # HTTP 413 Payload Too Large
    else:
        with open(file_path, 'rb') as f:
            content = f.read()
        return content

# Example usage for testing purposes
if __name__ == "__main__":
    test_file = "test_upload.txt"
    # Create a test file if it doesn't exist for demonstration
    if not os.path.exists(test_file):
        withением open(test_file, 'w') as f:
            f.write("Test content for upload.")
    result = handle_upload(test_file)
    print(result)