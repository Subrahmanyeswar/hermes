# core/context/engine.py
"""
Context Engine 2.x for HERMES.
The model-agnostic, state-aware, cache-aware context coordinator for long-running missions.
Collects, normalizes, validates, classifies, scores relevance, enforces budgets,
externalizes large outputs, and manages 3-tier compaction.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from loguru import logger

from core.context.budget import (
    BudgetHealthState,
    ContextBudgetReport,
    ContextBudgeter,
    ContextCapacity,
    TokenEstimator,
)
from core.context.cache_builder import (
    CacheAwarePromptBuilder,
    CacheCapabilities,
    CacheMetrics,
    CacheSegment,
)
from core.context.compactor import CompactionSummary, Compactor
from core.context.external_store import (
    ExternalizedArtifact,
    ExternalizedOutputStore,
    RetentionPolicy,
    externalized_output_store,
)
from core.context.freshness import FreshnessChecker, freshness_checker
from core.context.models import (
    ActiveFileSnippet,
    ContextFreshness,
    ContextItem,
    ContextPriority,
    ContextProvenance,
    ContextSectionType,
    ContextSourceType,
    ContextVersion,
)
from core.context.pack import ContextPack
from core.context.relevance import RelevanceEngine, relevance_engine
from core.context.serializer import ContextSerializer, context_serializer
from core.context.tool_results import ToolResultRecord, ToolResultStore, tool_result_store
from core.context.validation import ContextPackValidator, context_validator
from core.runtime_state.events import EventSeverity, EventType, HermesEvent


class ContextEngine:
    """
    Central coordinator for HERMES 2.x Context Management.
    Projects authoritative state into minimal, high-signal, budgeted ContextPacks.
    """

    def __init__(
        self,
        event_bus: Any = None,
        capacity: Optional[ContextCapacity] = None,
        external_store: Optional[ExternalizedOutputStore] = None,
        result_store: Optional[ToolResultStore] = None,
        cache_capabilities: Optional[CacheCapabilities] = None,
        estimator: Optional[TokenEstimator] = None,
        project_intelligence: Optional[Any] = None,
    ) -> None:
        self.event_bus = event_bus
        self.project_intelligence = project_intelligence
        self.capacity = capacity or ContextCapacity()
        self.estimator = estimator or TokenEstimator()
        self.budgeter = ContextBudgeter(capacity=self.capacity, estimator=self.estimator)
        self.external_store = external_store or externalized_output_store
        self.result_store = result_store or tool_result_store
        self.compactor = Compactor(result_store=self.result_store)
        self.cache_builder = CacheAwarePromptBuilder(capabilities=cache_capabilities)
        self.relevance_engine = relevance_engine
        self.freshness_checker = freshness_checker
        self.validator = context_validator
        self.serializer = context_serializer

        # In-memory candidate registry for current mission
        self._items: Dict[str, ContextItem] = {}
        self._active_files: Dict[str, ActiveFileSnippet] = {}
        self._context_version_counter: int = 0
        self._last_pack: Optional[ContextPack] = None
        self._mission_id: str = "default"

    # ── Item Ingestion and State Registration ─────────────────────────────────

    def register_item(self, item: ContextItem) -> None:
        """Register a candidate context item."""
        self._items[item.id] = item

    def invalidate_item(self, item_id: str, reason: str = "") -> None:
        """Mark an item invalidated when state or underlying resource changes."""
        if item_id in self._items:
            self._items[item_id].mark_invalidated(reason)
            self._publish_event(
                EventType.CONTEXT_ITEM_INVALIDATED,
                payload={"item_id": item_id, "reason": reason},
            )

    def track_file_snippet(
        self,
        path: str,
        content: str,
        start_line: int = 1,
        end_line: int = -1,
        content_hash: str = "",
        is_modified: bool = False,
    ) -> None:
        """Record or update active file snippet in working set."""
        snippet = ActiveFileSnippet(
            path=path,
            start_line=start_line,
            end_line=end_line if end_line != -1 else len(content.splitlines()),
            content=content,
            content_hash=content_hash,
            is_modified_in_mission=is_modified,
        )
        self._active_files[path] = snippet

        # Also register as ContextItem
        clean_path = path.replace("/", "_").replace("\\", "_")
        item_id = f"file_{clean_path}"
        item = ContextItem(
            id=item_id,
            section=ContextSectionType.RELEVANT_FILES,
            content=content,
            provenance=ContextProvenance(
                source_type=ContextSourceType.FILE,
                source_id=path,
                file_path=path,
                line_start=start_line,
                line_end=snippet.end_line,
                content_hash=content_hash,
            ),
            priority=ContextPriority.IMPORTANT if is_modified else ContextPriority.OPTIONAL,
            relevance_score=0.85 if is_modified else 0.60,
        )
        self.register_item(item)

    # ── Tool Result Integration ───────────────────────────────────────────────

    def record_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        turn_id: str,
        mission_id: str,
        output_text: str,
        status: str = "success",
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        evidence_ref: Optional[str] = None,
        auto_externalize_threshold_chars: int = 4000,
    ) -> ToolResultRecord:
        """Record tool execution, auto-externalizing if oversized."""
        rec = self.result_store.record_result(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            turn_id=turn_id,
            mission_id=mission_id,
            output_text=output_text,
            status=status,
            summary=summary,
            metadata=metadata,
            evidence_ref=evidence_ref,
            auto_externalize_threshold_chars=auto_externalize_threshold_chars,
        )

        if rec.external_ref:
            self._publish_event(
                EventType.TOOL_RESULT_EXTERNALIZED,
                payload={
                    "tool_call_id": tool_call_id,
                    "artifact_id": rec.external_ref,
                    "size_bytes": rec.size_bytes,
                },
            )

        # Create corresponding observation ContextItem
        is_error = status != "success"
        priority = ContextPriority.IMPORTANT if is_error else ContextPriority.OPTIONAL
        obs_item = ContextItem(
            id=f"obs_{tool_call_id}",
            section=ContextSectionType.RECENT_OBSERVATIONS,
            content=output_text if len(output_text) <= 1500 else f"[OUTPUT: {rec.summary} | full_ref={rec.external_ref}]",
            provenance=ContextProvenance(
                source_type=ContextSourceType.TOOL_RESULT,
                source_id=tool_name,
                tool_call_id=tool_call_id,
                turn_id=turn_id,
                evidence_id=evidence_ref,
            ),
            priority=priority,
            relevance_score=0.90 if is_error else 0.65,
            externalized=rec.external_ref is not None,
            external_ref=rec.external_ref,
            summary=rec.summary,
            metadata={"is_error": is_error, "tool_name": tool_name},
        )
        self.register_item(obs_item)
        return rec

    # ── Tiered Context Management: Clear, Microcompact, Full Compact ──────────

    def clear_tool_results(self, max_age_turns: int = 3) -> int:
        """
        Level 1: Clear bulky inline tool results older than max_age_turns.
        Preserves summaries and external references.
        """
        cleared = self.compactor.trim_tool_results(list(self._items.values()), max_age_turns=max_age_turns)
        if cleared > 0:
            self._publish_event(
                EventType.TOOL_RESULT_CLEARED,
                payload={"cleared_count": cleared},
            )
        return cleared

    def microcompact(self, current_turn: int) -> int:
        """
        Level 2: Deterministic compression of observations, searches, and repeated reads.
        """
        self._publish_event(EventType.MICROCOMPACTION_STARTED, payload={"turn": current_turn})
        count = self.compactor.microcompact(list(self._items.values()), current_turn=current_turn)
        self._publish_event(EventType.MICROCOMPACTION_COMPLETED, payload={"compressed_count": count})
        return count

    def compact(
        self,
        mission_goal: str,
        state_snapshot: Any = None,
        reason: str = "AUTO",
        focus: str = "",
    ) -> CompactionSummary:
        """
        Level 3: Full compaction with structured summary.
        Preserves authoritative state, goal, evidence, modified files, known blockers.
        """
        self._context_version_counter += 1
        self._publish_event(
            EventType.COMPACTION_STARTED,
            payload={"reason": reason, "focus": focus},
        )

        try:
            summary, surviving_items = self.compactor.full_compact(
                items=list(self._items.values()),
                mission_goal=mission_goal,
                state_snapshot=state_snapshot,
                reason=reason,
                focus=focus,
            )

            # Replace items with surviving set
            self._items = {it.id: it for it in surviving_items}

            self._publish_event(
                EventType.COMPACTION_COMPLETED,
                payload={
                    "compaction_id": summary.compaction_id,
                    "reason": reason,
                    "surviving_items_count": len(surviving_items),
                },
            )
            return summary
        except Exception as exc:
            logger.error(f"ContextEngine: compaction failed ({exc}), retaining deterministic fallback")
            self._publish_event(
                EventType.COMPACTION_FAILED,
                severity=EventSeverity.ERROR,
                payload={"error": str(exc)},
            )
            # Safe deterministic fallback: do not crash mission
            fallback_summary = CompactionSummary(
                compaction_id=f"fallback-{uuid.uuid4().hex[:6]}",
                mission_goal=mission_goal,
                next_action="Continue mission with deterministic fallback.",
            )
            return fallback_summary

    # ── Context Pack Construction ─────────────────────────────────────────────

    def build_context(
        self,
        mission_goal: str,
        state_snapshot: Any = None,
        turn_id: str = "",
        turn_number: int = 1,
        auto_manage_pressure: bool = True,
    ) -> ContextPack:
        """
        Assemble the canonical ContextPack for the upcoming model turn.
        Enforces freshness, calculates relevance, validates budget, and applies
        graduated pressure relief if budget thresholds are exceeded.
        """
        start_time = time.monotonic()
        self._context_version_counter += 1
        self._mission_id = getattr(state_snapshot, "mission_id", self._mission_id) if state_snapshot else self._mission_id

        # 0. Sync Project Intelligence (HERMES.md rules, path-scoped rules)
        if self.project_intelligence and hasattr(self.project_intelligence, "sync_to_context_engine"):
            try:
                active_paths = set(self._active_files.keys())
                self.project_intelligence.sync_to_context_engine(
                    context_engine=self,
                    active_files=active_paths,
                    task_description=mission_goal,
                )
            except Exception as pi_exc:
                logger.warning(f"ContextEngine: project intelligence sync failed: {pi_exc}")

        # 1. Freshness check: Verify active files against current filesystem
        for item in list(self._items.values()):
            self.freshness_checker.check_item_freshness(item)

        # 2. Score candidate items with relevance engine
        candidates = list(self._items.values())
        active_paths = set(self._active_files.keys())
        self.relevance_engine.score_all(
            items=candidates,
            current_goal=mission_goal,
            active_files=active_paths,
            current_turn=turn_number,
        )

        # 3. First budget evaluation pass
        included, dropped, budget_report = self.budgeter.budget(candidates)

        # 4. Graduated Context Pressure Management if required
        if auto_manage_pressure and budget_report.health_state != BudgetHealthState.HEALTHY:
            self._publish_event(
                EventType.CONTEXT_PRESSURE_DETECTED,
                payload={
                    "health_state": budget_report.health_state.value,
                    "utilization": budget_report.utilization,
                    "used_tokens": budget_report.used_tokens,
                },
            )

            # Level 1: Trim tool results
            if budget_report.health_state in (BudgetHealthState.PRESSURE, BudgetHealthState.MICROCOMPACT_REQUIRED):
                self.clear_tool_results(max_age_turns=2)
                included, dropped, budget_report = self.budgeter.budget(list(self._items.values()))

            # Level 2: Microcompaction
            if budget_report.health_state in (BudgetHealthState.MICROCOMPACT_REQUIRED, BudgetHealthState.COMPACT_REQUIRED):
                self.microcompact(current_turn=turn_number)
                included, dropped, budget_report = self.budgeter.budget(list(self._items.values()))

            # Level 3: Full Compaction
            if budget_report.health_state in (BudgetHealthState.COMPACT_REQUIRED, BudgetHealthState.EMERGENCY):
                logger.info(f"ContextEngine: context pressure critical ({budget_report.health_state.value}), triggering full compaction")
                self.compact(
                    mission_goal=mission_goal,
                    state_snapshot=state_snapshot,
                    reason="AUTO_BUDGET_PRESSURE",
                )
                included, dropped, budget_report = self.budgeter.budget(list(self._items.values()))

        # 5. Group included items into canonical sections
        sections: Dict[ContextSectionType, List[ContextItem]] = {sec: [] for sec in ContextSectionType}
        for item in included:
            sections[item.section].append(item)

        # 6. Validate context pack
        val_result = self.validator.validate(sections, budget_report=budget_report, authoritative_state=state_snapshot)
        if not val_result.is_valid:
            logger.warning(f"ContextEngine: validation issues found: {[i.message for i in val_result.issues]}, attempting repair")
            sections = self.validator.repair(sections, val_result)

        # 7. Finalize ContextPack
        duration_ms = (time.monotonic() - start_time) * 1000.0
        version = ContextVersion(
            context_version=self._context_version_counter,
            mission_id=self._mission_id,
            turn_id=turn_id or f"turn_{turn_number}",
            source_state_version=getattr(state_snapshot, "state_version", 0) if state_snapshot else 0,
        )

        pack = ContextPack(
            version=version,
            sections=sections,
            budget_report=budget_report,
            items=included,
            build_duration_ms=duration_ms,
        )

        self._last_pack = pack

        self._publish_event(
            EventType.CONTEXT_BUDGET_UPDATED,
            payload=budget_report.to_dict(),
        )

        self._publish_event(
            EventType.CONTEXT_REBUILT,
            payload={
                "version": version.context_version,
                "items_included": len(included),
                "total_tokens": budget_report.used_tokens,
                "health_state": budget_report.health_state.value,
                "duration_ms": duration_ms,
            },
        )

        return pack

    def rebuild_context(
        self,
        mission_goal: str,
        state_snapshot: Any = None,
        turn_number: int = 1,
    ) -> ContextPack:
        """Explicitly re-synthesize context from registered state and disk references."""
        return self.build_context(
            mission_goal=mission_goal,
            state_snapshot=state_snapshot,
            turn_number=turn_number,
        )

    # ── Telemetry & Observability ─────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Generate lightweight diagnostics snapshot of context state."""
        return {
            "version": self._context_version_counter,
            "registered_items_count": len(self._items),
            "active_files_count": len(self._active_files),
            "budget": self.budgeter.capacity.to_dict(),
            "last_pack_tokens": self._last_pack.total_estimated_tokens if self._last_pack else 0,
            "last_pack_health": self._last_pack.budget_report.health_state.value if self._last_pack else "UNKNOWN",
        }

    def _publish_event(
        self,
        event_type: EventType,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Helper to safely emit canonical events to the authoritative EventBus if present."""
        if not self.event_bus:
            return

        from core.runtime_state.events import HermesEvent
        event = HermesEvent(
            event_type=event_type,
            mission_id=self._mission_id,
            source="context_engine",
            severity=severity,
            payload=payload or {},
        )

        if hasattr(self.event_bus, "publish_nowait"):
            self.event_bus.publish_nowait(event)
        elif hasattr(self.event_bus, "publish"):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.event_bus.publish(event))
            except Exception:
                pass


# Global singleton
context_engine = ContextEngine()
