# core/context/models.py
"""
Canonical Context Models, Section Taxonomy, and Provenance for HERMES 2.x Context Engine.
Ensures context items carry strict provenance, freshness tracking, and structured ordering.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContextSectionType(str, Enum):
    """
    Canonical Section Taxonomy in strict presentation order.
    Sections must appear in this order in the final assembled ContextPack.
    """
    SYSTEM = "SYSTEM"
    PROJECT_RULES = "PROJECT_RULES"
    SCOPED_RULES = "SCOPED_RULES"
    CURRENT_GOAL = "CURRENT_GOAL"
    ACTIVE_REQUIREMENTS = "ACTIVE_REQUIREMENTS"
    RELEVANT_FILES = "RELEVANT_FILES"
    RECENT_CHANGES = "RECENT_CHANGES"
    RELEVANT_MEMORY = "RELEVANT_MEMORY"
    ACTIVE_TOOLS = "ACTIVE_TOOLS"
    EVIDENCE = "EVIDENCE"
    RECENT_OBSERVATIONS = "RECENT_OBSERVATIONS"
    RESERVE = "RESERVE"


class ContextSourceType(str, Enum):
    """Provenance origin of context content."""
    SYSTEM = "system"
    PROJECT_RULE = "project_rule"
    SCOPED_RULE = "scoped_rule"
    RUNTIME_STATE = "runtime_state"
    REQUIREMENT = "requirement"
    FILE = "file"
    CHANGE = "change"
    MEMORY = "memory"
    TOOL_SPEC = "tool_spec"
    EVIDENCE = "evidence"
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    COMPACTION_SUMMARY = "compaction_summary"
    USER = "user"


class ContextFreshness(str, Enum):
    """Freshness state of context content."""
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    INVALIDATED = "INVALIDATED"


class ContextPriority(str, Enum):
    """
    Strict priority tier for budgeting and compaction retention.
    MANDATORY items must never be dropped by relevance ranking or microcompaction.
    """
    MANDATORY = "MANDATORY"
    IMPORTANT = "IMPORTANT"
    OPTIONAL = "OPTIONAL"
    DISCARDABLE = "DISCARDABLE"


@dataclass
class ContextProvenance:
    """Provenance metadata tracking where context originated."""
    source_type: ContextSourceType
    source_id: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    content_hash: Optional[str] = None
    file_identity: Optional[Any] = None
    turn_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    evidence_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "content_hash": self.content_hash,
            "turn_id": self.turn_id,
            "tool_call_id": self.tool_call_id,
            "evidence_id": self.evidence_id,
            "timestamp": self.timestamp,
        }


@dataclass
class ContextItem:
    """
    Canonical Context Item.
    Atomic unit of context with full provenance, freshness, and lifecycle metadata.
    """
    id: str
    section: ContextSectionType
    content: str
    provenance: ContextProvenance
    priority: ContextPriority = ContextPriority.OPTIONAL
    relevance_score: float = 0.5
    freshness: ContextFreshness = ContextFreshness.FRESH
    token_estimate: int = 0
    pinned: bool = False
    externalized: bool = False
    external_ref: Optional[str] = None
    cleared: bool = False
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.token_estimate:
            # Fallback heuristic: ~4 characters per token
            self.token_estimate = max(1, len(self.content) // 4)

    def mark_stale(self, reason: str = "") -> None:
        """Mark item as stale when backing file or evidence changes."""
        self.freshness = ContextFreshness.STALE
        self.updated_at = time.time()
        if reason:
            self.metadata["stale_reason"] = reason

    def mark_invalidated(self, reason: str = "") -> None:
        """Mark item as invalidated by authoritative state change."""
        self.freshness = ContextFreshness.INVALIDATED
        self.updated_at = time.time()
        if reason:
            self.metadata["invalidated_reason"] = reason

    def mark_cleared(self, summary: str, external_ref: Optional[str] = None) -> None:
        """Clear bulky inline content while preserving summary and retrieval reference."""
        self.cleared = True
        self.summary = summary
        if external_ref:
            self.external_ref = external_ref
            self.externalized = True
        self.content = f"[CLEARED: {summary}]"
        self.token_estimate = max(1, len(self.content) // 4)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "section": self.section.value,
            "content_length": len(self.content),
            "priority": self.priority.value,
            "relevance_score": self.relevance_score,
            "freshness": self.freshness.value,
            "token_estimate": self.token_estimate,
            "pinned": self.pinned,
            "externalized": self.externalized,
            "external_ref": self.external_ref,
            "cleared": self.cleared,
            "summary": self.summary,
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ContextVersion:
    """Monotonic context version metadata tracking every context rebuild."""
    context_version: int
    mission_id: str
    turn_id: str
    compaction_id: Optional[str] = None
    source_state_version: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_version": self.context_version,
            "mission_id": self.mission_id,
            "turn_id": self.turn_id,
            "compaction_id": self.compaction_id,
            "source_state_version": self.source_state_version,
            "created_at": self.created_at,
        }


@dataclass
class ActiveFileSnippet:
    """Lightweight reference to a line-addressable file snippet retained in context."""
    path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    file_identity: Optional[Any] = None
    is_modified_in_mission: bool = False
    last_accessed: float = field(default_factory=time.time)
