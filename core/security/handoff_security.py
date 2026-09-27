# core/security/handoff_security.py
"""
HERMES 2.x - Inbound Subagent Handoff Security Checker (Prompt 13)
Screens child return handoffs, reports, and generated artifacts before parent ingestion.
Prevents compromised or misled workers from injecting directives into the parent context.
"""

from __future__ import annotations

import logging
from typing import Optional, List

from core.security.content_boundary import ContentBoundary
from core.security.enums import ContentTrust, PromptInjectionStatus
from core.security.models import (
    HandoffSecurityAssessment,
    PromptInjectionAssessment,
    SubagentSecurityContext,
)
from core.security.risk import CREDENTIAL_REGEXES

logger = logging.getLogger("hermes.security.handoff")


class HandoffSecurityChecker:
    """
    Validates and screens subagent handoffs before parent agent integration.
    """

    def __init__(self, content_boundary: Optional[ContentBoundary] = None) -> None:
        self.content_boundary = content_boundary or ContentBoundary()

    def inspect_handoff(
        self,
        child_context: SubagentSecurityContext,
        return_payload: str,
        artifacts_produced: Optional[List[str]] = None,
    ) -> HandoffSecurityAssessment:
        """
        Screen the returned payload from a child agent.
        Returns a HandoffSecurityAssessment indicating safety and any detected violations.
        """
        violations: List[str] = []
        is_safe = True

        # 1. Screen return text for prompt injections targeting the parent
        sanitized_payload, injection_assessment = self.content_boundary.process_observation(
            return_payload,
            trust_level=ContentTrust.UNTRUSTED_EXTERNAL,
            source_id=f"subagent_{child_context.agent_id}",
        )

        if injection_assessment.status == PromptInjectionStatus.INJECTION_DETECTED:
            is_safe = False
            violations.append(
                f"Child handoff contains suspected prompt injection attack: {injection_assessment.attack_family}"
            )
        elif injection_assessment.status == PromptInjectionStatus.SUSPICIOUS:
            is_safe = False
            violations.append("Child handoff contains suspicious directives")

        # 2. Check for unauthorized credential leakage in handoff payload
        for cred_regex in CREDENTIAL_REGEXES:
            if cred_regex.search(return_payload):
                is_safe = False
                violations.append("Child handoff contains exposed credential or secret token")
                break

        # 3. Check artifact boundaries
        if artifacts_produced and child_context.path_boundaries:
            for art in artifacts_produced:
                in_boundary = any(art.startswith(b) for b in child_context.path_boundaries)
                if not in_boundary:
                    is_safe = False
                    violations.append(f"Child generated artifact '{art}' outside allowed path boundary")

        has_injection = injection_assessment.status in (
            PromptInjectionStatus.INJECTION_DETECTED,
            PromptInjectionStatus.SUSPICIOUS,
        )

        return HandoffSecurityAssessment(
            subagent_id=child_context.agent_id,
            safe_to_ingest=is_safe,
            injection_detected=has_injection,
            violations=violations,
            sanitized_payload=sanitized_payload if not is_safe else return_payload,
        )
