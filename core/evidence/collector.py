# core/evidence/collector.py
"""
Objective Evidence Collector for HERMES 2.x.

Core Invariants:
1. TRUTHFUL EXTRACTION: Captures factual environment observations from tool executions and filesystem state.
2. CRYPTOGRAPHIC PROOFS: Computes SHA-256 digests for all referenced files, command outputs, and diffs.
3. CAUSAL PROVENANCE: Every collected evidence record is tied to its originating action, tool call, and agent.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.evidence.models import (
    EvidenceFreshness,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSourceType,
    EvidenceStatus,
    EvidenceTrustClass,
)
from core.evidence.store import EvidenceStore
from core.runtime_state.events import EventType, HermesEvent
from core.event_bus import EventBus


class EvidenceCollector:
    """
    Collects immutable evidence records from physical environment interactions.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        mission_id: str = "default",
        evidence_store: Optional[EvidenceStore] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.mission_id = mission_id
        self.store = evidence_store or EvidenceStore(self.workspace_root, mission_id)
        self.event_bus = event_bus

    def _publish_evidence_created(self, record: EvidenceRecord) -> None:
        """Publish canonical EVIDENCE_CREATED event."""
        if self.event_bus:
            event = HermesEvent(
                event_type=EventType.EVIDENCE_CREATED,
                mission_id=self.mission_id,
                task_id=record.provenance.task_id,
                turn_id=record.provenance.turn_id,
                tool_call_id=record.provenance.tool_call_id,
                agent_id=record.provenance.agent_id,
                worktree_id=record.provenance.worktree_id,
                requirement_id=record.requirement_id,
                acceptance_check_id=record.acceptance_check_id,
                evidence_id=record.evidence_id,
                payload={
                    "evidence_id": record.evidence_id,
                    "kind": record.source_type.value,
                    "source": record.provenance.tool_call_id or "tool",
                    "artifact_path": record.source_uri_or_path,
                    "digest": record.output_digest,
                    "freshness": record.freshness.value,
                    "trust_class": record.trust_class.value,
                },
            )
            self.event_bus.publish(event)

    def collect_file_evidence(
        self,
        rel_path: str,
        requirement_id: Optional[str] = None,
        acceptance_check_id: Optional[str] = None,
        provenance: Optional[EvidenceProvenance] = None,
        check_id: Optional[str] = None,
    ) -> Optional[EvidenceRecord]:
        """Collect file existence, content size, and cryptographic hash evidence."""
        acceptance_check_id = acceptance_check_id or check_id
        full_path = (self.workspace_root / rel_path).resolve()
        prov = provenance or EvidenceProvenance(workspace=str(self.workspace_root))

        if not full_path.exists():
            record = EvidenceRecord(
                evidence_id=f"ev_file_missing_{uuid.uuid4().hex[:6]}",
                mission_id=self.mission_id,
                requirement_id=requirement_id,
                acceptance_check_id=acceptance_check_id,
                source_type=EvidenceSourceType.FILE_EXISTENCE,
                source_uri_or_path=rel_path,
                provenance=prov,
                status=EvidenceStatus.RECORDED,
                freshness=EvidenceFreshness.FRESH,
                trust_class=EvidenceTrustClass.DIRECT_ENVIRONMENT_OBSERVATION,
                exit_code=1,
                assertion_results={"exists": False},
                metadata={"error": "File does not exist on disk"},
            )
            self.store.add(record)
            self._publish_evidence_created(record)
            return record

        try:
            content_bytes = full_path.read_bytes()
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            stat = full_path.stat()

            record = EvidenceRecord(
                evidence_id=f"ev_file_{uuid.uuid4().hex[:6]}",
                mission_id=self.mission_id,
                requirement_id=requirement_id,
                acceptance_check_id=acceptance_check_id,
                source_type=EvidenceSourceType.FILE_CONTENT,
                source_uri_or_path=rel_path,
                provenance=prov,
                status=EvidenceStatus.RECORDED,
                freshness=EvidenceFreshness.FRESH,
                trust_class=EvidenceTrustClass.DIRECT_ENVIRONMENT_OBSERVATION,
                exit_code=0,
                output_digest=content_hash,
                assertion_results={
                    "exists": True,
                    "non_empty": len(content_bytes) > 0,
                },
                metadata={
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                },
            )
            self.store.add(record)
            self._publish_evidence_created(record)
            return record
        except Exception as e:
            return None

    def collect_test_evidence(
        self,
        command: str | List[str],
        exit_code: int,
        stdout: str,
        stderr: str = "",
        duration: float = 0.0,
        passed_count: int = 0,
        failed_count: int = 0,
        error_count: int = 0,
        requirement_id: Optional[str] = None,
        acceptance_check_id: Optional[str] = None,
        provenance: Optional[EvidenceProvenance] = None,
        check_id: Optional[str] = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        """Collect test run evidence with stdout/stderr digests and test assertions."""
        acceptance_check_id = acceptance_check_id or check_id
        prov = provenance or EvidenceProvenance(workspace=str(self.workspace_root))
        cmd_str = command if isinstance(command, str) else " ".join(command)
        out_digest = hashlib.sha256(stdout.encode("utf-8")).hexdigest()

        # Parse test metrics if pytest/npm output
        is_pass = (exit_code == 0 and failed_count == 0 and error_count == 0)
        assertions = {
            "exit_code_zero": (exit_code == 0),
            "no_failures": (failed_count == 0 and error_count == 0),
        }

        record = EvidenceRecord(
            evidence_id=f"ev_test_{uuid.uuid4().hex[:6]}",
            mission_id=self.mission_id,
            requirement_id=requirement_id,
            acceptance_check_id=acceptance_check_id,
            source_type=EvidenceSourceType.TEST_RESULT,
            source_uri_or_path=cmd_str,
            provenance=prov,
            status=EvidenceStatus.VERIFIED if is_pass else EvidenceStatus.RECORDED,
            freshness=EvidenceFreshness.FRESH,
            trust_class=EvidenceTrustClass.DIRECT_ENVIRONMENT_OBSERVATION,
            command=cmd_str,
            exit_code=exit_code,
            output_digest=out_digest,
            assertion_results=assertions,
            metadata={
                "duration_seconds": duration,
                "stdout_preview": stdout[:500],
                "stderr_preview": stderr[:500],
                "passed_count": passed_count,
                "failed_count": failed_count,
                "error_count": error_count,
            },
        )
        self.store.add(record)
        self._publish_evidence_created(record)
        return record

    def collect_from_tool_result(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_result: Any,
        requirement_id: Optional[str] = None,
        acceptance_check_id: Optional[str] = None,
        provenance: Optional[EvidenceProvenance] = None,
    ) -> Optional[EvidenceRecord]:
        """Collect evidence directly from a completed tool execution."""
        prov = provenance or EvidenceProvenance(workspace=str(self.workspace_root))
        canonical = tool_name.strip().lower()

        if canonical in ("fs.write", "fs.edit", "write_file", "edit_file"):
            path_str = arguments.get("path") or arguments.get("target_file")
            if path_str:
                return self.collect_file_evidence(
                    rel_path=path_str,
                    requirement_id=requirement_id,
                    acceptance_check_id=acceptance_check_id,
                    provenance=prov,
                )

        elif canonical in ("shell.bash", "bash", "execute_command"):
            cmd = arguments.get("command", "")
            out = getattr(tool_result, "output", "") or ""
            err = getattr(tool_result, "error", "") or ""
            exit_c = getattr(tool_result, "exit_code", 0) if getattr(tool_result, "success", True) else (getattr(tool_result, "exit_code", 1) or 1)

            # Detect if test command
            is_test = any(kw in cmd.lower() for kw in ("pytest", "unittest", "npm test", "jest", "cargo test"))
            src_type = EvidenceSourceType.TEST_RESULT if is_test else EvidenceSourceType.COMMAND_RESULT

            record = EvidenceRecord(
                evidence_id=f"ev_cmd_{uuid.uuid4().hex[:6]}",
                mission_id=self.mission_id,
                requirement_id=requirement_id,
                acceptance_check_id=acceptance_check_id,
                source_type=src_type,
                source_uri_or_path=cmd,
                provenance=prov,
                status=EvidenceStatus.VERIFIED if exit_c == 0 else EvidenceStatus.RECORDED,
                freshness=EvidenceFreshness.FRESH,
                trust_class=EvidenceTrustClass.DIRECT_ENVIRONMENT_OBSERVATION,
                command=cmd,
                exit_code=exit_c,
                output_digest=hashlib.sha256(out.encode("utf-8")).hexdigest(),
                assertion_results={"exit_code_zero": exit_c == 0},
                metadata={"stdout_preview": out[:300]},
            )
            self.store.add(record)
            self._publish_evidence_created(record)
            return record

        return None
