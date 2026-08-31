# core/cross_file_retriever.py
"""
Cross-File Context Retrieval for HERMES
Based on: RepoBench (Liu et al., 2024)

RepoBench finding: Repository-level code tasks require a DEDICATED
retrieval phase BEFORE generation. Dumping the whole repository into
the context degrades performance (the "lost in the middle" problem).
Instead: detect which files are relevant, extract only their
signatures/key sections, and place them at context edges.

Three retrieval strategies (in order of what to try):
  1. Import-based: Files that are explicitly imported/required
  2. Keyword-based: Files whose names match task keywords
  3. Signature-based: Files whose class/function names match task intent

RepoBench also establishes the prompt placement rule:
  CRITICAL context goes at the START and END, never buried in the middle.
  This module enforces that discipline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from loguru import logger

from core.workspace import WorkspaceManager


@dataclass
class RetrievedContext:
    """One retrieved cross-file context item."""
    relative_path: str
    retrieval_reason: str    # Why this file was retrieved
    content: str             # Signatures or relevant excerpt
    relevance_score: float   # 0.0–1.0


@dataclass
class CrossFileContext:
    """
    The assembled cross-file context for one task.
    Enforces RepoBench's placement discipline:
      - High-relevance items go at the START of the context
      - Medium-relevance items go in the MIDDLE
      - The task itself goes at the END

    This exploits LLM primacy and recency bias.
    """
    items: list[RetrievedContext] = field(default_factory=list)
    task_description: str = ""

    def to_prompt_section(self, max_items: int = 6) -> str:
        """
        Format retrieved context for prompt injection.
        RepoBench placement: highest-relevance at top.
        """
        if not self.items:
            return ""

        # Sort by relevance (highest first — primacy position)
        sorted_items = sorted(self.items, key=lambda x: -x.relevance_score)[:max_items]

        lines = ["CROSS-FILE CONTEXT (retrieved from workspace):"]
        lines.append("─" * 50)

        for item in sorted_items:
            lines.append(f"# File: {item.relative_path} [{item.retrieval_reason}]")
            lines.append(item.content[:800])
            lines.append("")

        lines.append("─" * 50)
        return "\n".join(lines)

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0


class CrossFileRetriever:
    """
    Retrieves relevant cross-file context before T1 generation.

    RepoBench establishes that retrieval quality directly determines
    completion quality. This retriever uses three strategies
    in priority order.
    """

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    def retrieve(
        self,
        task_description: str,
        max_files: int = 5,
    ) -> CrossFileContext:
        """
        Retrieve cross-file context relevant to this task.

        Returns empty CrossFileContext if workspace is not locked
        or task appears to be single-file.
        """
        ctx = CrossFileContext(task_description=task_description)

        if not self.workspace.is_locked or self.workspace.index is None:
            return ctx

        # Strategy 1: Import-based retrieval
        # Find files that existing project files import
        import_items = self._retrieve_by_imports(task_description)
        ctx.items.extend(import_items)

        # Strategy 2: Keyword-based retrieval
        # Find files whose names match task keywords
        keyword_items = self._retrieve_by_keywords(task_description)
        # Deduplicate
        existing_paths = {i.relative_path for i in ctx.items}
        for item in keyword_items:
            if item.relative_path not in existing_paths:
                ctx.items.append(item)
                existing_paths.add(item.relative_path)

        # Strategy 3: Signature-based retrieval
        # Find files whose class/function names match intent
        sig_items = self._retrieve_by_signatures(task_description)
        for item in sig_items:
            if item.relative_path not in existing_paths:
                ctx.items.append(item)
                existing_paths.add(item.relative_path)

        # Cap at max_files and sort by relevance
        ctx.items = sorted(ctx.items, key=lambda x: -x.relevance_score)[:max_files]

        logger.debug(
            f"CrossFileRetriever: task='{task_description[:50]}' | "
            f"retrieved={len(ctx.items)} files"
        )
        return ctx

    def _retrieve_by_imports(self, task_description: str) -> list[RetrievedContext]:
        """
        Strategy 1: Find files that import from other files in the workspace.
        When a task touches file A, also retrieve files that A imports.
        """
        items: list[RetrievedContext] = []

        if self.workspace.index is None:
            return items

        for rel_path, entry in self.workspace.index.files.items():
            if entry.extension != ".py":
                continue
            try:
                content = Path(entry.absolute_path).read_text(
                    encoding="utf-8", errors="replace"
                )
                # Find import statements
                imports = re.findall(
                    r'^(?:from|import)\s+([\w.]+)',
                    content, re.MULTILINE
                )
                # Check if any import matches task keywords
                task_lower = task_description.lower()
                for imp in imports:
                    if any(kw in imp.lower() for kw in task_lower.split() if len(kw) > 3):
                        sigs = self.workspace.get_signatures(rel_path)
                        if sigs:
                            items.append(RetrievedContext(
                                relative_path=rel_path,
                                retrieval_reason="imported module",
                                content=sigs,
                                relevance_score=0.9,
                            ))
                        break
            except Exception:
                continue

        return items[:3]

    def _retrieve_by_keywords(self, task_description: str) -> list[RetrievedContext]:
        """
        Strategy 2: Find files whose names match task keywords.
        """
        items: list[RetrievedContext] = []
        task_words = [
            w.lower() for w in task_description.split()
            if len(w) > 3 and w.isalpha()
        ]

        if not task_words or self.workspace.index is None:
            return items

        for rel_path, entry in self.workspace.index.files.items():
            if not entry.is_code_file:
                continue

            path_lower = rel_path.lower()
            match_count = sum(1 for w in task_words if w in path_lower)

            if match_count > 0:
                relevance = min(1.0, match_count / len(task_words) + 0.3)
                # Get signatures if Python, else first 40 lines
                if entry.extension == ".py":
                    content = self.workspace.get_signatures(rel_path) or ""
                else:
                    try:
                        full = Path(entry.absolute_path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                        content = "\n".join(full.split("\n")[:40])
                    except Exception:
                        content = ""

                if content:
                    items.append(RetrievedContext(
                        relative_path=rel_path,
                        retrieval_reason=f"keyword match ({match_count}/{len(task_words)} words)",
                        content=content,
                        relevance_score=relevance,
                    ))

        return sorted(items, key=lambda x: -x.relevance_score)[:4]

    def _retrieve_by_signatures(self, task_description: str) -> list[RetrievedContext]:
        """
        Strategy 3: Find files whose class/function signatures match task intent.
        """
        items: list[RetrievedContext] = []
        task_lower = task_description.lower()

        if self.workspace.index is None:
            return items

        for rel_path, entry in self.workspace.index.files.items():
            if entry.extension != ".py":
                continue

            sigs = self.workspace.get_signatures(rel_path)
            if not sigs:
                continue

            sigs_lower = sigs.lower()
            # Count how many task keywords appear in the signatures
            task_words = [w for w in task_lower.split() if len(w) > 4]
            match_count = sum(1 for w in task_words if w in sigs_lower)

            if match_count >= 2:
                items.append(RetrievedContext(
                    relative_path=rel_path,
                    retrieval_reason=f"signature match ({match_count} terms)",
                    content=sigs,
                    relevance_score=min(1.0, match_count / max(len(task_words), 1)),
                ))

        return sorted(items, key=lambda x: -x.relevance_score)[:3]