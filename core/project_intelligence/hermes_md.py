# core/project_intelligence/hermes_md.py
"""
HERMES.md Standing Project Constitution Loader for HERMES 2.x.
Discovers, hashes, validates, and tracks freshness of root HERMES.md.
Guarantees project instructions are automatically refreshed when modified mid-session.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger
from core.project_intelligence.models import HermesInstructions


class HermesMdLoader:
    """
    Manages discovery, validation, freshness tracking, and caching for HERMES.md.
    """

    RECOMMENDED_MAX_LINES = 200

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._cached_instructions: Optional[HermesInstructions] = None

    def discover_path(self) -> Optional[Path]:
        """Locate HERMES.md in project root or .hermes directory."""
        candidates = [
            self.workspace_root / "HERMES.md",
            self.workspace_root / "hermes.md",
            self.workspace_root / ".hermes" / "HERMES.md",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return c
        return None

    def load(self, force_reload: bool = False) -> HermesInstructions:
        """
        Load or reload HERMES.md.
        If missing, returns empty instructions safely without raising an exception.
        """
        target_path = self.discover_path()
        if not target_path:
            empty_inst = HermesInstructions(
                path="",
                content="",
                line_count=0,
                size_bytes=0,
                mtime_ns=0,
                sha256_hash="",
                is_oversized=False,
                warning="No HERMES.md found in workspace root.",
            )
            self._cached_instructions = empty_inst
            return empty_inst

        # Check cache freshness if not forcing reload
        if not force_reload and self._cached_instructions and self._cached_instructions.path == str(target_path):
            try:
                stat = target_path.stat()
                if stat.st_mtime_ns == self._cached_instructions.mtime_ns:
                    return self._cached_instructions
            except Exception:
                pass

        try:
            raw_bytes = target_path.read_bytes()
            content = raw_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
            stat = target_path.stat()
            lines = content.splitlines()
            line_count = len(lines)
            size_bytes = len(raw_bytes)
            sha256 = hashlib.sha256(raw_bytes).hexdigest()

            is_oversized = line_count > self.RECOMMENDED_MAX_LINES
            warning = None
            if is_oversized:
                warning = (
                    f"HERMES.md is {line_count} lines (recommended: < {self.RECOMMENDED_MAX_LINES} lines). "
                    "Consider moving path-scoped instructions to .hermes/rules/ or procedural tasks to .hermes/skills/."
                )
                logger.warning(f"HermesMdLoader: {warning}")

            instructions = HermesInstructions(
                path=str(target_path),
                content=content,
                line_count=line_count,
                size_bytes=size_bytes,
                mtime_ns=stat.st_mtime_ns,
                sha256_hash=sha256,
                is_oversized=is_oversized,
                warning=warning,
            )
            self._cached_instructions = instructions
            return instructions

        except Exception as exc:
            logger.error(f"HermesMdLoader: error reading '{target_path}': {exc}")
            err_inst = HermesInstructions(
                path=str(target_path),
                content="",
                line_count=0,
                size_bytes=0,
                mtime_ns=0,
                sha256_hash="",
                warning=f"Error reading HERMES.md: {exc}",
            )
            self._cached_instructions = err_inst
            return err_inst

    def check_freshness(self) -> Tuple[bool, Optional[HermesInstructions]]:
        """
        Check if the file on disk has changed compared to cached snapshot.
        Returns: (has_changed, fresh_instructions_or_none)
        """
        target = self.discover_path()
        if not target and not self._cached_instructions:
            return False, None
        if not target and self._cached_instructions and self._cached_instructions.path:
            # File was deleted externally
            fresh = self.load(force_reload=True)
            return True, fresh
        if target and (not self._cached_instructions or not self._cached_instructions.path):
            # File was created externally
            fresh = self.load(force_reload=True)
            return True, fresh

        assert target is not None
        try:
            stat = target.stat()
            if self._cached_instructions and stat.st_mtime_ns != self._cached_instructions.mtime_ns:
                # File modified externally
                fresh = self.load(force_reload=True)
                return True, fresh
        except Exception:
            pass

        return False, self._cached_instructions
