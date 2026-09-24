# core/context_engine.py
"""
Context Engine for HERMES vNext (Phase 8).
Coordinates intelligent relevance gathering, deterministic ranking,
token-aware budgeting, generation headroom reservation, and ContextPack assembly.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

from loguru import logger
from config.model_config import CONTEXT_ENGINE_ENABLED


class ContextSource(Enum):
    SYSTEM_CORE = "SYSTEM_CORE"
    USER_TASK = "USER_TASK"
    WORKSPACE_STRUCTURE = "WORKSPACE_STRUCTURE"
    WORKSPACE_FILE = "WORKSPACE_FILE"
    WORKSPACE_SYMBOL = "WORKSPACE_SYMBOL"
    MEMORY = "MEMORY"
    SKILL = "SKILL"
    TOOL_SCHEMA = "TOOL_SCHEMA"
    TASK_STATE = "TASK_STATE"


@dataclass
class ContextItem:
    id: str
    source: ContextSource
    content: str
    relevance_score: float
    is_hard_required: bool = False
    token_estimate: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.token_estimate:
            # Approximate token estimation: ~4 chars per token
            self.token_estimate = max(1, len(self.content) // 4)


@dataclass
class ContextPack:
    task_text: str
    system_prompt: str
    user_message: str
    total_tokens: int
    items_included: int
    items_dropped: int
    source_breakdown: Dict[str, int]
    build_duration_ms: float = 0.0
    items: List[ContextItem] = field(default_factory=list)


class ContextRanker:
    """Ranks context items across all sources based on task relevance."""

    def rank(self, items: List[ContextItem]) -> List[ContextItem]:
        # Sort hard-required first, then by relevance_score descending
        return sorted(items, key=lambda x: (x.is_hard_required, x.relevance_score), reverse=True)


class ContextBudgeter:
    """Enforces token limits and reserves generation headroom."""

    def __init__(self, max_context_tokens: int = 4096, generation_reserve: int = 1024):
        self.max_context_tokens = max_context_tokens
        self.generation_reserve = generation_reserve

    def budget(self, ranked_items: List[ContextItem]) -> Tuple[List[ContextItem], List[ContextItem]]:
        available_budget = max(0, self.max_context_tokens - self.generation_reserve)
        used_tokens = 0
        included = []
        dropped = []
        seen_hashes = set()

        for item in ranked_items:
            # Deduplication
            content_hash = hashlib.sha256(item.content.strip().encode("utf-8")).hexdigest()
            if content_hash in seen_hashes and not item.is_hard_required:
                dropped.append(item)
                continue
            seen_hashes.add(content_hash)

            if item.is_hard_required:
                included.append(item)
                used_tokens += item.token_estimate
            elif used_tokens + item.token_estimate <= available_budget:
                included.append(item)
                used_tokens += item.token_estimate
            else:
                dropped.append(item)

        return included, dropped


class ContextEngine:
    """
    Central Context Engine: Assembles high-density, token-budgeted context packs for models.
    """

    def __init__(self, enabled: bool = CONTEXT_ENGINE_ENABLED):
        self.enabled = enabled
        self.ranker = ContextRanker()
        logger.info("ContextEngine initialized | enabled={}", self.enabled)

    def build_context_pack(
        self,
        task_text: str,
        mode: str,
        workspace_manager=None,
        memory_context: str = "",
        skill_content: str = "",
        active_skill_name: str = "none",
        tool_descriptions: str = "",
        task_state: str = "",
        max_context_tokens: int = 4096,
        generation_reserve: int = 1024,
        max_workspace_files: int = 8
    ) -> ContextPack:
        """Assemble a complete structured ContextPack."""
        start_time = time.perf_counter()
        budgeter = ContextBudgeter(max_context_tokens=max_context_tokens, generation_reserve=generation_reserve)

        items: List[ContextItem] = []

        # 1. System Core (Hard Required)
        from core.prompt_builder import HERMES_ROLE
        base_role = HERMES_ROLE.format(
            tool_descriptions=tool_descriptions,
            mode=mode.upper(),
            memory_context="[Refer to [MEMORY] section]",
            skill_context="[Refer to [SKILL] section]",
            workspace_context="[Refer to [WORKSPACE] section]"
        )
        items.append(ContextItem(
            id="system:core_role",
            source=ContextSource.SYSTEM_CORE,
            content=base_role,
            relevance_score=100.0,
            is_hard_required=True
        ))

        # 2. User Task (Hard Required)
        items.append(ContextItem(
            id="user:task_instruction",
            source=ContextSource.USER_TASK,
            content=f"TASK: {task_text}\n\nCRITICAL: If you use <think>...</think>, keep your thinking concise. Use native tool calling (e.g. write_file) when tools are available.",
            relevance_score=100.0,
            is_hard_required=True
        ))

        # 3. Workspace Information (From Phase 7)
        if workspace_manager and workspace_manager.is_locked:
            skeleton = workspace_manager.get_skeleton()
            summary = workspace_manager.get_workspace_summary()
            ws_root_name = summary.get('root', 'unknown')
            items.append(ContextItem(
                id="workspace:structure",
                source=ContextSource.WORKSPACE_STRUCTURE,
                content=f"Workspace: {ws_root_name}\nStructure:\n{skeleton}",
                relevance_score=30.0
            ))

            # Retrieve relevant files & symbols via Phase 7 retriever
            from core.workspace_retriever import workspace_retriever as default_retriever, WorkspaceRetriever
            indexer = getattr(workspace_manager, "indexer", None)
            store = getattr(indexer, "store", None) if indexer else None
            retriever = WorkspaceRetriever(store=store) if store else default_retriever
            retrieved_files = retriever.retrieve_relevant_files(
                workspace_root=workspace_manager.root_str,
                query=task_text,
                max_files=max_workspace_files
            )
            for rf in retrieved_files:
                sym_info = f" (Symbols: {', '.join(rf.symbols)})" if rf.symbols else ""
                flag = " [TEST]" if rf.is_test_file else (" [DEP]" if rf.is_dependency else "")
                file_text_summary = f"Relevant File: {rf.rel_path}{flag}{sym_info}"
                try:
                    full_p = Path(workspace_manager.workspace_root) / rf.rel_path
                    if full_p.exists() and full_p.suffix == ".py":
                        code = full_p.read_text(encoding="utf-8")
                        lines = code.splitlines()
                        if len(lines) <= 80:
                            file_text_summary += f"\n```{rf.rel_path}\n{code}\n```"
                except Exception:
                    pass
                items.append(ContextItem(
                    id=f"workspace:file:{rf.rel_path}",
                    source=ContextSource.WORKSPACE_FILE,
                    content=file_text_summary,
                    relevance_score=rf.score,
                    metadata={
                        "rel_path": rf.rel_path,
                        "symbols": rf.symbols,
                        "is_test_file": rf.is_test_file,
                        "is_dependency": rf.is_dependency,
                        "reasons": rf.reasons,
                        "score": rf.score
                    }
                ))

        # 4. Filtered Relevant Memory Facts
        if memory_context:
            mem_lines = [l.strip() for l in memory_context.split("\n") if l.strip()]
            for idx, m_line in enumerate(mem_lines[:5]):
                # Score memory relevance by keyword overlap with task
                task_words = set(task_text.lower().split())
                m_words = set(m_line.lower().split())
                overlap = len(task_words & m_words)
                m_score = 10.0 + (overlap * 2.0)
                items.append(ContextItem(
                    id=f"memory:fact_{idx}",
                    source=ContextSource.MEMORY,
                    content=m_line,
                    relevance_score=m_score,
                    metadata={"memory_fact": m_line, "index": idx}
                ))

        # 5. Domain Skill Content
        if skill_content and active_skill_name != "none":
            items.append(ContextItem(
                id=f"skill:{active_skill_name}",
                source=ContextSource.SKILL,
                content=f"Skill Instructions ({active_skill_name}):\n{skill_content[:1500]}",
                relevance_score=25.0
            ))

        # 6. Current Task State (if any)
        if task_state:
            items.append(ContextItem(
                id="task:state",
                source=ContextSource.TASK_STATE,
                content=f"Task Execution State:\n{task_state}",
                relevance_score=40.0,
                metadata={"task_state": task_state}
            ))

        # Rank and Budget
        ranked = self.ranker.rank(items)
        included, dropped = budgeter.budget(ranked)

        # Assemble system prompt & user message
        sys_sections = []
        source_counts: Dict[str, int] = {}
        total_tokens = 0

        for item in included:
            src_name = item.source.value
            source_counts[src_name] = source_counts.get(src_name, 0) + 1
            total_tokens += item.token_estimate

            if item.source == ContextSource.SYSTEM_CORE:
                sys_sections.insert(0, item.content)
            else:
                sys_sections.append(f"[{item.source.name}]\n{item.content}")

        final_system_prompt = "\n\n".join(sys_sections)
        from core.prompt_builder import build_user_message
        final_user_message = build_user_message(task_text)

        dur = (time.perf_counter() - start_time) * 1000.0

        return ContextPack(
            task_text=task_text,
            system_prompt=final_system_prompt,
            user_message=final_user_message,
            total_tokens=total_tokens,
            items_included=len(included),
            items_dropped=len(dropped),
            source_breakdown=source_counts,
            build_duration_ms=dur,
            items=included
        )


# Global singleton
context_engine = ContextEngine()
