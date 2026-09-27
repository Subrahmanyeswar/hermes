# core/persistence/models.py
"""
Data models, manifests, and error taxonomy for HERMES 2.x persistence.

Core Invariants:
1. IMMUTABLE CHECKPOINTS: Checkpoints and manifests are immutable once committed.
2. NO SECRETS PERSISTED: API keys, tokens, and passwords must never be stored.
3. EXPLICIT SCHEMAS: No pickle serialization; typed JSON schemas with schema versioning.
4. CONTENT-ADDRESSED BLOBS: Files and large payloads are addressed by SHA-256.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SCHEMA_VERSION: int = 1
RUNTIME_VERSION: str = "2.0.0"


# ── Error Taxonomy ────────────────────────────────────────────────────────────

class PersistenceError(Exception):
    """Base exception for all persistence and recovery operations."""
    pass


class CheckpointNotFound(PersistenceError):
    """Requested checkpoint ID does not exist."""
    pass


class CheckpointCorrupt(PersistenceError):
    """Checkpoint manifest or constituent blobs failed hash verification."""
    pass


class CheckpointSchemaMismatch(PersistenceError):
    """Checkpoint was created with an incompatible schema version."""
    pass


class StorageCorrupt(PersistenceError):
    """Underlying database or blob store integrity check failed."""
    pass


class WorkspaceConflict(PersistenceError):
    """Unresolvable workspace collision during resume, rewind, or fork."""
    pass


class GitDriftDetected(PersistenceError):
    """Git repository state has diverged from checkpoint manifest."""
    pass


class EnvironmentDrift(PersistenceError):
    """Execution environment has diverged from checkpoint manifest."""
    pass


class RecoveryBlocked(PersistenceError):
    """Session recovery cannot proceed safely without manual intervention."""
    pass


class ResumeConflict(PersistenceError):
    """Session cannot be resumed due to active lock or conflicting lineage."""
    pass


class RewindConflict(PersistenceError):
    """Rewind cannot proceed because user edits would be destroyed."""
    pass


class ApprovalInvalidAfterResume(PersistenceError):
    """Cached user approval is invalid or expired upon session resume."""
    pass


class JobRecoveryFailure(PersistenceError):
    """Background job could not be reconciled or safely adopted."""
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING = "WAITING"
    INTERRUPTED = "INTERRUPTED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    FORKED = "FORKED"
    ARCHIVED = "ARCHIVED"


class CheckpointReason(str, Enum):
    MANUAL = "MANUAL"
    PRE_ACTION = "PRE_ACTION"
    POST_ACTION = "POST_ACTION"
    PRE_REPAIR = "PRE_REPAIR"
    POST_VERIFICATION = "POST_VERIFICATION"
    AUTO_PERIODIC = "AUTO_PERIODIC"
    PRE_DESTRUCTIVE = "PRE_DESTRUCTIVE"
    PRE_BRANCH = "PRE_BRANCH"
    PRE_REWIND = "PRE_REWIND"
    SESSION_PAUSE = "SESSION_PAUSE"
    CRASH_RECOVERY = "CRASH_RECOVERY"


class CheckpointTrigger(str, Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    POLICY = "POLICY"
    REPAIR_PIPELINE = "REPAIR_PIPELINE"
    SUPERVISOR = "SUPERVISOR"


class RewindMode(str, Enum):
    CONVERSATION_ONLY = "CONVERSATION_ONLY"
    STATE_ONLY = "STATE_ONLY"
    FILES_ONLY = "FILES_ONLY"
    CODE_AND_CONVERSATION = "CODE_AND_CONVERSATION"
    FULL_SAFE_REWIND = "FULL_SAFE_REWIND"


class FileChangeType(str, Enum):
    TRACKED = "TRACKED"
    UNTRACKED = "UNTRACKED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    ADDED = "ADDED"


class ConflictOwnership(str, Enum):
    AGENT_CHANGE = "AGENT_CHANGE"
    USER_CHANGE = "USER_CHANGE"
    UNKNOWN = "UNKNOWN"


class RecoveryDecisionType(str, Enum):
    RESUME_CLEAN = "RESUME_CLEAN"
    RESUME_WITH_WARNINGS = "RESUME_WITH_WARNINGS"
    WAIT_FOR_USER = "WAIT_FOR_USER"
    REPAIR_SESSION = "REPAIR_SESSION"
    ROLLBACK_TO_PREVIOUS_CHECKPOINT = "ROLLBACK_TO_PREVIOUS_CHECKPOINT"
    BLOCK = "BLOCK"


# ── Domain Manifests ──────────────────────────────────────────────────────────

@dataclass
class FileSnapshot:
    """Snapshot metadata for a single file in the workspace."""
    relative_path: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    blob_id: str
    change_type: FileChangeType = FileChangeType.TRACKED
    is_agent_created: bool = False
    encoding: str = "utf-8"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["change_type"] = self.change_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FileSnapshot:
        d = dict(data)
        d["change_type"] = FileChangeType(d.get("change_type", FileChangeType.TRACKED.value))
        return cls(**d)


@dataclass
class WorkspaceManifest:
    """Complete file state manifest of the workspace at checkpoint time."""
    workspace_root: str
    files: Dict[str, FileSnapshot] = field(default_factory=dict)
    total_files: int = 0
    total_bytes: int = 0
    manifest_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "manifest_hash": self.manifest_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkspaceManifest:
        files = {k: FileSnapshot.from_dict(v) for k, v in data.get("files", {}).items()}
        return cls(
            workspace_root=data.get("workspace_root", ""),
            files=files,
            total_files=data.get("total_files", len(files)),
            total_bytes=data.get("total_bytes", sum(f.size_bytes for f in files.values())),
            manifest_hash=data.get("manifest_hash", ""),
        )


@dataclass
class GitManifest:
    """Structured Git repository metadata snapshot."""
    repo_root: str
    head_sha: str
    branch: str
    is_detached: bool = False
    upstream: Optional[str] = None
    is_dirty: bool = False
    tracked_modifications: List[str] = field(default_factory=list)
    staged_modifications: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)
    staged_diff_stat: str = ""
    unstaged_diff_stat: str = ""
    remote_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GitManifest:
        return cls(**data)


@dataclass
class EnvironmentManifest:
    """Allowlisted execution environment fingerprint. Strictly excludes secrets."""
    os_name: str
    os_version: str
    architecture: str
    python_version: str
    cwd: str
    allowlisted_env: Dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvironmentManifest:
        return cls(**data)


@dataclass
class ProviderManifest:
    """Logical model and network provider state snapshot."""
    provider: str
    model: str
    endpoint: str = ""
    retry_max_attempts: int = 3
    circuit_state: str = "CLOSED"
    consecutive_failures: int = 0
    cooldown_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProviderManifest:
        return cls(**data)


@dataclass
class SecurityManifest:
    """Security policy, approval grants, and denial state snapshot."""
    policy_version: str = "1.0.0"
    active_grants: List[Dict[str, Any]] = field(default_factory=list)
    denial_counts: Dict[str, int] = field(default_factory=dict)
    prompt_injection_warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecurityManifest:
        return cls(**data)


@dataclass
class JobManifest:
    """Snapshot of background jobs and subagent tasks."""
    jobs: List[Dict[str, Any]] = field(default_factory=list)
    subagents: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobManifest:
        return cls(**data)


# ── Checkpoint Manifest ───────────────────────────────────────────────────────

@dataclass
class CheckpointManifest:
    """
    Immutable cross-domain snapshot manifest.
    Contains cryptographic hashes and structured metadata across all runtime domains.
    """
    checkpoint_id: str
    session_id: str
    mission_id: str
    sequence: int
    parent_checkpoint_id: Optional[str] = None
    reason: CheckpointReason = CheckpointReason.MANUAL
    trigger: CheckpointTrigger = CheckpointTrigger.SYSTEM
    created_at: float = field(default_factory=time.time)
    schema_version: int = SCHEMA_VERSION
    runtime_version: str = RUNTIME_VERSION
    state_hash: str = ""
    manifest_hash: str = ""
    transcript_cursor: int = 0
    event_cursor: int = 0
    workspace: WorkspaceManifest = field(default_factory=lambda: WorkspaceManifest(workspace_root=""))
    git: GitManifest = field(default_factory=lambda: GitManifest(repo_root="", head_sha="", branch=""))
    environment: EnvironmentManifest = field(default_factory=lambda: EnvironmentManifest(os_name="", os_version="", architecture="", python_version="", cwd=""))
    provider: ProviderManifest = field(default_factory=lambda: ProviderManifest(provider="", model=""))
    security: SecurityManifest = field(default_factory=SecurityManifest)
    jobs: JobManifest = field(default_factory=JobManifest)
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "mission_id": self.mission_id,
            "sequence": self.sequence,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "reason": self.reason.value,
            "trigger": self.trigger.value,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "runtime_version": self.runtime_version,
            "state_hash": self.state_hash,
            "manifest_hash": self.manifest_hash,
            "transcript_cursor": self.transcript_cursor,
            "event_cursor": self.event_cursor,
            "workspace": self.workspace.to_dict(),
            "git": self.git.to_dict(),
            "environment": self.environment.to_dict(),
            "provider": self.provider.to_dict(),
            "security": self.security.to_dict(),
            "jobs": self.jobs.to_dict(),
            "evidence_refs": self.evidence_refs,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CheckpointManifest:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_id=data["session_id"],
            mission_id=data.get("mission_id", ""),
            sequence=data.get("sequence", 0),
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            reason=CheckpointReason(data.get("reason", CheckpointReason.MANUAL.value)),
            trigger=CheckpointTrigger(data.get("trigger", CheckpointTrigger.SYSTEM.value)),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            runtime_version=data.get("runtime_version", RUNTIME_VERSION),
            state_hash=data.get("state_hash", ""),
            manifest_hash=data.get("manifest_hash", ""),
            transcript_cursor=data.get("transcript_cursor", 0),
            event_cursor=data.get("event_cursor", 0),
            workspace=WorkspaceManifest.from_dict(data.get("workspace", {})),
            git=GitManifest.from_dict(data.get("git", {"repo_root": "", "head_sha": "", "branch": ""})),
            environment=EnvironmentManifest.from_dict(data.get("environment", {"os_name": "", "os_version": "", "architecture": "", "python_version": "", "cwd": ""})),
            provider=ProviderManifest.from_dict(data.get("provider", {"provider": "", "model": ""})),
            security=SecurityManifest.from_dict(data.get("security", {})),
            jobs=JobManifest.from_dict(data.get("jobs", {})),
            evidence_refs=data.get("evidence_refs", []),
            metadata=data.get("metadata", {}),
        )
