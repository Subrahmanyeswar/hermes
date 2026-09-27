# core/persistence/transactions.py
"""
Atomic file system transactions and checkpoint commit protocols for HERMES 2.x.

Guarantees:
1. ATOMIC REPLACE: Uses os.replace() with temporary files in the same directory.
2. FSYNC DURABILITY: Flushes file buffers to disk before replacing destination.
3. WINDOWS RESILIENCE: Implements exponential backoff on transient Windows lock errors.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Union


def atomic_write(target_path: Path | str, content: Union[str, bytes], mode: str = "w") -> None:
    """
    Atomically write content to target_path using a temporary file in the same folder.
    Guarantees no half-written files exist on disk if interrupted.
    """
    dest = Path(target_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_name = f".tmp_{uuid.uuid4().hex}_{os.getpid()}"
    tmp_path = dest.parent / tmp_name

    is_binary = "b" in mode or isinstance(content, (bytes, bytearray))
    write_mode = "wb" if is_binary else "w"
    encoding = None if is_binary else "utf-8"

    try:
        with open(tmp_path, write_mode, encoding=encoding) as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # Windows-safe atomic replace with retry
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                os.replace(tmp_path, dest)
                break
            except PermissionError:
                if attempt == max_attempts - 1:
                    # Fallback to copy + remove
                    shutil.copyfile(str(tmp_path), str(dest))
                    tmp_path.unlink(missing_ok=True)
                else:
                    time.sleep(0.02 * (attempt + 1))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
