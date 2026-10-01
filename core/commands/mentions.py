# core/commands/mentions.py
"""
Workspace-Safe @-Mention Resolution Subsystem for HERMES 2.x (Prompt 16).

Guarantees:
1. WORKSPACE CONTAINMENT: Strict confinement to active workspace root; zero traversal bypasses (Prompt 13).
2. BUDGET-AWARE CONTEXT: Small files inlined, large files summarized, binary files metadata-only (Prompt 7).
3. CONTENT REMAINS DATA: File contents pass through ContentBoundary screening; prompt injections neutralized.
4. ZERO CRASHES: Gracefully handles missing files, unreadable permissions, symlink loops, UNC paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from core.commands.models import AtMention
from core.security.content_boundary import ContentBoundary
from core.security.enums import ContentTrust

# Thresholds for context inclusion
MAX_INLINE_FILE_BYTES = 100 * 1024       # 100 KB
MAX_DIRECTORY_ITEMS_DISPLAY = 50


class MentionResolver:
    """Safely resolves and screens file and directory @mentions."""

    def __init__(
        self,
        workspace_root: Path | str,
        content_boundary: Optional[ContentBoundary] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.boundary = content_boundary or ContentBoundary()
        self.resolve = self.resolve_mention

    def resolve_mention(self, mention: AtMention) -> AtMention:
        """Resolve a single AtMention against the workspace with security checks."""
        raw_path = mention.path_str

        # 1. Resolve target path
        try:
            target_path = Path(raw_path)
            if not target_path.is_absolute():
                resolved = (self.workspace_root / target_path).resolve()
            else:
                resolved = target_path.resolve()
        except Exception as e:
            return AtMention(
                raw_token=mention.raw_token,
                path_str=raw_path,
                is_valid_path=False,
                error=f"Invalid path syntax: {e}",
            )

        # 2. Workspace Containment Check
        try:
            # Check if resolved path is within workspace root
            is_contained = False
            try:
                # Python 3.9+ is_relative_to
                is_contained = resolved.is_relative_to(self.workspace_root)
            except AttributeError:
                # Fallback for older python or cross-drive on Windows
                common = os.path.commonpath([str(resolved), str(self.workspace_root)])
                is_contained = Path(common) == self.workspace_root
        except Exception:
            is_contained = False

        if not is_contained:
            return AtMention(
                raw_token=mention.raw_token,
                path_str=raw_path,
                is_valid_path=True,
                resolved_path=resolved,
                is_contained=False,
                error=f"Security violation: path '{raw_path}' escapes workspace boundary '{self.workspace_root}'",
            )

        # 3. Existence Check
        if not resolved.exists():
            return AtMention(
                raw_token=mention.raw_token,
                path_str=raw_path,
                is_valid_path=True,
                resolved_path=resolved,
                is_contained=True,
                error=f"File or directory not found: '{raw_path}'",
            )

        # 4. Directory Handling
        if resolved.is_dir():
            return self._resolve_directory(mention, resolved)

        # 5. File Handling
        return self._resolve_file(mention, resolved)

    def _resolve_directory(self, mention: AtMention, dir_path: Path) -> AtMention:
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            total_count = len(entries)
            display_entries = entries[:MAX_DIRECTORY_ITEMS_DISPLAY]

            lines = [f"Directory listing for '{dir_path.name}/' (total {total_count} items):"]
            for e in display_entries:
                suffix = "/" if e.is_dir() else ""
                lines.append(f"  - {e.name}{suffix}")

            if total_count > MAX_DIRECTORY_ITEMS_DISPLAY:
                lines.append(f"  ... and {total_count - MAX_DIRECTORY_ITEMS_DISPLAY} more items")

            summary = "\n".join(lines)
            return AtMention(
                raw_token=mention.raw_token,
                path_str=mention.path_str,
                is_valid_path=True,
                resolved_path=dir_path,
                is_directory=True,
                is_contained=True,
                content_or_summary=summary,
            )
        except Exception as e:
            return AtMention(
                raw_token=mention.raw_token,
                path_str=mention.path_str,
                is_valid_path=True,
                resolved_path=dir_path,
                is_directory=True,
                is_contained=True,
                error=f"Failed to inspect directory: {e}",
            )

    def _resolve_file(self, mention: AtMention, file_path: Path) -> AtMention:
        try:
            stat = file_path.stat()
            file_size = stat.st_size

            # Check for binary file by reading first 1024 bytes
            with open(file_path, "rb") as f:
                header = f.read(1024)

            # Null byte in header indicates binary content
            if b"\x00" in header:
                summary = (
                    f"Binary file '{file_path.name}' ({file_size} bytes). "
                    f"Content omitted from text context."
                )
                return AtMention(
                    raw_token=mention.raw_token,
                    path_str=mention.path_str,
                    is_valid_path=True,
                    resolved_path=file_path,
                    is_directory=False,
                    is_contained=True,
                    file_size_bytes=file_size,
                    is_binary=True,
                    content_or_summary=summary,
                )

            # Large file (> 100 KB): provide bounded preview
            if file_size > MAX_INLINE_FILE_BYTES:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                head = "".join(all_lines[:50])
                tail = "".join(all_lines[-20:])
                summary = (
                    f"Large file '{file_path.name}' ({file_size} bytes, {len(all_lines)} lines). "
                    f"Showing head and tail preview. Use fs.read for specific line ranges.\n\n"
                    f"--- BEGIN HEAD (lines 1-50) ---\n{head}\n"
                    f"--- END HEAD ---\n"
                    f"... [{len(all_lines) - 70} lines omitted] ...\n"
                    f"--- BEGIN TAIL (last 20 lines) ---\n{tail}\n"
                    f"--- END TAIL ---"
                )
                sanitized, _ = self.boundary.process_observation(
                    summary,
                    trust_level=ContentTrust.UNTRUSTED_EXTERNAL,
                    source_id=f"mention:{mention.path_str}",
                )
                return AtMention(
                    raw_token=mention.raw_token,
                    path_str=mention.path_str,
                    is_valid_path=True,
                    resolved_path=file_path,
                    is_directory=False,
                    is_contained=True,
                    file_size_bytes=file_size,
                    is_binary=False,
                    content_or_summary=sanitized,
                )

            # Small text file: read full content and screen through ContentBoundary
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()

            sanitized, _ = self.boundary.process_observation(
                raw_content,
                trust_level=ContentTrust.UNTRUSTED_EXTERNAL,
                source_id=f"mention:{mention.path_str}",
            )

            return AtMention(
                raw_token=mention.raw_token,
                path_str=mention.path_str,
                is_valid_path=True,
                resolved_path=file_path,
                is_directory=False,
                is_contained=True,
                file_size_bytes=file_size,
                is_binary=False,
                content_or_summary=sanitized,
            )
        except Exception as e:
            return AtMention(
                raw_token=mention.raw_token,
                path_str=mention.path_str,
                is_valid_path=True,
                resolved_path=file_path,
                is_directory=False,
                is_contained=True,
                error=f"Error reading file '{mention.path_str}': {e}",
            )

    def resolve_all(self, mentions: Tuple[AtMention, ...]) -> Tuple[AtMention, ...]:
        return tuple(self.resolve_mention(m) for m in mentions)

    @staticmethod
    def enrich_prompt_with_mentions(
        prompt: str,
        resolved_mentions: Tuple[AtMention, ...],
    ) -> str:
        """
        Enrich original prompt with structured, bounded reference data.
        File contents are presented cleanly as context data, never instructions.
        """
        if not resolved_mentions:
            return prompt

        sections = [prompt.strip(), "\n\n=== REFERENCED WORKSPACE CONTEXT ==="]
        for m in resolved_mentions:
            if m.error:
                sections.append(f"\n[Mention '{m.raw_token}': {m.error}]")
            elif m.content_or_summary:
                sections.append(
                    f"\n--- Mention: {m.path_str} ---\n{m.content_or_summary}\n--- End Mention ---"
                )

        return "".join(sections)
