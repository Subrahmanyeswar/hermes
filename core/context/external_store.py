# core/context/external_store.py
"""
File-backed Externalized Output Storage for HERMES 2.x Context Engine.
Offloads oversized tool outputs and logs into persistent, integrity-checked artifacts
allowing surgical slice retrieval without context pollution.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.runtime_state.events import redact_sensitive_str


class RetentionPolicy(str, Enum):
    """Retention lifecycle for externalized artifacts."""
    EPHEMERAL = "EPHEMERAL"       # Can be cleared quickly under light pressure
    MISSION = "MISSION"           # Retained for duration of current mission
    CHECKPOINT = "CHECKPOINT"     # Must survive for rewind/session checkpointing
    EVIDENCE = "EVIDENCE"         # Must never be deleted by auto GC (formal audit trail)
    PERSISTENT = "PERSISTENT"     # Permanent workspace knowledge


@dataclass
class ExternalizedArtifact:
    """Metadata record for a file-backed externalized output artifact."""
    artifact_id: str
    file_path: str
    size_bytes: int
    sha256_hash: str
    mime_type: str = "text/plain"
    encoding: str = "utf-8"
    line_count: int = 0
    created_at: float = field(default_factory=time.time)
    tool_call_id: str = ""
    tool_name: str = ""
    mission_id: str = ""
    retention_policy: RetentionPolicy = RetentionPolicy.MISSION
    sensitivity: str = "internal"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "sha256_hash": self.sha256_hash,
            "mime_type": self.mime_type,
            "encoding": self.encoding,
            "line_count": self.line_count,
            "created_at": self.created_at,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "mission_id": self.mission_id,
            "retention_policy": self.retention_policy.value,
            "sensitivity": self.sensitivity,
            "metadata": self.metadata,
        }


class ExternalizedOutputStore:
    """
    Thread-safe, file-backed storage for oversized tool execution outputs.
    Ensures data integrity via SHA-256, protects secrets via pre-storage redaction,
    and supports targeted line slicing.
    """

    def __init__(self, base_dir: Optional[Path | str] = None) -> None:
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        elif os.environ.get("HERMES_EXTERNAL_STORE_DIR"):
            self.base_dir = Path(os.environ["HERMES_EXTERNAL_STORE_DIR"]).resolve()
        elif os.environ.get("HERMES_ARTIFACTS_DIR"):
            self.base_dir = (Path(os.environ["HERMES_ARTIFACTS_DIR"]) / "context" / "tool-results").resolve()
        else:
            self.base_dir = Path("artifacts/context/tool-results").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: Dict[str, ExternalizedArtifact] = {}
        self._lock = threading.Lock()

    def put(
        self,
        raw_content: str,
        mission_id: str = "default",
        tool_call_id: str = "",
        tool_name: str = "",
        retention_policy: RetentionPolicy = RetentionPolicy.MISSION,
        sensitivity: str = "internal",
        metadata: Optional[Dict[str, Any]] = None,
        redact_secrets: bool = True,
    ) -> ExternalizedArtifact:
        """
        Store raw content to an externalized file-backed artifact.
        Redacts credentials before writing to disk.
        """
        if redact_secrets:
            sanitized_content = redact_sensitive_str(raw_content)
        else:
            sanitized_content = raw_content

        artifact_id = f"art-{uuid.uuid4().hex[:12]}"
        mission_clean = re_sanitize_path_segment(mission_id)
        target_dir = self.base_dir / mission_clean
        target_dir.mkdir(parents=True, exist_ok=True)

        call_id_clean = re_sanitize_path_segment(tool_call_id) if tool_call_id else artifact_id
        target_file = target_dir / f"{call_id_clean}.json"

        content_bytes = sanitized_content.encode("utf-8", errors="replace")
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        lines = sanitized_content.splitlines()

        payload = {
            "artifact_id": artifact_id,
            "mission_id": mission_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "retention_policy": retention_policy.value,
            "sha256": sha256,
            "created_at": time.time(),
            "content": sanitized_content,
            "metadata": metadata or {},
        }

        # Atomic file write
        temp_file = target_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_file.replace(target_file)

        artifact = ExternalizedArtifact(
            artifact_id=artifact_id,
            file_path=str(target_file),
            size_bytes=len(content_bytes),
            sha256_hash=sha256,
            line_count=len(lines),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            mission_id=mission_id,
            retention_policy=retention_policy,
            sensitivity=sensitivity,
            metadata=metadata or {},
        )

        with self._lock:
            self._artifacts[artifact_id] = artifact

        return artifact

    def get(self, artifact_id: str) -> Optional[str]:
        """Retrieve full text content of stored artifact, verifying integrity."""
        artifact = self._get_artifact_meta(artifact_id)
        if not artifact:
            return None

        p = Path(artifact.file_path)
        if not p.exists():
            return None

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            content = data.get("content", "")
            # Integrity check
            current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if current_hash != artifact.sha256_hash:
                raise ValueError(f"Integrity check failed for artifact '{artifact_id}': hash mismatch")
            return content
        except Exception:
            return None

    def get_slice(
        self,
        artifact_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> Tuple[Optional[str], bool, int]:
        """
        Retrieve line slice from externalized artifact.
        Returns: (sliced_content, has_more, total_lines)
        """
        full_content = self.get(artifact_id)
        if full_content is None:
            return None, False, 0

        lines = full_content.splitlines()
        total = len(lines)
        s_idx = max(0, start_line - 1)
        e_idx = min(total, end_line) if end_line is not None else total

        sliced = lines[s_idx:e_idx]
        has_more = e_idx < total
        return "\n".join(sliced), has_more, total

    def verify_integrity(self, artifact_id: str) -> bool:
        """Verify whether stored file matches recorded SHA-256 hash."""
        artifact = self._get_artifact_meta(artifact_id)
        if not artifact:
            return False
        p = Path(artifact.file_path)
        if not p.exists():
            return False
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            content = data.get("content", "")
            return hashlib.sha256(content.encode("utf-8")).hexdigest() == artifact.sha256_hash
        except Exception:
            return False

    def metadata(self, artifact_id: str) -> Optional[ExternalizedArtifact]:
        """Retrieve artifact metadata record."""
        return self._get_artifact_meta(artifact_id)

    def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists and file is present on disk."""
        meta = self._get_artifact_meta(artifact_id)
        if not meta:
            return False
        return Path(meta.file_path).exists()

    def delete_if_expired(self, max_age_seconds: float) -> int:
        """
        Clean up expired EPHEMERAL and MISSION artifacts.
        Never deletes EVIDENCE or CHECKPOINT artifacts.
        """
        now = time.time()
        deleted_count = 0
        with self._lock:
            to_delete = []
            for art_id, art in self._artifacts.items():
                if art.retention_policy in (RetentionPolicy.EVIDENCE, RetentionPolicy.CHECKPOINT, RetentionPolicy.PERSISTENT):
                    continue
                if (now - art.created_at) > max_age_seconds:
                    to_delete.append(art_id)

            for art_id in to_delete:
                art = self._artifacts.pop(art_id, None)
                if art:
                    try:
                        p = Path(art.file_path)
                        if p.exists():
                            p.unlink()
                            deleted_count += 1
                    except Exception:
                        pass
        return deleted_count

    def clear(self) -> None:
        """Clear memory cache (does not delete EVIDENCE files from disk)."""
        with self._lock:
            self._artifacts.clear()

    def _get_artifact_meta(self, artifact_id: str) -> Optional[ExternalizedArtifact]:
        with self._lock:
            return self._artifacts.get(artifact_id)


def re_sanitize_path_segment(name: str) -> str:
    """Sanitize path component to prevent traversal or illegal characters."""
    return "".join(c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in name)


# Global singleton instance
externalized_output_store = ExternalizedOutputStore()
