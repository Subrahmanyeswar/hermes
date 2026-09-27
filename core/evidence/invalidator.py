# core/evidence/invalidator.py
"""
Evidence Invalidator for HERMES 2.x.

Core Invariants:
1. ENVIRONMENT MUTATIONS INVALIDATE EVIDENCE: When a file or resource changes, all derived evidence becomes STALE or INVALIDATED.
2. CASCADE TO VERIFICATION: When evidence is invalidated, any acceptance checks that relied upon it cannot remain silently verified; they must be reopened or marked unverified.
3. DURABILITY & REVERSIBILITY: Invalidation is published via canonical events (EVIDENCE_INVALIDATED) and reflected in both the durable store and runtime state.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.event_bus import EventBus
from core.evidence.models import EvidenceFreshness, EvidenceRecord, EvidenceStatus
from core.evidence.store import EvidenceStore
from core.runtime_state.events import EventType, HermesEvent
from tools.platform.file_identity import FileIdentityCache, file_identity_cache

logger = logging.getLogger("hermes.evidence.invalidator")


class EvidenceInvalidator:
    """
    Watches environment changes, validates evidence freshness against current disk state,
    and invalidates stale evidence records and dependent verification states.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        evidence_store: EvidenceStore,
        event_bus: Optional[EventBus] = None,
        identity_cache: Optional[FileIdentityCache] = None,
        mission_id: str = "default",
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = evidence_store
        self.event_bus = event_bus
        self.cache = identity_cache or file_identity_cache
        self.mission_id = mission_id

    def check_file_freshness(self, record: EvidenceRecord) -> bool:
        """
        Verify if a file-based evidence record is still fresh relative to the file on disk.
        Returns True if fresh, False if stale/invalid.
        """
        if not record.source_uri_or_path:
            return True

        target_path = Path(record.source_uri_or_path)
        if not target_path.is_absolute():
            target_path = (self.workspace_root / target_path).resolve()

        if not target_path.exists():
            # If the file was expected to exist (status == RECORDED and exit_code == 0) but now doesn't
            if record.exit_code == 0 and record.status == EvidenceStatus.RECORDED:
                return False
            return True

        # Check content hash / digest against current file
        if record.output_digest:
            try:
                import hashlib
                current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                if current_hash != record.output_digest:
                    return False
            except Exception as e:
                logger.warning(f"Error checking hash for {target_path}: {e}")
                return False

        return True

    def invalidate_record(self, evidence_id: str, reason: str = "environment_mutation") -> Optional[EvidenceRecord]:
        """
        Mark a single evidence record as INVALIDATED and publish canonical event.
        """
        record = self.store.get(evidence_id)
        if not record:
            return None

        self.store.mark_invalidated(evidence_id)

        if self.event_bus:
            event = HermesEvent(
                event_type=EventType.EVIDENCE_INVALIDATED,
                mission_id=self.mission_id,
                requirement_id=record.requirement_id,
                acceptance_check_id=record.acceptance_check_id,
                evidence_id=record.evidence_id,
                payload={
                    "evidence_id": record.evidence_id,
                    "requirement_id": record.requirement_id,
                    "acceptance_check_id": record.acceptance_check_id,
                    "reason": reason,
                    "source_path": record.source_uri_or_path,
                },
            )
            self.event_bus.publish(event)

        return record

    def mark_stale(self, evidence_id: str, reason: str = "file_modified") -> Optional[EvidenceRecord]:
        """
        Mark an evidence record as STALE.
        """
        record = self.store.get(evidence_id)
        if not record:
            return None

        self.store.mark_stale(evidence_id)
        return record

    def invalidate_by_file_path(self, rel_or_abs_path: str, reason: str = "file_modified") -> List[EvidenceRecord]:
        """
        Invalidate all evidence records referencing a modified file path.
        """
        target = Path(rel_or_abs_path)
        try:
            rel_str = str(target.relative_to(self.workspace_root)).replace("\\", "/")
        except Exception:
            rel_str = str(target).replace("\\", "/")

        invalidated: List[EvidenceRecord] = []
        for rec in self.store.list_all():
            rec_path = rec.source_uri_or_path.replace("\\", "/")
            if rec_path == rel_str or str(target).replace("\\", "/") == rec_path or rec_path.endswith(rel_str):
                if rec.freshness != EvidenceFreshness.INVALIDATED:
                    self.invalidate_record(rec.evidence_id, reason=reason)
                    invalidated.append(rec)

        return invalidated

    def invalidate_for_paths(
        self,
        paths: List[str],
        reason: str = "files_modified",
        task_id: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        """
        Invalidate all evidence records referencing any of the modified file paths.
        """
        all_inv: List[EvidenceRecord] = []
        for p in paths:
            all_inv.extend(self.invalidate_by_file_path(p, reason=reason))
        return all_inv

    def scan_and_reconcile(self) -> List[str]:
        """
        Scan all stored evidence records against current workspace state.
        Mark any records whose underlying files have changed or disappeared as STALE/INVALIDATED.
        Returns list of invalidated evidence IDs.
        """
        invalidated_ids: List[str] = []
        for rec in self.store.list_all():
            if rec.freshness == EvidenceFreshness.FRESH:
                if not self.check_file_freshness(rec):
                    self.invalidate_record(rec.evidence_id, reason="disk_state_mismatch")
                    invalidated_ids.append(rec.evidence_id)
        return invalidated_ids
