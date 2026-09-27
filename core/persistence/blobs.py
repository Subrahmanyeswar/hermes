# core/persistence/blobs.py
"""
Content-Addressed Storage (CAS) for HERMES 2.x persistence.

Core Invariants:
1. ADDRESSING BY SHA-256: Blob ID is the exact hex digest of content bytes.
2. ATOMIC COMMITS: Blobs are written to temporary files and atomically renamed.
3. INTEGRITY ON READ: Every blob read verifies content against its hash.
4. SAFE WINDOWS COMPATIBILITY: Handles file locking and path separators robustly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from core.persistence.models import StorageCorrupt


class BlobStore:
    """
    Content-Addressed Blob Storage.
    Files and large transcript/journal payloads are indexed by SHA-256.
    """

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir).resolve()
        self.blobs_dir = self.root / "blobs"
        self.tmp_dir = self.blobs_dir / ".tmp"
        self._init_dirs()

    def _init_dirs(self) -> None:
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, blob_id: str) -> Path:
        """Partition blobs into 2-character prefix directories."""
        clean_id = blob_id.strip().lower()
        prefix = clean_id[:2] if len(clean_id) >= 2 else "00"
        return self.blobs_dir / prefix / clean_id

    def put(self, data: bytes) -> str:
        """
        Store bytes into CAS. Returns SHA-256 hex digest.
        Idempotent: Identical content shares the existing blob.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"Blob content must be bytes, got {type(data)}")

        blob_id = hashlib.sha256(data).hexdigest()
        dest_path = self._blob_path(blob_id)

        if dest_path.exists() and dest_path.stat().st_size == len(data):
            return blob_id

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temp file
        temp_name = f"blob_{uuid.uuid4().hex}_{os.getpid()}.tmp"
        temp_path = self.tmp_dir / temp_name
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            # Atomic replace (Windows-safe)
            try:
                os.replace(temp_path, dest_path)
            except OSError:
                if not dest_path.exists():
                    shutil.move(str(temp_path), str(dest_path))
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        return blob_id

    def put_file(self, source_path: Path | str) -> str:
        """Stream file contents into CAS blob store."""
        src = Path(source_path)
        with open(src, "rb") as f:
            data = f.read()
        return self.put(data)

    def get(self, blob_id: str) -> bytes:
        """
        Retrieve bytes from CAS by blob_id.
        Verifies SHA-256 hash integrity. Raises StorageCorrupt on mismatch.
        """
        path = self._blob_path(blob_id)
        if not path.exists():
            raise FileNotFoundError(f"Blob '{blob_id}' does not exist in store.")

        with open(path, "rb") as f:
            data = f.read()

        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != blob_id.lower():
            raise StorageCorrupt(
                f"Blob corruption detected: expected {blob_id}, got {actual_hash}"
            )
        return data

    def has(self, blob_id: str) -> bool:
        """Check if blob exists in store."""
        return self._blob_path(blob_id).exists()

    def verify(self, blob_id: str) -> bool:
        """Verify blob exists and its content hash matches."""
        try:
            self.get(blob_id)
            return True
        except (FileNotFoundError, StorageCorrupt):
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Return blob store volume metrics."""
        count = 0
        total_bytes = 0
        for entry in self.blobs_dir.rglob("*"):
            if entry.is_file() and not entry.name.endswith(".tmp"):
                count += 1
                total_bytes += entry.stat().st_size
        return {
            "total_blobs": count,
            "total_bytes": total_bytes,
        }
