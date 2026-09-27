# core/evidence/models.py
"""
Durable Evidence Models & Provenance for HERMES 2.x.

Core Invariants:
1. CLAIMS ARE NOT EVIDENCE: Model self-claims and subagent declarations are not evidence.
2. EVIDENCE IS NOT VERIFICATION: Evidence proves facts; verifiers evaluate criteria against evidence.
3. IMMUTABILITY & PROVENANCE: Every evidence record carries causal history, SHA-256 digests, and freshness.
4. TRUST ORDERING:
   DIRECT_ENVIRONMENT_OBSERVATION > TOOL_DERIVED_OBSERVATION > DERIVED_ASSERTION > SUBAGENT_REPORTED > MODEL_CLAIM
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.runtime_state.models import (
    EvidenceFreshness,
    EvidenceTrustClass,
    EvidenceKind,
    EvidenceState,
)


class EvidenceSourceType(str, Enum):
    FILE_EXISTENCE = "FILE_EXISTENCE"
    FILE_CONTENT = "FILE_CONTENT"
    FILE_HASH = "FILE_HASH"
    AST_CHECK = "AST_CHECK"
    JSON_SCHEMA_CHECK = "JSON_SCHEMA_CHECK"
    YAML_CHECK = "YAML_CHECK"
    TEST_RESULT = "TEST_RESULT"
    LINTER_RESULT = "LINTER_RESULT"
    TYPECHECK_RESULT = "TYPECHECK_RESULT"
    BUILD_RESULT = "BUILD_RESULT"
    COMMAND_RESULT = "COMMAND_RESULT"
    PROCESS_RESULT = "PROCESS_RESULT"
    GIT_DIFF = "GIT_DIFF"
    GIT_STATUS = "GIT_STATUS"
    GIT_COMMIT = "GIT_COMMIT"
    PACKAGE_MANIFEST = "PACKAGE_MANIFEST"
    CONFIG_VALIDATION = "CONFIG_VALIDATION"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    SUBAGENT_ARTIFACT = "SUBAGENT_ARTIFACT"
    SUBAGENT_TEST = "SUBAGENT_TEST"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    OTHER = "OTHER"


class EvidenceStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


@dataclass
class EvidenceProvenance:
    """Causal traceability metadata for an evidence record."""
    agent_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    action_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    workspace: str = ""
    worktree_id: Optional[str] = None
    base_commit: Optional[str] = None
    command: Optional[str] = None
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRecord:
    """
    Authoritative, immutable environment evidence record.
    Proves an objective factual observation from the environment or tool execution.
    """
    evidence_id: str
    mission_id: str
    requirement_id: Optional[str] = None
    acceptance_check_id: Optional[str] = None
    source_type: EvidenceSourceType = EvidenceSourceType.OTHER
    source_uri_or_path: str = ""
    provenance: EvidenceProvenance = field(default_factory=EvidenceProvenance)
    status: EvidenceStatus = EvidenceStatus.RECORDED
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH
    trust_class: EvidenceTrustClass = EvidenceTrustClass.TOOL_DERIVED_OBSERVATION
    command: Optional[str] = None
    exit_code: Optional[int] = 0
    inputs_digest: Optional[str] = None
    output_digest: Optional[str] = None
    artifact_refs: List[str] = field(default_factory=list)
    assertion_results: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def compute_sha256(cls, content: str | bytes) -> str:
        """Compute hex SHA-256 digest of string or bytes."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def to_evidence_state(self) -> EvidenceState:
        """Project to canonical runtime state EvidenceState."""
        return EvidenceState(
            evidence_id=self.evidence_id,
            mission_id=self.mission_id,
            task_id=self.provenance.task_id,
            source=self.provenance.tool_call_id or "tool",
            kind=EvidenceKind.TOOL_RESULT,
            status=self.status.value,
            timestamp=self.created_at,
            artifact_path=self.artifact_refs[0] if self.artifact_refs else self.source_uri_or_path,
            verification_reference=self.acceptance_check_id,
            digest=self.output_digest,
            valid=(self.freshness == EvidenceFreshness.FRESH and self.status != EvidenceStatus.REJECTED),
            freshness=self.freshness.value,
            trust_class=self.trust_class.value,
            requirement_id=self.requirement_id,
            acceptance_check_id=self.acceptance_check_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["status"] = self.status.value
        d["freshness"] = self.freshness.value
        d["trust_class"] = self.trust_class.value
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class EvidenceBundle:
    """A collection of correlated evidence records supporting an acceptance check or requirement."""
    bundle_id: str
    requirement_id: str
    acceptance_check_id: Optional[str] = None
    records: List[EvidenceRecord] = field(default_factory=list)

    def add(self, record: EvidenceRecord) -> None:
        self.records.append(record)

    @property
    def is_all_fresh(self) -> bool:
        if not self.records:
            return False
        return all(r.freshness == EvidenceFreshness.FRESH for r in self.records)

    @property
    def has_failures(self) -> bool:
        for r in self.records:
            if r.exit_code is not None and r.exit_code != 0:
                return True
            if any(not passed for passed in r.assertion_results.values()):
                return True
        return False

    def get_latest_record(self) -> Optional[EvidenceRecord]:
        return self.records[-1] if self.records else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "requirement_id": self.requirement_id,
            "acceptance_check_id": self.acceptance_check_id,
            "record_count": len(self.records),
            "is_all_fresh": self.is_all_fresh,
            "records": [r.to_dict() for r in self.records],
        }
