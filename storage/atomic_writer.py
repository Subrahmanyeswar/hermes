import os
import tempfile
from pathlib import Path

def atomic_write_file(path: Path, content: str, encoding: str = 'utf-8'):
    with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, delete=False) as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name
    os.replace(temp_file_path, str(path))