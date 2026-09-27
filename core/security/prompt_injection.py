# core/security/prompt_injection.py
"""
HERMES 2.x - Prompt-Injection Probe & Untrusted Content Screening (Prompt 13)
Detects instruction overrides, authority spoofing, covert exfiltration, delimiter attacks,
and jailbreak patterns with provenance-aware scoring and false-positive guards.
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple, Dict, Any

from core.security.enums import (
    ContentTrust,
    InjectionAttackFamily,
    PromptInjectionStatus,
)
from core.security.models import PromptInjectionAssessment

logger = logging.getLogger("hermes.security.prompt_injection")

# Regex patterns for attack families
INSTRUCTION_OVERRIDE_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|directives|rules|guidelines)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|system\s+prompts?|rules)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior)\s+(instructions|conversations|rules)", re.IGNORECASE),
    re.compile(r"from\s+now\s+on[\s,]+(you\s+(must|should|will)|act\s+as|pretend)", re.IGNORECASE),
    re.compile(r"new\s+system\s+(prompt|instructions?|rule)\s*[:=]", re.IGNORECASE),
    re.compile(r"you\s+are\s+no\s+longer\s+(hermes|bound\s+by|restricted)", re.IGNORECASE),
    re.compile(r"override\s+system\s+directives?", re.IGNORECASE),
    re.compile(r"bypass\s+all\s+(security|safety|permission)\s+(checks|controls|policies)", re.IGNORECASE),
]

AUTHORITY_SPOOFING_PATTERNS = [
    re.compile(r"(system|admin|administrator|developer|root|superuser)\s*:\s*(please\s+)?(execute|run|do|ignore)", re.IGNORECASE),
    re.compile(r"\[system\s+message\]", re.IGNORECASE),
    re.compile(r"\[developer\s+mode(\s+enabled)?\]", re.IGNORECASE),
    re.compile(r"message\s+from\s+(the\s+)?(system|admin|hermes\s+team|anthropic)", re.IGNORECASE),
    re.compile(r"authorized\s+security\s+override", re.IGNORECASE),
    re.compile(r"emergency\s+override\s+code\s*[:=]", re.IGNORECASE),
]

EXFILTRATION_PATTERNS = [
    # Markdown image tags with exfiltration URLs: ![leak](https://...?data=...)
    re.compile(r"!\[.*?\]\((https?://[^\s\)]+[\?&](?:token|key|secret|data|exfil|leak|c)=[^\s\)]+)\)", re.IGNORECASE),
    # HTML image / link exfiltration
    re.compile(r"<img\s+[^>]*src=[\"'](https?://[^\s\"']+[\?&](?:token|key|secret|data|exfil|leak)=[^\s\"']+)[\"']", re.IGNORECASE),
    # Direct instruction to send secrets
    re.compile(r"(curl|fetch|wget|send|post|transmit)\s+.*?(env|\.env|api[_-]key|secret|password|credential|token)\s+to\s+https?://", re.IGNORECASE),
]

DELIMITER_INJECTION_PATTERNS = [
    re.compile(r"</?observation>", re.IGNORECASE),
    re.compile(r"</?system>", re.IGNORECASE),
    re.compile(r"</?tool_call>", re.IGNORECASE),
    re.compile(r"</?assistant>", re.IGNORECASE),
    re.compile(r"<!--\s*hermes-internal-directive", re.IGNORECASE),
    re.compile(r"```(json|xml)\s*\{\s*\"__hermes_internal__\"", re.IGNORECASE),
]

JAILBREAK_PATTERNS = [
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"do\s+anything\s+now", re.IGNORECASE),
    re.compile(r"unrestricted\s+mode\s+activated", re.IGNORECASE),
    re.compile(r"hypothetical\s+rule-free\s+scenario", re.IGNORECASE),
    re.compile(r"anti-censorship\s+override", re.IGNORECASE),
]

CREDENTIAL_HARVESTING_PATTERNS = [
    re.compile(r"(print|echo|cat|display|output|show)\s+(the\s+)?(api[_-]?key|secret[_-]?key|token|auth[_-]?token|password|\.env)", re.IGNORECASE),
    re.compile(r"what\s+is\s+the\s+(value\s+of\s+)?(api[_-]?key|token|password|auth|secret)", re.IGNORECASE),
    re.compile(r"dump\s+(all\s+)?(environment\s+variables|env\s+vars|\.env|secrets)", re.IGNORECASE),
]


class PromptInjectionProbe:
    """
    Analyzes text payloads across input and tool observations to detect
    prompt injection attacks, malicious overrides, delimiter evasion, and covert leaks.
    """

    def __init__(self, sensitivity: float = 0.5) -> None:
        self.sensitivity = sensitivity

    def screen_text(
        self,
        text: str,
        trust_level: ContentTrust = ContentTrust.UNTRUSTED_EXTERNAL,
        source_id: Optional[str] = None,
    ) -> PromptInjectionAssessment:
        """
        Screen arbitrary text for prompt-injection markers.
        Takes into account content provenance (untrusted web vs user prompt).
        """
        if not text or not text.strip():
            return PromptInjectionAssessment(
                status=PromptInjectionStatus.SAFE,
                confidence=0.0,
                source_id=source_id,
            )

        detected_families: List[InjectionAttackFamily] = []
        matched_indicators: List[str] = []
        raw_score = 0.0

        # 1. Instruction Overrides
        for pattern in INSTRUCTION_OVERRIDE_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.OVERRIDE_INSTRUCTION)
                matched_indicators.append(f"Override directive: '{match.group(0)}'")
                raw_score += 0.4
                break

        # 2. Authority Spoofing
        for pattern in AUTHORITY_SPOOFING_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.AUTHORITY_SPOOFING)
                matched_indicators.append(f"Authority spoof: '{match.group(0)}'")
                raw_score += 0.4
                break

        # 3. Covert Exfiltration
        for pattern in EXFILTRATION_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.EXFILTRATION_TRIGGER)
                matched_indicators.append(f"Exfiltration pattern: '{match.group(0)}'")
                raw_score += 0.7
                break

        # 4. Delimiter Injection
        for pattern in DELIMITER_INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.DELIMITER_INJECTION)
                matched_indicators.append(f"Delimiter injection: '{match.group(0)}'")
                raw_score += 0.35
                break

        # 5. Jailbreak patterns
        for pattern in JAILBREAK_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.JAILBREAK_ATTEMPT)
                matched_indicators.append(f"Jailbreak signature: '{match.group(0)}'")
                raw_score += 0.5
                break

        # 6. Credential Harvesting
        for pattern in CREDENTIAL_HARVESTING_PATTERNS:
            match = pattern.search(text)
            if match:
                detected_families.append(InjectionAttackFamily.SYSTEM_PROMPT_EXTRACTION)
                matched_indicators.append(f"Credential harvesting directive: '{match.group(0)}'")
                raw_score += 0.35
                break

        # Provenance weighting:
        # Untrusted external web content or files have higher suspicion weight
        if trust_level in (ContentTrust.UNTRUSTED_EXTERNAL, ContentTrust.UNTRUSTED_FILE):
            raw_score *= 1.2
        elif trust_level == ContentTrust.TRUSTED_USER:
            # User direct commands may discuss these concepts without attacking
            raw_score *= 0.7
        elif trust_level == ContentTrust.TRUSTED_SYSTEM:
            raw_score *= 0.3

        confidence = min(1.0, round(raw_score, 3))

        # Determine status
        if confidence >= 0.75:
            status = PromptInjectionStatus.INJECTION_DETECTED
        elif confidence >= 0.35:
            status = PromptInjectionStatus.SUSPICIOUS
        else:
            status = PromptInjectionStatus.SAFE

        primary_family = detected_families[0] if detected_families else None

        reason = None
        if status != PromptInjectionStatus.SAFE:
            reason = f"Detected {len(matched_indicators)} potential injection marker(s): {'; '.join(matched_indicators[:3])}"

        return PromptInjectionAssessment(
            status=status,
            confidence=confidence,
            attack_family=primary_family,
            indicators=matched_indicators,
            reason=reason,
            source_id=source_id,
        )
