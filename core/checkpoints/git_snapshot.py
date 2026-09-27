# core/checkpoints/git_snapshot.py
"""
Git repository state snapshotting for HERMES 2.x persistence.

Core Invariants:
1. NON-DESTRUCTIVE: Snapshotting is strictly read-only; never runs reset or clean.
2. NO CREDENTIAL PERSISTENCE: Remote URLs are scrubbed of tokens and passwords.
3. STRUCTURED DIFFS: Captures HEAD SHA, branch, index status, and diff statistics.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional

from core.persistence.models import GitManifest


_CREDENTIAL_URL_PATTERN = re.compile(r"(https?://)([^:@\s]+):([^@\s]+)@")


def sanitize_git_url(url: str) -> str:
    """Scrub credentials from git remote URLs."""
    if not url:
        return ""
    return _CREDENTIAL_URL_PATTERN.sub(r"\1[REDACTED_SECRET]@", url)


class GitSnapshotter:
    """
    Captures structured Git status and diffs for checkpoint metadata.
    Does not mutate or reset repository state under any circumstances.
    """

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root).resolve()

    def _run_git(self, args: List[str]) -> Tuple[int, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            return res.returncode, res.stdout.strip()
        except Exception:
            return -1, ""

    def create_snapshot(self) -> GitManifest:
        """Capture complete Git state snapshot."""
        if not (self.repo_root / ".git").exists():
            return GitManifest(
                repo_root=str(self.repo_root),
                head_sha="NO_GIT",
                branch="NO_GIT",
            )

        # 1. HEAD SHA
        code, head_sha = self._run_git(["rev-parse", "HEAD"])
        if code != 0 or not head_sha:
            head_sha = "UNKNOWN_HEAD"

        # 2. Branch name
        code, branch = self._run_git(["branch", "--show-current"])
        is_detached = False
        if code != 0 or not branch:
            branch = "DETACHED"
            is_detached = True

        # 3. Upstream
        _, upstream = self._run_git(["rev-parse", "--abbrev-ref", "@{upstream}"])

        # 4. Status porcelain
        code, status_out = self._run_git(["status", "--porcelain"])
        tracked_mods: List[str] = []
        staged_mods: List[str] = []
        untracked: List[str] = []

        is_dirty = bool(status_out)
        if status_out:
            for line in status_out.splitlines():
                if len(line) < 3:
                    continue
                index_status = line[0]
                worktree_status = line[1]
                file_path = line[3:].strip()

                if index_status in ("M", "A", "D", "R"):
                    staged_mods.append(file_path)
                if worktree_status in ("M", "D"):
                    tracked_mods.append(file_path)
                elif index_status == "?" and worktree_status == "?":
                    untracked.append(file_path)

        # 5. Diff stats
        _, staged_diff = self._run_git(["diff", "--cached", "--stat"])
        _, unstaged_diff = self._run_git(["diff", "--stat"])

        # 6. Remote summary
        _, remote_out = self._run_git(["remote", "-v"])
        remote_summary = sanitize_git_url(remote_out.splitlines()[0]) if remote_out else ""

        return GitManifest(
            repo_root=str(self.repo_root),
            head_sha=head_sha,
            branch=branch,
            is_detached=is_detached,
            upstream=upstream if upstream else None,
            is_dirty=is_dirty,
            tracked_modifications=tracked_mods,
            staged_modifications=staged_mods,
            untracked_files=untracked,
            staged_diff_stat=staged_diff,
            unstaged_diff_stat=unstaged_diff,
            remote_summary=remote_summary,
        )
