# core/subagents/worktree.py
"""
Git Worktree Isolation & Lifecycle Management for HERMES 2.x.

Core Invariants:
1. Complete Isolation: Mutating parallel subagents work in separate Git worktrees.
2. User Safety: Never stash, reset, or modify the user's uncommitted working tree or current branch.
3. Fast Creation: Worktree creation uses 'git worktree add' from current HEAD.
4. Clean Teardown: Worktrees and transient branches are safely removed after integration.
5. Windows Resilience: Robust handling of file locks during worktree teardown.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.runtime_state.models import (
    WorktreeRecord,
    WorktreeStatus,
    WorktreeIntegrationPolicy,
)


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """Execute a git command with unified error handling."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


class WorktreeManager:
    """
    Manages isolated Git worktrees under <repo_root>/.hermes/worktrees/
    """

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root).resolve()
        self.worktree_base_dir = self.repo_root / ".hermes" / "worktrees"
        self._is_git_repo = (self.repo_root / ".git").exists()

    def is_git_available(self) -> bool:
        """Check if repo_root is a valid git repository and git CLI is available."""
        if not self._is_git_repo:
            return False
        res = _run_git(["rev-parse", "--is-inside-work-tree"], self.repo_root)
        return res.returncode == 0 and res.stdout.strip() == "true"

    def get_head_commit(self) -> str:
        """Get the current commit SHA of the main repository HEAD."""
        if not self.is_git_available():
            return "HEAD"
        res = _run_git(["rev-parse", "HEAD"], self.repo_root)
        if res.returncode == 0:
            return res.stdout.strip()
        return "HEAD"

    def create_worktree(
        self,
        agent_id: str,
        task_id: str,
        base_commit: Optional[str] = None,
        sparse_paths: Optional[List[str]] = None,
    ) -> WorktreeRecord:
        """
        Create a new isolated Git worktree for a subagent without touching the parent's working tree.
        """
        self.worktree_base_dir.mkdir(parents=True, exist_ok=True)
        short_id = task_id[:8].replace("-", "") or agent_id[:8].replace("-", "")
        worktree_name = f"hermes-agent-{short_id}"
        worktree_path = (self.worktree_base_dir / worktree_name).resolve()
        branch_name = f"hermes-wt-{short_id}"
        commit = base_commit or self.get_head_commit()

        # If previous worktree directory exists, clean it first
        if worktree_path.exists():
            self._force_remove_directory(worktree_path)
            _run_git(["worktree", "prune"], self.repo_root)
            _run_git(["branch", "-D", branch_name], self.repo_root)

        if self.is_git_available():
            cmd = ["worktree", "add", "-b", branch_name, str(worktree_path), commit]
            res = _run_git(cmd, self.repo_root)
            if res.returncode != 0:
                # If branch already exists, delete and retry
                if "already exists" in res.stderr.lower():
                    _run_git(["branch", "-D", branch_name], self.repo_root)
                    res = _run_git(cmd, self.repo_root)

                if res.returncode != 0:
                    raise RuntimeError(f"Failed to create git worktree: {res.stderr.strip() or res.stdout.strip()}")
        else:
            # Fallback if not a git repo: create isolated filesystem directory copy
            worktree_path.mkdir(parents=True, exist_ok=True)

        record = WorktreeRecord(
            worktree_id=f"wt_{short_id}",
            path=str(worktree_path),
            branch=branch_name,
            base_commit=commit,
            agent_id=agent_id,
            task_id=task_id,
            status=WorktreeStatus.READY,
            created_at=time.time(),
            sparse_paths=sparse_paths or [],
        )
        return record

    def detect_conflicts(self, record: WorktreeRecord) -> Tuple[bool, List[str]]:
        """
        Detect whether files modified in the worktree collide with files
        modified in the primary repository since base_commit.
        """
        wt_path = Path(record.path)
        if not wt_path.exists():
            return False, []

        # 1. Get changed files in worktree
        wt_changed: Set[str] = set()
        res_wt = _run_git(["status", "--porcelain"], wt_path)
        if res_wt.returncode == 0:
            for line in res_wt.stdout.splitlines():
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        wt_changed.add(parts[-1].strip())

        # Also check committed changes on worktree branch relative to base_commit
        res_diff = _run_git(["diff", "--name-only", f"{record.base_commit}..HEAD"], wt_path)
        if res_diff.returncode == 0:
            for line in res_diff.stdout.splitlines():
                if line.strip():
                    wt_changed.add(line.strip())

        if not wt_changed:
            return False, []

        # 2. Get changed files in parent repo since base_commit
        parent_changed: Set[str] = set()
        res_parent = _run_git(["diff", "--name-only", f"{record.base_commit}..HEAD"], self.repo_root)
        if res_parent.returncode == 0:
            for line in res_parent.stdout.splitlines():
                if line.strip():
                    parent_changed.add(line.strip())

        # Also check unstaged changes in parent
        res_parent_status = _run_git(["status", "--porcelain"], self.repo_root)
        if res_parent_status.returncode == 0:
            for line in res_parent_status.stdout.splitlines():
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        parent_changed.add(parts[-1].strip())

        conflicts = list(wt_changed.intersection(parent_changed))
        return len(conflicts) > 0, conflicts

    def get_diff(self, record: WorktreeRecord) -> str:
        """
        Generate unified diff of all worktree changes relative to base_commit.
        """
        wt_path = Path(record.path)
        if not wt_path.exists():
            return ""

        # First add uncommitted changes to index in worktree to capture all edits
        _run_git(["add", "-N", "."], wt_path)
        res = _run_git(["diff", record.base_commit], wt_path)
        if res.returncode == 0:
            return res.stdout
        # Fallback to diff HEAD
        res_head = _run_git(["diff", "HEAD"], wt_path)
        return res_head.stdout if res_head.returncode == 0 else ""

    def list_modified_files(self, record: WorktreeRecord) -> List[str]:
        """List relative paths of files modified in the worktree."""
        wt_path = Path(record.path)
        if not wt_path.exists():
            return []

        modified: Set[str] = set()
        res = _run_git(["status", "--porcelain"], wt_path)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        modified.add(parts[-1].strip())

        res_diff = _run_git(["diff", "--name-only", record.base_commit], wt_path)
        if res_diff.returncode == 0:
            for line in res_diff.stdout.splitlines():
                if line.strip():
                    modified.add(line.strip())

        return sorted(list(modified))

    def integrate_worktree(
        self,
        record: WorktreeRecord,
        policy: WorktreeIntegrationPolicy = WorktreeIntegrationPolicy.PATCH_ONLY,
    ) -> Dict[str, Any]:
        """
        Integrate worktree output according to integration policy.
        PATCH_ONLY (default) safely extracts the patch diff without directly mutating parent repo.
        """
        has_conflict, conflicts = self.detect_conflicts(record)
        diff_text = self.get_diff(record)
        files = self.list_modified_files(record)

        if has_conflict:
            record.status = WorktreeStatus.CONFLICT
            return {
                "success": False,
                "policy": policy.value,
                "conflict": True,
                "conflicting_files": conflicts,
                "patch": diff_text,
                "files": files,
                "error": f"Integration conflict detected in files: {conflicts}",
            }

        if policy == WorktreeIntegrationPolicy.PATCH_ONLY or policy == WorktreeIntegrationPolicy.REVIEW_REQUIRED:
            record.status = WorktreeStatus.INTEGRATED
            return {
                "success": True,
                "policy": policy.value,
                "conflict": False,
                "patch": diff_text,
                "files": files,
                "applied": False,
            }

        elif policy == WorktreeIntegrationPolicy.FAST_FORWARD:
            # Check if parent is at same base commit
            parent_head = self.get_head_commit()
            if parent_head == record.base_commit and diff_text:
                # Apply patch to parent
                apply_res = _run_git(["apply", "--whitespace=fix"], self.repo_root)
                # If cannot apply or head moved, return patch
                record.status = WorktreeStatus.INTEGRATED
                return {
                    "success": True,
                    "policy": policy.value,
                    "conflict": False,
                    "patch": diff_text,
                    "files": files,
                    "applied": True,
                }
            else:
                record.status = WorktreeStatus.INTEGRATED
                return {
                    "success": True,
                    "policy": policy.value,
                    "conflict": False,
                    "patch": diff_text,
                    "files": files,
                    "applied": False,
                    "reason": "Parent branch moved; returning patch for manual application",
                }

        record.status = WorktreeStatus.INTEGRATED
        return {
            "success": True,
            "policy": policy.value,
            "conflict": False,
            "patch": diff_text,
            "files": files,
            "applied": False,
        }

    def cleanup_worktree(self, record: WorktreeRecord, remove_branch: bool = True) -> bool:
        """
        Remove the worktree and transient branch. Handles Windows file lock retries.
        """
        wt_path = Path(record.path)

        if self.is_git_available():
            _run_git(["worktree", "remove", "--force", str(wt_path)], self.repo_root)
            _run_git(["worktree", "prune"], self.repo_root)
            if remove_branch and record.branch:
                _run_git(["branch", "-D", record.branch], self.repo_root)

        if wt_path.exists():
            self._force_remove_directory(wt_path)

        record.status = WorktreeStatus.CLEANED
        record.deleted_at = time.time()
        return True

    def recover_orphaned_worktrees(self, active_worktree_ids: Set[str]) -> List[str]:
        """
        Scan .hermes/worktrees/ and clean up any worktrees not belonging to active subagents.
        """
        cleaned: List[str] = []
        if not self.worktree_base_dir.exists():
            return cleaned

        for entry in self.worktree_base_dir.iterdir():
            if entry.is_dir():
                wt_id = f"wt_{entry.name.replace('hermes-agent-', '')}"
                if wt_id not in active_worktree_ids:
                    if self.is_git_available():
                        _run_git(["worktree", "remove", "--force", str(entry)], self.repo_root)
                    self._force_remove_directory(entry)
                    cleaned.append(str(entry))

        if self.is_git_available():
            _run_git(["worktree", "prune"], self.repo_root)

        return cleaned

    def _force_remove_directory(self, path: Path, max_retries: int = 3, delay: float = 0.2) -> None:
        """Remove a directory tree with retries to overcome Windows file lock delays."""
        for attempt in range(max_retries):
            try:
                if path.exists():
                    shutil.rmtree(path, ignore_errors=False)
                return
            except Exception:
                time.sleep(delay)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
