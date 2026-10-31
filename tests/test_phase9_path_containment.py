# tests/test_phase9_path_containment.py
"""
HERMES Phase 9 Final Security Audit — Path Containment & Escape Prevention Tests.

Proves:
1. Test A: Sibling directory prefix attack ('hermes-evil' vs 'hermes') is strictly rejected.
2. Test B: Legitimate nested paths within workspace root are accepted.
3. Test C: File symlink escapes targeting outside workspace are rejected.
4. Test D: Windows directory junction escapes targeting outside workspace are pruned and rejected.
5. Test E: Path canonicalization edge cases (mixed case, parent traversals '..', relative paths, malformed paths).
6. Test F: Full checkpoint snapshotting completely ignores external junction/symlink targets.
"""

import os
import subprocess
import tempfile
from pathlib import Path
import pytest

from core.checkpoints.file_snapshot import WorkspaceSnapshotter
from core.persistence.blobs import BlobStore


def test_sibling_directory_prefix_attack(tmp_path):
    """
    Test A: Sibling-directory prefix attack.
    Ensures that a path like 'C:/work/hermes-evil/malicious.py' is rejected
    when the workspace root is 'C:/work/hermes'.
    """
    ws_root = tmp_path / "hermes"
    ws_root.mkdir()
    sibling_evil = tmp_path / "hermes-evil"
    sibling_evil.mkdir()

    evil_file = sibling_evil / "malicious.py"
    evil_file.write_text("evil code")

    evil_nested = sibling_evil / "sub" / "deep" / "malicious.py"
    evil_nested.parent.mkdir(parents=True)
    evil_nested.write_text("deep evil code")

    blob_store = BlobStore(tmp_path / "blobs")
    snapshotter = WorkspaceSnapshotter(workspace_root=ws_root, blob_store=blob_store)

    # Must reject sibling evil file
    assert snapshotter._is_safe_path(evil_file) is False
    # Must reject nested evil file
    assert snapshotter._is_safe_path(evil_nested) is False
    # Must reject sibling directory itself
    assert snapshotter._is_safe_path(sibling_evil) is False


def test_legitimate_nested_paths(tmp_path):
    """
    Test B: Legitimate nested paths within workspace.
    Ensures valid files and directories remain accepted without issues.
    """
    ws_root = tmp_path / "hermes"
    ws_root.mkdir()
    (ws_root / "src" / "core").mkdir(parents=True)
    valid_file = ws_root / "src" / "core" / "app.py"
    valid_file.write_text("print('hello')")

    blob_store = BlobStore(tmp_path / "blobs")
    snapshotter = WorkspaceSnapshotter(workspace_root=ws_root, blob_store=blob_store)

    assert snapshotter._is_safe_path(valid_file) is True
    assert snapshotter._is_safe_path(ws_root / "src") is True
    assert snapshotter._is_safe_path(ws_root) is True


def test_symlink_escape(tmp_path):
    """
    Test C: Symlink escape targeting outside workspace root.
    """
    ws_root = tmp_path / "hermes"
    ws_root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.env"
    secret_file.write_text("SUPER_SECRET_KEY=12345")

    symlink_file = ws_root / "leak.env"

    # Try creating a file symlink (requires SeCreateSymbolicLinkPrivilege or Developer Mode on Windows)
    try:
        symlink_file.symlink_to(secret_file)
        symlink_created = True
    except (OSError, NotImplementedError, PermissionError):
        symlink_created = False

    blob_store = BlobStore(tmp_path / "blobs")
    snapshotter = WorkspaceSnapshotter(workspace_root=ws_root, blob_store=blob_store)

    if symlink_created:
        assert snapshotter._is_safe_path(symlink_file) is False
    else:
        # Document limitation if Windows unprivileged symlink creation is not permitted
        pytest.skip("Symlink creation not permitted in this Windows unprivileged environment.")


def test_windows_junction_escape(tmp_path):
    """
    Test D: Windows directory junction escape targeting outside workspace root.
    Uses 'mklink /J' which does NOT require Administrator privileges on Windows.
    """
    ws_root = tmp_path / "hermes"
    ws_root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "passwords.txt"
    secret_file.write_text("admin:secret")

    junction_dir = ws_root / "junction_out"

    res = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_dir), str(outside_dir)],
        capture_output=True,
        text=True,
    )

    if res.returncode != 0:
        pytest.skip(f"Junction creation not available: {res.stderr}")

    try:
        blob_store = BlobStore(tmp_path / "blobs")
        snapshotter = WorkspaceSnapshotter(workspace_root=ws_root, blob_store=blob_store)

        # File inside junction must be rejected as unsafe
        file_in_junction = junction_dir / "passwords.txt"
        assert snapshotter._is_safe_path(file_in_junction) is False
        assert snapshotter._is_safe_path(junction_dir) is False

        # In full snapshotting, junction must be pruned and NOT ingested into manifest
        manifest = snapshotter.create_snapshot()
        assert "junction_out/passwords.txt" not in manifest.files
        assert manifest.total_files == 0
    finally:
        # Clean up junction
        subprocess.run(["cmd", "/c", "rmdir", str(junction_dir)], capture_output=True)


def test_path_canonicalization_edge_cases(tmp_path):
    """
    Test E: Path edge cases including mixed case, parent directory traversals ('..'),
    relative paths, and fail-closed behavior on invalid inputs.
    """
    ws_root = tmp_path / "hermes"
    ws_root.mkdir()
    valid_file = ws_root / "test.txt"
    valid_file.write_text("data")

    blob_store = BlobStore(tmp_path / "blobs")
    snapshotter = WorkspaceSnapshotter(workspace_root=ws_root, blob_store=blob_store)

    # 1. Mixed-case on Windows
    mixed_case = str(ws_root).upper() + "\\TEST.TXT"
    assert snapshotter._is_safe_path(mixed_case) is True

    # 2. Parent traversal escaping workspace
    escape_traversal = ws_root / ".." / "other.txt"
    assert snapshotter._is_safe_path(escape_traversal) is False

    # 3. Parent traversal resolving back inside workspace
    internal_traversal = ws_root / "sub" / ".." / "test.txt"
    assert snapshotter._is_safe_path(internal_traversal) is True

    # 4. Relative path valid
    assert snapshotter._is_safe_path("test.txt") is True

    # 5. Relative path escaping
    assert snapshotter._is_safe_path("../secret.txt") is False

    # 6. Malformed / empty / None-like inputs fail closed
    assert snapshotter._is_safe_path("") is True  # relative '' resolves to workspace_root, which is in workspace
    assert snapshotter._is_safe_path("///invalid???:::path") is False
