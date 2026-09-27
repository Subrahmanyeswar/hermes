# core/verification/engine.py
"""
Deterministic Verification Engine for HERMES 2.x.

Core Invariants:
1. EVIDENCE-BASED DECISIONS: Every verification decision is grounded in fresh, durable evidence.
2. DIVERSE VERIFICATION METHODS: Dispatches filesystem, syntax, schema, and test-based evaluations.
3. FINGERPRINT REPRODUCIBILITY: Evaluated verdicts are fingerprinted with evidence digests.
4. CANONICAL EVENTING: Emits VERIFICATION_PASSED, VERIFICATION_FAILED, VERIFICATION_INCONCLUSIVE, or VERIFICATION_BLOCKED.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.event_bus import EventBus
from core.evidence.models import EvidenceFreshness, EvidenceRecord, EvidenceStatus
from core.evidence.store import EvidenceStore
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import FailureClass
from core.verification.models import CheckType, VerificationResult, VerificationVerdict
from core.verification.verifiers import (
    BaseVerifier,
    CompositeVerifier,
    FilesystemVerifier,
    JsonSchemaVerifier,
    PythonAstVerifier,
    TestResultVerifier,
)

logger = logging.getLogger("hermes.verification.engine")


class VerificationEngine:
    """
    Executes deterministic verification across workspace evidence.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        evidence_store: EvidenceStore,
        event_bus: Optional[EventBus] = None,
        mission_id: str = "default",
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = evidence_store
        self.event_bus = event_bus
        self.mission_id = mission_id

        # Built-in deterministic verifiers
        self.fs_verifier = FilesystemVerifier(self.workspace_root)
        self.ast_verifier = PythonAstVerifier(self.workspace_root)
        self.json_verifier = JsonSchemaVerifier(self.workspace_root)
        self.test_verifier = TestResultVerifier()

        # Cache of evaluated results by (check_id, evidence_digest)
        self._cache: Dict[str, VerificationResult] = {}

    def _compute_fingerprint(
        self,
        check_id: str,
        evidence_ids: List[str],
        check_type: str = "",
        criteria: Optional[Dict[str, Any]] = None,
        policy_version: str = "2.0.0",
    ) -> str:
        h = hashlib.sha256(f"{check_id}:{check_type}:{policy_version}".encode("utf-8"))
        if criteria:
            crit_str = json.dumps(criteria, sort_keys=True, default=str)
            h.update(f":criteria:{crit_str}".encode("utf-8"))
        for eid in sorted(evidence_ids):
            rec = self.store.get(eid)
            digest = rec.output_digest if rec else ""
            h.update(f":{eid}:{digest}".encode("utf-8"))
        return h.hexdigest()

    def _publish_result_event(self, result: VerificationResult, task_id: Optional[str] = None) -> None:
        """Publish canonical verification event based on verdict."""
        if not self.event_bus:
            return

        type_map = {
            VerificationVerdict.PASS: EventType.VERIFICATION_PASSED,
            VerificationVerdict.FAIL: EventType.VERIFICATION_FAILED,
            VerificationVerdict.INCONCLUSIVE: EventType.VERIFICATION_INCONCLUSIVE,
            VerificationVerdict.BLOCKED: EventType.VERIFICATION_BLOCKED,
        }
        event_type = type_map.get(result.verdict, EventType.VERIFICATION_FAILED)

        event = HermesEvent(
            event_type=event_type,
            mission_id=self.mission_id,
            task_id=task_id,
            requirement_id=result.requirement_id,
            acceptance_check_id=result.check_id,
            payload={
                "check_id": result.check_id,
                "requirement_id": result.requirement_id,
                "verdict": result.verdict.value,
                "passed": result.passed,
                "message": result.message,
                "failure_class": result.failure_class.value if result.failure_class else None,
                "evidence_ids": result.evidence_ids,
                "duration_ms": result.duration_ms,
                "fingerprint": result.fingerprint,
            },
        )
        self.event_bus.publish(event)

    def verify_check(
        self,
        check_id: str,
        check_type: CheckType | str,
        requirement_id: Optional[str] = None,
        task_id: Optional[str] = None,
        bypass_cache: bool = False,
        **kwargs: Any,
    ) -> VerificationResult:
        """
        Verify a single acceptance check against its associated evidence bundle.
        """
        t0 = time.time()
        bundle = self.store.get_bundle(requirement_id or "default", check_id=check_id)

        # Invariant: If there is no evidence recorded, cannot pass
        if not bundle.records:
            res = VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message=f"No evidence records found for acceptance check {check_id}",
                duration_ms=(time.time() - t0) * 1000.0,
            )
            self._publish_result_event(res, task_id=task_id)
            return res

        # Invariant: Check freshness of evidence
        stale_records = [r for r in bundle.records if r.freshness != EvidenceFreshness.FRESH]
        if stale_records:
            res = VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"Evidence for check {check_id} is stale or invalidated ({len(stale_records)} stale records)",
                evidence_ids=[r.evidence_id for r in bundle.records],
                duration_ms=(time.time() - t0) * 1000.0,
            )
            self._publish_result_event(res, task_id=task_id)
            return res

        # Dispatch verifier
        ct = check_type.value if isinstance(check_type, CheckType) else check_type.upper()

        # Check fingerprint cache
        evidence_ids = [r.evidence_id for r in bundle.records]
        fingerprint = self._compute_fingerprint(
            check_id=check_id,
            evidence_ids=evidence_ids,
            check_type=ct,
            criteria=kwargs,
        )
        if not bypass_cache and fingerprint in self._cache:
            return self._cache[fingerprint]
        if ct == CheckType.FILESYSTEM.value:
            result = self.fs_verifier.verify(check_id, bundle, requirement_id=requirement_id, **kwargs)
        elif ct == CheckType.PYTHON_AST.value:
            result = self.ast_verifier.verify(check_id, bundle, requirement_id=requirement_id, **kwargs)
        elif ct == CheckType.JSON_SCHEMA.value:
            result = self.json_verifier.verify(check_id, bundle, requirement_id=requirement_id, **kwargs)
        elif ct == CheckType.TEST_RESULT.value:
            result = self.test_verifier.verify(check_id, bundle, requirement_id=requirement_id, **kwargs)
        elif ct == CheckType.COMMAND_EXIT.value:
            # Check exit code of command evidence
            latest = bundle.get_latest_record()
            if latest and latest.exit_code == 0:
                result = VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.PASS,
                    message="Command executed with exit code 0",
                    evidence_ids=evidence_ids,
                )
            else:
                ec = latest.exit_code if latest else -1
                result = VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.FAIL,
                    failure_class=FailureClass.TOOL_EXECUTION_ERROR,
                    message=f"Command failed with exit code {ec}",
                    evidence_ids=evidence_ids,
                )
        else:
            # Default fallback: check if bundle has no failures
            if bundle.has_failures:
                result = VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.FAIL,
                    failure_class=FailureClass.ASSERTION_FAILED,
                    message=f"Evidence bundle contains observed failures for {check_id}",
                    evidence_ids=evidence_ids,
                )
            else:
                result = VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.PASS,
                    message=f"Default evidence check passed for {check_id}",
                    evidence_ids=evidence_ids,
                )

        result.fingerprint = fingerprint
        result.duration_ms = (time.time() - t0) * 1000.0

        # Store in cache
        self._cache[fingerprint] = result

        # Publish event
        self._publish_result_event(result, task_id=task_id)

        return result
