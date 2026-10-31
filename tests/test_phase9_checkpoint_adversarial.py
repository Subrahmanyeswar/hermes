# tests/test_phase9_checkpoint_adversarial.py
"""
HERMES Phase 9 Audit A — Mandatory Adversarial Checkpoint & Hash Integrity Test.

Proves:
1. Baseline checkpoint captures initial file contents and CAS blob.
2. Adversarial same-size content replacement with restored mtime_ns is detected.
3. Checkpoint manifest hash, CAS blob, and file hash reflect the new content.
4. Concurrency protection: file modified during snapshotting is consistently captured.
"""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest

from core.checkpoints.engine import CheckpointEngine
from core.checkpoints.file_snapshot import WorkspaceSnapshotter
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import CheckpointReason, CheckpointTrigger, FileChangeType, SessionStatus
from core.runtime_state.models import HermesRuntimeState


def test_adversarial_same_size_content_with_restored_mtime(tmp_path):
    """
    Mandatory Adversarial Test:
    1. Create a file with known contents.
    2. Capture baseline checkpoint (manifest entry, blob ID, content hash, size, timestamp).
    3. Replace file contents with different bytes of exactly the same length.
    4. Restore original modification timestamp via os.utime.
    5. Ensure metadata matches prior values.
    6. Create subsequent checkpoint with prior_manifest.
    7. Independently calculate actual current content hash.
    8. Verify checkpoint manifest and CAS content agree with independent hash.
    """
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    blob_dir = tmp_path / "blobs"
    blob_store = BlobStore(blob_dir)
    snapshotter = WorkspaceSnapshotter(workspace_root=ws, blob_store=blob_store)

    target_file = ws / "adversarial.txt"
    initial_content = b"ORIGINAL_10_BYTES!"
    target_file.write_bytes(initial_content)
    initial_hash = hashlib.sha256(initial_content).hexdigest()

    # Capture Baseline Checkpoint
    manifest_1 = snapshotter.create_snapshot()
    assert "adversarial.txt" in manifest_1.files
    snap_1 = manifest_1.files["adversarial.txt"]
    assert snap_1.sha256 == initial_hash
    assert snap_1.change_type == FileChangeType.TRACKED
    assert blob_store.get(snap_1.blob_id) == initial_content

    orig_stat = target_file.stat()
    orig_atime = orig_stat.st_atime
    orig_mtime = orig_stat.st_mtime
    orig_mtime_ns = orig_stat.st_mtime_ns
    orig_size = orig_stat.st_size

    # Replace with different bytes of the EXACT same length
    adversarial_content = b"MUTATED__10_BYTES!"
    assert len(adversarial_content) == len(initial_content)
    target_file.write_bytes(adversarial_content)
    adversarial_hash = hashlib.sha256(adversarial_content).hexdigest()
    assert adversarial_hash != initial_hash

    # Restore modification timestamp to match initial metadata
    os.utime(target_file, (orig_atime, orig_mtime))
    new_stat = target_file.stat()
    assert new_stat.st_size == orig_size
    # Confirm timestamp restoration
    assert abs(new_stat.st_mtime - orig_mtime) < 0.001

    # Capture Subsequent Checkpoint with prior_manifest provided
    manifest_2 = snapshotter.create_snapshot(prior_manifest=manifest_1)
    assert "adversarial.txt" in manifest_2.files
    snap_2 = manifest_2.files["adversarial.txt"]

    # Invariant Verification:
    # 1. Manifest sha256 must match current content hash, NOT old hash
    assert snap_2.sha256 == adversarial_hash, "Checkpoint must reflect NEW content hash, not stale hash!"
    # 2. Change type must be MODIFIED
    assert snap_2.change_type == FileChangeType.MODIFIED, "Adversarial edit must be recognized as MODIFIED!"
    # 3. CAS Blob must contain the new content
    assert blob_store.get(snap_2.blob_id) == adversarial_content
    # 4. Manifest hashes must differ
    assert manifest_2.manifest_hash != manifest_1.manifest_hash


def test_concurrent_modification_during_snapshot_recovery(tmp_path):
    """
    Test that if a file is modified during snapshotting, the concurrency check
    re-reads and stores the consistent final content and metadata.
    """
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    blob_dir = tmp_path / "blobs"
    blob_store = BlobStore(blob_dir)
    snapshotter = WorkspaceSnapshotter(workspace_root=ws, blob_store=blob_store)

    target_file = ws / "concurrent.txt"
    target_file.write_bytes(b"content_version_1")

    # Hook put_file to simulate concurrent file modification during read
    orig_put_file = blob_store.put_file
    call_count = 0

    def mutating_put_file(path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First read: concurrently mutate file on disk before stat_after check
            Path(path).write_bytes(b"content_version_2_concurrent")
        return orig_put_file(path)

    blob_store.put_file = mutating_put_file

    manifest = snapshotter.create_snapshot()
    snap = manifest.files["concurrent.txt"]

    # Concurrency check must have re-read the file
    assert call_count >= 2, "Concurrency check should have triggered a re-read!"
    assert snap.sha256 == hashlib.sha256(b"content_version_2_concurrent").hexdigest()
    assert blob_store.get(snap.blob_id) == b"content_version_2_concurrent"
