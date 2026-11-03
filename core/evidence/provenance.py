# core/evidence/provenance.py
"""
Mission Output Provenance Manifest and Evidence Verification for HERMES 2.x (Phase E).
Distinguishes HERMES-generated outputs, pre-existing inputs, user-supplied files,
runtime-generated files, and unattributed files by comparing current artifact SHA-256
against the authoritative write and promotion event journal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.project_contract import CanonicalPathResolver
from core.js_syntax_validator import compute_file_sha256

logger = logging.getLogger(__name__)


class ProvenanceClassification(str, Enum):
    HERMES_GENERATED = "HERMES_GENERATED"
    PRE_EXISTING = "PRE_EXISTING"
    USER_SUPPLIED = "USER_SUPPLIED"
    RUNTIME_GENERATED = "RUNTIME_GENERATED"
    UNATTRIBUTED = "UNATTRIBUTED"


@dataclass
class ArtifactProvenanceRecord:
    path: str
    classification: ProvenanceClassification
    current_sha256: str
    recorded_sha256: Optional[str] = None
    size_bytes: int = 0
    latest_event_type: Optional[str] = None
    tool_call_id: Optional[str] = None
    verified_valid: bool = False
    evidence_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


@dataclass
class MissionProvenanceManifest:
    """Complete machine-readable mission provenance report (Phase E4)."""
    mission_id: str
    workspace_root: str
    generated_at: float = field(default_factory=time.time)
    artifacts: Dict[str, ArtifactProvenanceRecord] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "workspace_root": self.workspace_root,
            "generated_at": self.generated_at,
            "artifacts": {k: v.to_dict() for k, v in self.artifacts.items()},
            "summary": self.summary,
        }

    @classmethod
    def generate(
        cls,
        workspace_root: Path | str,
        mission_id: str,
        hermes_write_journal: Optional[List[Dict[str, Any]]] = None,
        pre_existing_files: Optional[Set[str]] = None,
    ) -> MissionProvenanceManifest:
        """
        Build authoritative output provenance manifest.
        Compares disk artifact hashes against the HERMES write/promotion journal.
        """
        ws = Path(workspace_root).resolve()
        pre_existing = pre_existing_files or set()

        # Build lookup from journal: path -> latest record
        journal_by_path: Dict[str, Dict[str, Any]] = {}
        if hermes_write_journal:
            for ev in hermes_write_journal:
                p = ev.get("target_path") or ev.get("path") or ""
                if p:
                    norm = CanonicalPathResolver.normalize_slashes(p)
                    journal_by_path[norm] = ev

        manifest = cls(mission_id=mission_id, workspace_root=str(ws))
        counts: Dict[str, int] = {c.value: 0 for c in ProvenanceClassification}

        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in {".git", "venv", ".pytest_cache", "__pycache__", "node_modules", ".hermes"}]
            for file in files:
                full_p = Path(root) / file
                rel_str = CanonicalPathResolver.normalize_slashes(str(full_p.relative_to(ws)))
                size = full_p.stat().st_size
                curr_sha = compute_file_sha256(full_p) or ""

                # Determine classification
                journal_ev = journal_by_path.get(rel_str)
                if journal_ev:
                    recorded_sha = journal_ev.get("sha256") or journal_ev.get("content_sha256")
                    if recorded_sha == curr_sha:
                        cls_type = ProvenanceClassification.HERMES_GENERATED
                    else:
                        cls_type = ProvenanceClassification.UNATTRIBUTED
                    ev_type = journal_ev.get("event_type") or journal_ev.get("source_type")
                    tool_id = journal_ev.get("tool_call_id") or journal_ev.get("action_id")
                    rec_sha = recorded_sha
                elif rel_str in pre_existing:
                    cls_type = ProvenanceClassification.PRE_EXISTING
                    ev_type = "INPUT_DISCOVERY"
                    tool_id = None
                    rec_sha = None
                elif full_p.suffix in (".db", ".sqlite", ".sqlite3", ".log") or "cache" in rel_str.lower():
                    cls_type = ProvenanceClassification.RUNTIME_GENERATED
                    ev_type = "RUNTIME_EXECUTION"
                    tool_id = None
                    rec_sha = None
                else:
                    cls_type = ProvenanceClassification.UNATTRIBUTED
                    ev_type = None
                    tool_id = None
                    rec_sha = None

                counts[cls_type.value] += 1
                manifest.artifacts[rel_str] = ArtifactProvenanceRecord(
                    path=rel_str,
                    classification=cls_type,
                    current_sha256=curr_sha,
                    recorded_sha256=rec_sha,
                    size_bytes=size,
                    latest_event_type=ev_type,
                    tool_call_id=tool_id,
                    verified_valid=(cls_type == ProvenanceClassification.HERMES_GENERATED),
                )

        manifest.summary = counts
        return manifest
