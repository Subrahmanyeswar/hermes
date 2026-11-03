"""
core/mission_state_manager.py
Hermes 2.x - Authoritative Mission State and Filesystem Reconciliation (Section 17 / Test Group F).

Reconciles disk artifacts, staged files, contracts, validation records, and recovery snapshots.
Derives deterministic next actions and invalidates stale validation evidence when file hashes change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.js_syntax_validator import compute_file_sha256
from core.project_contract import ProjectContract

logger = logging.getLogger("hermes.mission_state_manager")


@dataclass
class ArtifactState:
    path: str
    exists: bool = False
    current_hash: Optional[str] = None
    validated_hash: Optional[str] = None
    is_valid: bool = False
    is_staged_pending: bool = False


@dataclass
class ReconciliationReport:
    mission_id: str
    reconciled_at: float = field(default_factory=time.time)
    artifacts: Dict[str, ArtifactState] = field(default_factory=dict)
    missing_required_files: List[str] = field(default_factory=list)
    unvalidated_files: List[str] = field(default_factory=list)
    unpromoted_staged_files: List[str] = field(default_factory=list)
    invalidated_files: List[str] = field(default_factory=list)
    is_contract_stale: bool = False
    has_conflicting_snapshots: bool = False
    next_action: str = "noop"
    state_hash: str = ""

    def compute_hash(self) -> str:
        d = {
            "mission_id": self.mission_id,
            "missing": sorted(self.missing_required_files),
            "unvalidated": sorted(self.unvalidated_files),
            "unpromoted": sorted(self.unpromoted_staged_files),
            "invalidated": sorted(self.invalidated_files),
            "is_contract_stale": self.is_contract_stale,
            "next_action": self.next_action,
        }
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class MissionStateManager:
    """Authoritative state reconciliation manager for a HERMES mission."""

    def __init__(self, workspace_root: Path | str, mission_id: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.mission_id = mission_id
        self.history: List[ReconciliationReport] = []
        self.validation_records: Dict[str, str] = {}  # rel_path -> validated_sha256

    def record_validation(self, rel_path: str, file_hash: str) -> None:
        """Record successful validation of an artifact at a specific hash."""
        self.validation_records[rel_path] = file_hash

    def invalidate_validation(self, rel_path: str) -> None:
        """Explicitly invalidate prior validation for a file."""
        self.validation_records.pop(rel_path, None)

    def reconcile(
        self,
        contract: Optional[ProjectContract] = None,
        recovery_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> ReconciliationReport:
        """
        Reconcile disk filesystem with mission contract and validation records.
        Deterministically produces a ReconciliationReport and derives the next action.
        """
        ws = self.workspace_root
        report = ReconciliationReport(mission_id=self.mission_id)

        # 1. Stale contract check
        if contract:
            if contract.mission_id and contract.mission_id != self.mission_id:
                report.is_contract_stale = True

        # 2. Conflicting recovery snapshots check
        if recovery_snapshots and len(recovery_snapshots) > 1:
            # Check for divergent heads or hashes
            hashes = {s.get("checkpoint_hash") or s.get("state_hash") for s in recovery_snapshots if s}
            if len(hashes) > 1:
                report.has_conflicting_snapshots = True

        # 3. Detect unpromoted staged files (*.pending.* or *.pending)
        for cand in ws.glob("**/*"):
            if cand.is_file():
                if ".pending" in cand.name:
                    rel = str(cand.relative_to(ws)).replace("\\", "/")
                    report.unpromoted_staged_files.append(rel)

        # 4. Check canonical required files from contract
        required_files = list(contract.required_files) if contract else ["index.html", "style.css", "app.js"]
        for req in required_files:
            file_p = ws / req
            astate = ArtifactState(path=req)
            if not file_p.exists() or not file_p.is_file():
                astate.exists = False
                report.missing_required_files.append(req)
            else:
                astate.exists = True
                curr_h = compute_file_sha256(file_p)
                astate.current_hash = curr_h
                val_h = self.validation_records.get(req)
                astate.validated_hash = val_h

                if val_h is None:
                    # File exists on disk but has never been validated
                    report.unvalidated_files.append(req)
                    astate.is_valid = False
                elif val_h != curr_h:
                    # File on disk changed after validation: invalidate!
                    report.invalidated_files.append(req)
                    astate.is_valid = False
                    # Remove stale validation
                    self.validation_records.pop(req, None)
                else:
                    astate.is_valid = True

            report.artifacts[req] = astate

        # 5. Deterministic derivation of next_action
        if report.is_contract_stale:
            report.next_action = "reconcile_stale_contract"
        elif report.unpromoted_staged_files:
            report.next_action = "promote_staged_artifact"
        elif report.missing_required_files:
            report.next_action = f"generate_missing_file:{report.missing_required_files[0]}"
        elif report.invalidated_files:
            report.next_action = f"revalidate_modified_file:{report.invalidated_files[0]}"
        elif report.unvalidated_files:
            report.next_action = f"validate_artifact:{report.unvalidated_files[0]}"
        elif report.has_conflicting_snapshots:
            report.next_action = "resolve_conflicting_snapshots"
        else:
            report.next_action = "evaluate_completion"

        report.state_hash = report.compute_hash()

        # 6. Preserve history
        self.history.append(report)
        return report
