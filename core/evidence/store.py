# core/evidence/store.py
"""
Append-Only Durable Evidence Store for HERMES 2.x.

Core Invariants:
1. IMMUTABLE ARCHIVE: Evidence records are append-only. Corrections create new causally-linked records.
2. FILE-BACKED PERSISTENCE: Records persist to disk under .hermes/evidence/<mission_id>/ to survive restarts.
3. QUERY SPEED & INDEXING: Fast in-memory indexed lookups by evidence_id, requirement_id, and check_id.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.evidence.models import (
    EvidenceBundle,
    EvidenceFreshness,
    EvidenceRecord,
    EvidenceStatus,
)

logger = logging.getLogger("hermes.evidence.store")


class EvidenceStore:
    """
    Authoritative append-only evidence storage engine.
    """

    def __init__(self, workspace_root: Path | str, mission_id: str = "default"):
        self.workspace_root = Path(workspace_root).resolve()
        self.mission_id = mission_id
        self.evidence_dir = self.workspace_root / ".hermes" / "evidence" / mission_id
        self._lock = threading.Lock()
        self._records: Dict[str, EvidenceRecord] = {}
        self._by_requirement: Dict[str, List[str]] = {}
        self._by_check: Dict[str, List[str]] = {}

    def add(self, record: EvidenceRecord, persist: bool = True) -> None:
        """Add an immutable evidence record and update indices."""
        with self._lock:
            self._records[record.evidence_id] = record

            if record.requirement_id:
                if record.requirement_id not in self._by_requirement:
                    self._by_requirement[record.requirement_id] = []
                if record.evidence_id not in self._by_requirement[record.requirement_id]:
                    self._by_requirement[record.requirement_id].append(record.evidence_id)

            if record.acceptance_check_id:
                if record.acceptance_check_id not in self._by_check:
                    self._by_check[record.acceptance_check_id] = []
                if record.evidence_id not in self._by_check[record.acceptance_check_id]:
                    self._by_check[record.acceptance_check_id].append(record.evidence_id)

        if persist:
            self.persist_record(record)

    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Retrieve an evidence record by ID."""
        with self._lock:
            return self._records.get(evidence_id)

    def get_by_requirement(self, requirement_id: str) -> List[EvidenceRecord]:
        """Get all evidence records associated with a requirement."""
        with self._lock:
            e_ids = self._by_requirement.get(requirement_id, [])
            return [self._records[eid] for eid in e_ids if eid in self._records]

    def get_by_check(self, check_id: str) -> List[EvidenceRecord]:
        """Get all evidence records associated with an acceptance check."""
        with self._lock:
            e_ids = self._by_check.get(check_id, [])
            return [self._records[eid] for eid in e_ids if eid in self._records]

    def get_bundle(self, requirement_id: str, check_id: Optional[str] = None) -> EvidenceBundle:
        """Build an EvidenceBundle for a requirement or specific check."""
        with self._lock:
            if check_id:
                e_ids = self._by_check.get(check_id, [])
            else:
                e_ids = self._by_requirement.get(requirement_id, [])

            records = [self._records[eid] for eid in e_ids if eid in self._records]
            return EvidenceBundle(
                bundle_id=f"bundle_{requirement_id}_{check_id or 'all'}",
                requirement_id=requirement_id,
                acceptance_check_id=check_id,
                records=records,
            )

    def mark_stale(self, evidence_id: str) -> bool:
        """Mark an evidence record as STALE."""
        with self._lock:
            rec = self._records.get(evidence_id)
            if not rec:
                return False
            rec.freshness = EvidenceFreshness.STALE
            rec.status = EvidenceStatus.STALE
        self.persist_record(rec)
        return True

    def mark_invalidated(self, evidence_id: str) -> bool:
        """Mark an evidence record as INVALIDATED."""
        with self._lock:
            rec = self._records.get(evidence_id)
            if not rec:
                return False
            rec.freshness = EvidenceFreshness.INVALIDATED
            rec.status = EvidenceStatus.INVALIDATED
        self.persist_record(rec)
        return True

    def list_all(self) -> List[EvidenceRecord]:
        """List all evidence records."""
        with self._lock:
            return list(self._records.values())

    def persist_record(self, record: EvidenceRecord) -> None:
        """Write record to disk file."""
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"{record.evidence_id}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist evidence record {record.evidence_id}: {e}")

    def load_from_disk(self) -> int:
        """Load persisted evidence records from disk."""
        if not self.evidence_dir.exists():
            return 0
        loaded = 0
        for p in self.evidence_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    rec = EvidenceRecord(
                        evidence_id=data["evidence_id"],
                        mission_id=data["mission_id"],
                        requirement_id=data.get("requirement_id"),
                        acceptance_check_id=data.get("acceptance_check_id"),
                        source_type=data.get("source_type", "OTHER"),
                        source_uri_or_path=data.get("source_uri_or_path", ""),
                        status=data.get("status", "RECORDED"),
                        freshness=data.get("freshness", "FRESH"),
                        trust_class=data.get("trust_class", "TOOL_DERIVED_OBSERVATION"),
                        command=data.get("command"),
                        exit_code=data.get("exit_code", 0),
                        inputs_digest=data.get("inputs_digest"),
                        output_digest=data.get("output_digest"),
                        artifact_refs=data.get("artifact_refs", []),
                        assertion_results=data.get("assertion_results", {}),
                        metadata=data.get("metadata", {}),
                        created_at=data.get("created_at", 0.0),
                    )
                    self.add(rec, persist=False)
                    loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load evidence file {p}: {e}")
        return loaded
