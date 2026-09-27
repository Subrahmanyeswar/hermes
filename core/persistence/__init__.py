# core/persistence/__init__.py
"""
HERMES 2.x Persistence Subsystem.
Authoritative storage, append-only event journals, content-addressed blob store,
and deterministic serialization.
"""

from core.persistence.models import (
    SCHEMA_VERSION,
    RUNTIME_VERSION,
    PersistenceError,
    CheckpointNotFound,
    CheckpointCorrupt,
    CheckpointSchemaMismatch,
    StorageCorrupt,
    WorkspaceConflict,
    GitDriftDetected,
    EnvironmentDrift,
    RecoveryBlocked,
    ResumeConflict,
    RewindConflict,
    ApprovalInvalidAfterResume,
    JobRecoveryFailure,
    SessionStatus,
    CheckpointReason,
    CheckpointTrigger,
    RewindMode,
    FileChangeType,
    ConflictOwnership,
    RecoveryDecisionType,
    FileSnapshot,
    WorkspaceManifest,
    GitManifest,
    EnvironmentManifest,
    ProviderManifest,
    SecurityManifest,
    JobManifest,
    CheckpointManifest,
)
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.journal import EventJournal
from core.persistence.locks import SessionLock
from core.persistence.transactions import atomic_write
from core.persistence.serializer import (
    serialize_runtime_state,
    deserialize_runtime_state,
    compute_state_hash,
)

__all__ = [
    "SCHEMA_VERSION",
    "RUNTIME_VERSION",
    "PersistenceError",
    "CheckpointNotFound",
    "CheckpointCorrupt",
    "CheckpointSchemaMismatch",
    "StorageCorrupt",
    "WorkspaceConflict",
    "GitDriftDetected",
    "EnvironmentDrift",
    "RecoveryBlocked",
    "ResumeConflict",
    "RewindConflict",
    "ApprovalInvalidAfterResume",
    "JobRecoveryFailure",
    "SessionStatus",
    "CheckpointReason",
    "CheckpointTrigger",
    "RewindMode",
    "FileChangeType",
    "ConflictOwnership",
    "RecoveryDecisionType",
    "FileSnapshot",
    "WorkspaceManifest",
    "GitManifest",
    "EnvironmentManifest",
    "ProviderManifest",
    "SecurityManifest",
    "JobManifest",
    "CheckpointManifest",
    "BlobStore",
    "SQLiteDatabase",
    "EventJournal",
    "SessionLock",
    "atomic_write",
    "serialize_runtime_state",
    "deserialize_runtime_state",
    "compute_state_hash",
]
