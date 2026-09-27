# core/sessions/transcript.py
"""
Typed transcript persistence and copy-on-write branching for HERMES 2.x.

Core Invariants:
1. IMMUTABLE RECORDS: Transcripts are append-only; historical entries are never modified.
2. COPY-ON-WRITE BRANCHING: Child branches inherit ancestor messages without duplication.
3. LARGE PAYLOAD CAS: Payloads exceeding threshold are externalized to the BlobStore.
4. FORENSIC FIDELITY: Preserves exact execution lineage and causal parentage.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase


class MessageType(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    SECURITY = "SECURITY"
    VERIFICATION = "VERIFICATION"
    SUBAGENT = "SUBAGENT"
    COMPACTION = "COMPACTION"
    CHECKPOINT = "CHECKPOINT"
    RECOVERY = "RECOVERY"


@dataclass
class TranscriptEntry:
    """Canonical typed record for a single conversation/transcript message."""
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:10]}")
    session_id: str = ""
    mission_id: str = ""
    turn_id: Optional[str] = None
    sequence: int = 0
    role: str = "user"
    message_type: MessageType = MessageType.USER
    timestamp: float = field(default_factory=time.time)
    content: str = ""
    blob_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    security_classification: str = "SAFE"
    parent_message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["message_type"] = self.message_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TranscriptEntry:
        d = dict(data)
        d["message_type"] = MessageType(d.get("message_type", MessageType.USER.value))
        return cls(**d)


class TranscriptStore:
    """
    Manages persistent, immutable transcripts with copy-on-write branching.
    """

    def __init__(self, db: SQLiteDatabase, blob_store: BlobStore, large_payload_threshold: int = 65536):
        self.db = db
        self.blob_store = blob_store
        self.threshold = large_payload_threshold

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: MessageType = MessageType.USER,
        turn_id: Optional[str] = None,
        sequence: Optional[int] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        security_classification: str = "SAFE",
    ) -> TranscriptEntry:
        """
        Append a single immutable transcript entry.
        Externalizes to CAS blob store if content exceeds large_payload_threshold.
        """
        meta = metadata.copy() if metadata else {}
        blob_id = None

        stored_content = content
        if len(content.encode("utf-8")) > self.threshold:
            blob_id = self.blob_store.put(content.encode("utf-8"))
            meta["externalized_blob_id"] = blob_id
            stored_content = f"[EXTERNALIZED_CONTENT: blob_id={blob_id}, size={len(content)} bytes]"

        existing = self.db.get_transcript_entries(session_id)
        seq = sequence if sequence is not None else (len(existing) + 1)
        msg_id = f"msg_{uuid.uuid4().hex[:10]}"
        now = time.time()

        entry = TranscriptEntry(
            message_id=msg_id,
            session_id=session_id,
            turn_id=turn_id,
            sequence=seq,
            role=role,
            message_type=message_type,
            timestamp=now,
            content=stored_content,
            blob_id=blob_id,
            metadata=meta,
            security_classification=security_classification,
            parent_message_id=parent_message_id,
        )

        self.db.append_transcript_entry(
            message_id=msg_id,
            session_id=session_id,
            sequence=seq,
            role=role,
            message_type=message_type.value,
            timestamp=now,
            content=stored_content,
            turn_id=turn_id,
            parent_message_id=parent_message_id,
            metadata=meta,
        )
        return entry

    def get_messages(
        self,
        session_id: str,
        parent_session_id: Optional[str] = None,
        fork_sequence: Optional[int] = None,
    ) -> List[TranscriptEntry]:
        """
        Retrieve messages for a session.
        If this session is a branch/fork, seamlessly prepends inherited ancestor messages up to fork_sequence (COW).
        """
        inherited_entries: List[TranscriptEntry] = []
        if parent_session_id and fork_sequence is not None:
            parent_rows = self.db.get_transcript_entries(parent_session_id, from_seq=1, to_seq=fork_sequence)
            for r in parent_rows:
                entry = TranscriptEntry(
                    message_id=r["message_id"],
                    session_id=r["session_id"],
                    turn_id=r.get("turn_id"),
                    sequence=r["sequence"],
                    role=r["role"],
                    message_type=MessageType(r["message_type"]),
                    timestamp=r["timestamp"],
                    content=r["content"],
                    metadata=r.get("metadata", {}),
                    parent_message_id=r.get("parent_message_id"),
                )
                inherited_entries.append(entry)

        current_rows = self.db.get_transcript_entries(session_id)
        current_entries: List[TranscriptEntry] = []
        for r in current_rows:
            entry = TranscriptEntry(
                message_id=r["message_id"],
                session_id=r["session_id"],
                turn_id=r.get("turn_id"),
                sequence=r["sequence"],
                role=r["role"],
                message_type=MessageType(r["message_type"]),
                timestamp=r["timestamp"],
                content=r["content"],
                metadata=r.get("metadata", {}),
                parent_message_id=r.get("parent_message_id"),
            )
            current_entries.append(entry)

        return inherited_entries + current_entries

    def resolve_content(self, entry: TranscriptEntry) -> str:
        """Resolve full content, reading from BlobStore if externalized."""
        if entry.blob_id:
            try:
                data = self.blob_store.get(entry.blob_id)
                return data.decode("utf-8")
            except Exception:
                return entry.content
        return entry.content
