# core/context/compactor.py
"""
Context Compactor, Microcompaction, and Semantic Retention for HERMES 2.x.
Provides three graduated levels of context compression (Level 1: Result Trimming,
Level 2: Microcompaction, Level 3: Full Compaction) ensuring long missions never
exhaust context windows while strictly preserving authoritative state and critical evidence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.context.models import (
    ContextFreshness,
    ContextItem,
    ContextPriority,
    ContextProvenance,
    ContextSectionType,
    ContextSourceType,
)
from core.context.tool_results import ToolResultStore, tool_result_store


@dataclass
class CompactionSummary:
    """Canonical high-fidelity summary produced by Level 3 Compaction."""
    compaction_id: str
    mission_goal: str
    active_requirements: List[Dict[str, Any]] = field(default_factory=list)
    completed_requirements: List[Dict[str, Any]] = field(default_factory=list)
    important_decisions: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    files_relevant: List[str] = field(default_factory=list)
    tests_run: List[Dict[str, Any]] = field(default_factory=list)
    known_failures: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    important_evidence: List[Dict[str, Any]] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    next_action: str = ""
    context_references: List[str] = field(default_factory=list)
    source_turn_range: Tuple[int, int] = (1, 1)
    source_observation_ids: List[str] = field(default_factory=list)
    source_evidence_ids: List[str] = field(default_factory=list)
    trigger: str = "AUTO"  # "AUTO", "MANUAL", "EMERGENCY"
    created_at: float = field(default_factory=time.time)

    def to_context_item(self) -> ContextItem:
        """Serialize into a structured ContextItem for injection into ContextPack."""
        lines = [
            f"=== COMPACT MISSION SUMMARY (Compaction ID: {self.compaction_id}) ===",
            f"Goal: {self.mission_goal}",
        ]
        if self.important_decisions:
            lines.append("Key Architectural Decisions:")
            for d in self.important_decisions:
                lines.append(f"  * {d}")

        if self.files_modified:
            lines.append(f"Files Modified: {', '.join(self.files_modified)}")

        if self.known_failures or self.blockers:
            lines.append("Active Blockers / Known Failures:")
            for b in self.blockers:
                lines.append(f"  ! Blocker: {b}")
            for f in self.known_failures:
                lines.append(f"  ! Failure: {f.get('desc', f)}")

        if self.important_evidence:
            lines.append("Critical Evidence:")
            for ev in self.important_evidence:
                lines.append(f"  [Evidence {ev.get('id', 'ref')}]: {ev.get('summary', '')}")

        if self.next_action:
            lines.append(f"Next Logical Action: {self.next_action}")

        content = "\n".join(lines)
        return ContextItem(
            id=f"compact_{self.compaction_id}",
            section=ContextSectionType.CURRENT_GOAL,
            content=content,
            provenance=ContextProvenance(
                source_type=ContextSourceType.COMPACTION_SUMMARY,
                source_id=self.compaction_id,
            ),
            priority=ContextPriority.MANDATORY,
            relevance_score=1.0,
            token_estimate=max(1, len(content) // 4),
            pinned=True,
            metadata={"compaction_id": self.compaction_id},
        )


class Compactor:
    """
    Executes tiered context compaction.
    Level 1: Trimming and externalizing bulky tool results.
    Level 2: Microcompaction (deterministic compression of observation history).
    Level 3: Full compaction with structured summary generation and fallback protection.
    """

    def __init__(
        self,
        result_store: Optional[ToolResultStore] = None,
        model_summarizer: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.result_store = result_store or tool_result_store
        self.model_summarizer = model_summarizer
        self._compaction_history: List[CompactionSummary] = []

    # ── Level 1: Tool Result Trimming ─────────────────────────────────────────

    def trim_tool_results(self, items: List[ContextItem], max_age_turns: int = 3) -> int:
        """
        Level 1: Clear bulky inline tool results older than max_age_turns.
        Preserves summaries and external references. Returns count of cleared items.
        """
        cleared_count = 0
        for item in items:
            if item.section == ContextSectionType.RECENT_OBSERVATIONS:
                tool_call_id = item.provenance.tool_call_id
                if tool_call_id and not item.pinned and not item.cleared:
                    if len(item.content) > 500:
                        summary = item.summary or item.content.splitlines()[0][:120]
                        item.mark_cleared(summary=summary, external_ref=item.external_ref)
                        self.result_store.clear_result(tool_call_id, summary_override=summary)
                        cleared_count += 1
        return cleared_count

    # ── Level 2: Microcompaction ──────────────────────────────────────────────

    def microcompact(self, items: List[ContextItem], current_turn: int) -> int:
        """
        Level 2: Deterministic compression of observations and search outputs.
        Collapses duplicate reads, shrinks passing test logs, and drops discardable prose.
        """
        compressed_count = 0
        seen_read_paths: Set[str] = set()

        for item in items:
            if item.priority == ContextPriority.MANDATORY or item.pinned:
                continue

            # 1. Collapse duplicate file reads in observation history
            if item.section == ContextSectionType.RECENT_OBSERVATIONS and item.provenance.file_path:
                fp = item.provenance.file_path
                if fp in seen_read_paths:
                    item.content = f"[Repeated read of {fp} collapsed - see earlier snippet]"
                    item.token_estimate = max(1, len(item.content) // 4)
                    item.priority = ContextPriority.DISCARDABLE
                    compressed_count += 1
                else:
                    seen_read_paths.add(fp)

            # 2. Compress large passing test outputs deterministically
            if "test" in item.content.lower() and "passed" in item.content.lower() and "failed" not in item.content.lower():
                if len(item.content) > 400:
                    summary = "All tests passed successfully."
                    item.mark_cleared(summary=summary, external_ref=item.external_ref)
                    compressed_count += 1

            # 3. Compress old search outputs
            if item.section == ContextSectionType.RECENT_OBSERVATIONS and "search" in item.provenance.source_id.lower():
                item_turn = item.metadata.get("turn_number", current_turn)
                if current_turn - item_turn > 4 and len(item.content) > 300:
                    summary = "Search completed (historical matches trimmed)."
                    item.mark_cleared(summary=summary, external_ref=item.external_ref)
                    compressed_count += 1

        return compressed_count

    # ── Level 3: Full Compaction ──────────────────────────────────────────────

    def full_compact(
        self,
        items: List[ContextItem],
        mission_goal: str,
        state_snapshot: Any = None,
        reason: str = "AUTO",
        focus: str = "",
    ) -> Tuple[CompactionSummary, List[ContextItem]]:
        """
        Level 3: Full session compaction.
        Produces structured CompactionSummary preserving machine-known truth,
        retaining mandatory items, and pruning old transient observations.
        """
        compaction_id = f"cmp-{uuid.uuid4().hex[:8]}"

        # 1. Take safety snapshot of authoritative state
        files_modified = []
        blockers = []
        known_failures = []
        tests_run = []
        important_decisions = []
        evidence_items = []
        source_obs_ids = []

        if state_snapshot:
            # Extract from authoritative state store
            if hasattr(state_snapshot, "mission"):
                files_modified.extend(getattr(state_snapshot.mission, "files_modified", []))
            if hasattr(state_snapshot, "tasks"):
                for t in getattr(state_snapshot.tasks, "tasks", {}).values():
                    if getattr(t, "status", "") == "BLOCKED":
                        blockers.append(f"{t.task_id}: {t.name}")

        # 2. Extract facts from context items
        for item in items:
            if item.section == ContextSectionType.RECENT_CHANGES:
                if item.provenance.file_path and item.provenance.file_path not in files_modified:
                    files_modified.append(item.provenance.file_path)

            if item.section == ContextSectionType.RELEVANT_MEMORY:
                if item.metadata.get("is_decision") or "decision" in item.content.lower():
                    important_decisions.append(item.content[:200])

            if item.section == ContextSectionType.EVIDENCE:
                evidence_items.append({
                    "id": item.provenance.evidence_id or item.id,
                    "summary": item.summary or item.content[:150],
                })

            if item.section == ContextSectionType.RECENT_OBSERVATIONS:
                source_obs_ids.append(item.id)
                if "failed" in item.content.lower() or "error" in item.content.lower():
                    desc = f"{item.summary}: {item.content[:120]}" if (item.summary and item.summary not in item.content) else (item.content[:150] or item.summary)
                    known_failures.append({
                        "id": item.id,
                        "desc": desc,
                    })

        # 3. Build structured summary
        next_action = "Continue implementing next unverified requirement or inspect active blockers."
        if blockers or known_failures:
            next_action = "Investigate and repair the active failure/blocker."

        summary = CompactionSummary(
            compaction_id=compaction_id,
            mission_goal=mission_goal,
            important_decisions=important_decisions[:10],
            files_modified=files_modified[:20],
            known_failures=known_failures[-5:],
            blockers=blockers[:5],
            important_evidence=evidence_items[-10:],
            next_action=next_action,
            source_observation_ids=source_obs_ids,
            trigger=reason,
        )

        # 4. Filter items: Keep SYSTEM, PROJECT_RULES, MANDATORY, pinned, active files, and inject the summary
        surviving_items: List[ContextItem] = []

        # Retain invariant system and rules
        for item in items:
            if item.section in (ContextSectionType.SYSTEM, ContextSectionType.PROJECT_RULES):
                surviving_items.append(item)
            elif item.priority == ContextPriority.MANDATORY or item.pinned:
                surviving_items.append(item)
            elif item.section == ContextSectionType.RELEVANT_FILES and item.freshness == ContextFreshness.FRESH:
                surviving_items.append(item)

        # Add the summary as a top-priority item
        summary_item = summary.to_context_item()
        surviving_items.append(summary_item)

        self._compaction_history.append(summary)
        return summary, surviving_items
