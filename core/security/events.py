# core/security/events.py
"""
HERMES 2.x - Security Event Creators (Prompt 13)
Factory functions for emitting canonical security and permission events.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional, List

from core.runtime_state.events import EventSeverity, EventType, HermesEvent


def create_security_risk_assessed_event(
    mission_id: str,
    tool_name: str,
    risk_level: str,
    risk_score: float,
    dimensions: List[str],
    fingerprint: str,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.SECURITY_RISK_ASSESSED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.WARNING if risk_level in ("HIGH", "CRITICAL") else EventSeverity.INFO,
        payload={
            "tool_name": tool_name,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "dimensions": dimensions,
            "action_fingerprint": fingerprint,
        },
    )


def create_permission_evaluated_event(
    mission_id: str,
    tool_name: str,
    outcome: str,
    reason_code: str,
    fingerprint: str,
    reason: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.PERMISSION_EVALUATED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.WARNING if outcome == "DENY" else EventSeverity.INFO,
        payload={
            "tool_name": tool_name,
            "outcome": outcome,
            "reason_code": reason_code,
            "action_fingerprint": fingerprint,
            "reason": reason,
        },
    )


def create_permission_asked_event(
    mission_id: str,
    request_id: str,
    tool_name: str,
    scope: str,
    risk_level: str,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.PERMISSION_ASKED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.WARNING,
        payload={
            "request_id": request_id,
            "tool_name": tool_name,
            "scope": scope,
            "risk_level": risk_level,
        },
    )


def create_permission_granted_event(
    mission_id: str,
    grant_id: str,
    tool_name: str,
    remaining_uses: int,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.PERMISSION_GRANTED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.SUCCESS,
        payload={
            "grant_id": grant_id,
            "tool_name": tool_name,
            "remaining_uses": remaining_uses,
        },
    )


def create_prompt_injection_detected_event(
    mission_id: str,
    source_id: Optional[str],
    family: Optional[str],
    confidence: float,
    indicators: List[str],
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.PROMPT_INJECTION_DETECTED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.CRITICAL if confidence > 0.7 else EventSeverity.WARNING,
        payload={
            "source_id": source_id,
            "family": family,
            "confidence": confidence,
            "indicators": indicators,
        },
    )


def create_content_sanitized_event(
    mission_id: str,
    source_id: Optional[str],
    indicators_count: int,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.CONTENT_SANITIZED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.INFO,
        payload={
            "source_id": source_id,
            "indicators_count": indicators_count,
        },
    )


def create_subagent_ceiling_enforced_event(
    mission_id: str,
    tool_name: str,
    agent_id: str,
    reason: Optional[str],
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.SUBAGENT_PERMISSION_CEILING_ENFORCED,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.WARNING,
        payload={
            "tool_name": tool_name,
            "agent_id": agent_id,
            "reason": reason,
        },
    )


def create_handoff_security_violation_event(
    mission_id: str,
    subagent_id: str,
    violations: List[str],
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.HANDOFF_SECURITY_VIOLATION,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.ERROR,
        payload={
            "subagent_id": subagent_id,
            "violations": violations,
        },
    )


def create_security_escalation_event(
    mission_id: str,
    reason: str,
    consecutive_denials: int,
    last_action: str,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> HermesEvent:
    return HermesEvent(
        event_type=EventType.SECURITY_ESCALATION,
        mission_id=mission_id,
        task_id=task_id,
        session_id=session_id,
        severity=EventSeverity.CRITICAL,
        payload={
            "reason": reason,
            "consecutive_denials": consecutive_denials,
            "last_action": last_action,
        },
    )
