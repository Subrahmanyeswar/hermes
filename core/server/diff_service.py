# core/server/diff_service.py
"""
Service for computing genuine, authoritative file diffs within a locked workspace.
Provides safe path resolution, git diff integration with filesystem fallback,
binary detection, truncation guards, and addition/deletion line counting.
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import List, Optional, Set
from loguru import logger

from core.server.models import FileDiffEntry, MissionDiffsResponse
from core.workspace import WorkspaceBoundaryError, canonicalize_workspace_path


def _is_binary_file(file_path: Path) -> bool:
    """Check if file is binary by scanning first 8KB for null bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except Exception:
        return False


def _run_git_diff(workspace_root: Path, rel_path: str) -> Optional[str]:
    """Attempt to run git diff for a relative file path."""
    git_dir = workspace_root / ".git"
    if not git_dir.exists():
        return None
    try:
        # Check both unstaged and staged/HEAD diffs
        res = subprocess.run(
            ["git", "diff", "HEAD", "--", rel_path],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout

        # Fallback to plain working-tree diff
        res2 = subprocess.run(
            ["git", "diff", "--", rel_path],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0 and res2.stdout.strip():
            return res2.stdout
    except Exception as e:
        logger.debug(f"Git diff failed or unavailable for {rel_path}: {e}")
    return None


def _count_diff_lines(diff_text: str) -> tuple[int, int]:
    """Count additions and deletions from unified diff text."""
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


# In-memory baseline store for non-git environments: (workspace_root_str, rel_path) -> content
_FILE_BASELINES: dict[tuple[str, str], str] = {}


def record_file_baseline(workspace_root: Path, file_path_str: str, content: str) -> None:
    """Record initial file baseline content for non-git diff calculation."""
    ws_str = str(workspace_root.resolve())
    rel = Path(file_path_str).as_posix()
    _FILE_BASELINES[(ws_str, rel)] = content


def get_file_baseline(workspace_root: Path, file_path_str: str) -> Optional[str]:
    """Retrieve recorded baseline content if available."""
    ws_str = str(workspace_root.resolve())
    rel = Path(file_path_str).as_posix()
    return _FILE_BASELINES.get((ws_str, rel))


def clear_file_baselines(workspace_root: Optional[Path] = None) -> None:
    """Clear recorded file baselines."""
    global _FILE_BASELINES
    if workspace_root:
        ws_str = str(workspace_root.resolve())
        _FILE_BASELINES = {k: v for k, v in _FILE_BASELINES.items() if k[0] != ws_str}
    else:
        _FILE_BASELINES.clear()


def compute_file_diff(
    workspace_root: Path,
    file_path_str: str,
    change_type_hint: Optional[str] = None,
) -> FileDiffEntry:
    """
    Compute diff for a file strictly inside workspace_root.
    Raises WorkspaceBoundaryError if file escapes workspace boundary.
    """
    ws = workspace_root.resolve()
    raw_path = Path(file_path_str)
    
    # Path resolution & boundary enforcement
    if raw_path.is_absolute():
        canonical_target = canonicalize_workspace_path(raw_path, ws)
    else:
        canonical_target = canonicalize_workspace_path(ws / raw_path, ws)

    try:
        rel_str = canonical_target.relative_to(ws).as_posix()
    except ValueError:
        rel_str = canonical_target.name

    base_content = get_file_baseline(ws, rel_str)

    # 1. If file does not exist on disk
    if not canonical_target.exists():
        if base_content is not None:
            base_lines = base_content.splitlines(keepends=True)
            diff_lines = list(difflib.unified_diff(
                base_lines,
                [],
                fromfile=f"a/{rel_str}",
                tofile="/dev/null",
            ))
            diff_text = "".join(diff_lines)
            adds, dels = _count_diff_lines(diff_text)
            return FileDiffEntry(
                path=rel_str,
                change_type="deleted",
                additions=adds,
                deletions=dels if dels > 0 else len(base_lines),
                diff_text=diff_text,
                original_content=base_content,
                new_content=None,
                size_bytes=0,
            )
        else:
            diff_text = f"--- a/{rel_str}\n+++ /dev/null\n@@ -1 +0,0 @@\n-[File deleted or not written to disk]"
            return FileDiffEntry(
                path=rel_str,
                change_type="deleted",
                additions=0,
                deletions=1,
                diff_text=diff_text,
                size_bytes=0,
            )

    # 2. Check binary
    size = canonical_target.stat().st_size
    if _is_binary_file(canonical_target):
        return FileDiffEntry(
            path=rel_str,
            change_type=change_type_hint or "modified",
            additions=0,
            deletions=0,
            diff_text=f"[Binary file ({size} bytes) not displayed]",
            is_binary=True,
            size_bytes=size,
        )

    # 3. Check file size cap (max 1MB for diffs)
    if size > 1_048_576:
        return FileDiffEntry(
            path=rel_str,
            change_type=change_type_hint or "modified",
            additions=0,
            deletions=0,
            diff_text=f"[File exceeds 1MB limit for inline diff ({size} bytes)]",
            is_large=True,
            size_bytes=size,
        )

    # 4. Try git diff first if applicable
    git_diff = _run_git_diff(ws, rel_str)
    if git_diff:
        adds, dels = _count_diff_lines(git_diff)
        return FileDiffEntry(
            path=rel_str,
            change_type="modified" if dels > 0 else (change_type_hint or "modified"),
            additions=adds,
            deletions=dels,
            diff_text=git_diff,
            size_bytes=size,
        )

    # 5. Non-git or untracked file fallback: read file content
    try:
        content = canonical_target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return FileDiffEntry(
            path=rel_str,
            change_type=change_type_hint or "modified",
            additions=0,
            deletions=0,
            diff_text=f"[Could not read file: {e}]",
            size_bytes=size,
        )

    lines = content.splitlines(keepends=True)
    if base_content is not None:
        change_type = "modified"
    else:
        change_type = change_type_hint or "created"

    if base_content is not None and change_type == "modified":
        base_lines = base_content.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            base_lines,
            lines,
            fromfile=f"a/{rel_str}",
            tofile=f"b/{rel_str}",
        ))
        diff_text = "".join(diff_lines) if diff_lines else f"[No modifications detected in {rel_str}]"
        adds, dels = _count_diff_lines(diff_text)
        return FileDiffEntry(
            path=rel_str,
            change_type=change_type,
            additions=adds,
            deletions=dels,
            diff_text=diff_text,
            original_content=base_content if len(base_content) < 50_000 else None,
            new_content=content if len(content) < 50_000 else None,
            size_bytes=size,
        )
    
    # Generate clean unified diff from empty file for newly created/untracked
    diff_lines = list(difflib.unified_diff(
        [],
        lines,
        fromfile="/dev/null",
        tofile=f"b/{rel_str}",
    ))
    diff_text = "".join(diff_lines) if diff_lines else f"[Empty file created: {rel_str}]"
    adds, dels = _count_diff_lines(diff_text)
    if not diff_lines and lines:
        adds = len(lines)

    return FileDiffEntry(
        path=rel_str,
        change_type=change_type,
        additions=adds,
        deletions=dels,
        diff_text=diff_text,
        original_content="" if change_type == "created" else None,
        new_content=content if len(content) < 50_000 else None,
        size_bytes=size,
    )


