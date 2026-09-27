# core/security/audit.py
"""
HERMES 2.x - Security Audit Logger (Prompt 13)
Maintains an immutable, structured, credential-redacted audit trail of all
risk assessments, permission decisions, grants, denials, and injection events.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from core.security.risk import redact_sensitive_text

logger = logging.getLogger("hermes.security.audit")


class SecurityAuditLogger:
    """
    Structured audit logger for security events.
    Applies credential redaction to all logged records.
    """

    def __init__(self, log_file_path: Optional[str] = None) -> None:
        self.log_file_path = log_file_path
        self._in_memory_records: List[Dict[str, Any]] = []

    def log_record(
        self,
        event_name: str,
        details: Dict[str, Any],
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a security audit event with automatic redaction."""
        record = {
            "timestamp": time.time(),
            "event": event_name,
            "session_id": session_id,
            "agent_id": agent_id,
            "details": self._redact_dict(details),
        }

        self._in_memory_records.append(record)
        logger.info("SECURITY_AUDIT: %s (agent=%s, session=%s)", event_name, agent_id, session_id)

        # Write to JSONL file if path configured
        if self.log_file_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.log_file_path)), exist_ok=True)
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.error("Failed to append to security audit log file %s: %s", self.log_file_path, e)

        return record

    def get_records(self) -> List[Dict[str, Any]]:
        """Return in-memory records."""
        return list(self._in_memory_records)

    def _redact_dict(self, data: Any) -> Any:
        """Recursively redact strings inside dictionaries/lists."""
        if isinstance(data, str):
            return redact_sensitive_text(data)
        elif isinstance(data, dict):
            return {k: self._redact_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._redact_dict(v) for v in data]
        return data