def get_mission_diffs(
    mission_id: str,
    workspace_root: Path,
    created_files: List[str],
    modified_files: List[str],
) -> MissionDiffsResponse:
    """
    Generate unified diffs and statistics for all files affected by a mission.
    """
    ws = workspace_root.resolve()
    seen_paths: Set[str] = set()
    entries: List[FileDiffEntry] = []

    # Process created files
    for f in created_files:
        if not f or f in seen_paths:
            continue
        try:
            entry = compute_file_diff(ws, f, change_type_hint="created")
            seen_paths.add(f)
            seen_paths.add(entry.path)
            entries.append(entry)
        except WorkspaceBoundaryError as wbe:
            logger.warning(f"Skipping file diff outside workspace boundary: {f} ({wbe})")
        except Exception as e:
            logger.warning(f"Error computing diff for {f}: {e}")

    # Process modified files
    for f in modified_files:
        if not f or f in seen_paths:
            continue
        try:
            entry = compute_file_diff(ws, f, change_type_hint="modified")
            seen_paths.add(f)
            seen_paths.add(entry.path)
            entries.append(entry)
        except WorkspaceBoundaryError as wbe:
            logger.warning(f"Skipping file diff outside workspace boundary: {f} ({wbe})")
        except Exception as e:
            logger.warning(f"Error computing diff for {f}: {e}")

    # Check git status for any additional uncommitted changes if workspace is git
    if (ws / ".git").exists():
        try:
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if status_res.returncode == 0:
                for line in status_res.stdout.splitlines():
                    if len(line) < 4:
                        continue
                    status_code = line[:2].strip()
                    git_file = line[3:].strip()
                    clean_rel = git_file.replace("\\", "/").rstrip("/")
                    if clean_rel.startswith((".git", ".hermes", ".artifacts", ".pytest_cache")):
                        continue
                    if (ws / git_file).is_dir():
                        continue
                    if git_file not in seen_paths:
                        c_hint = "created" if status_code == "??" else "modified"
                        try:
                            entry = compute_file_diff(ws, git_file, change_type_hint=c_hint)
                            seen_paths.add(git_file)
                            entries.append(entry)
                        except Exception:
                            pass
        except Exception:
            pass

    total_adds = sum(e.additions for e in entries)
    total_dels = sum(e.deletions for e in entries)

    return MissionDiffsResponse(
        mission_id=mission_id,
        files=entries,
        total_additions=total_adds,
        total_deletions=total_dels,
    )
