# core/recovery/__init__.py
"""
HERMES 2.x Recovery & Rewind Subsystem.
Deterministic crash recovery, safe file rewinds, user change protection,
and domain drift reconciliation.
"""

from core.recovery.conflicts import ConflictDetector, RestorePlan, RestoreAction, RestoreActionType
from core.recovery.rewind import RewindEngine
from core.recovery.reconcile import DomainReconciler
from core.recovery.gate import RecoveryGate, RecoveryVerdict
from core.recovery.engine import RecoveryEngine

__all__ = [
    "ConflictDetector",
    "RestorePlan",
    "RestoreAction",
    "RestoreActionType",
    "RewindEngine",
    "DomainReconciler",
    "RecoveryGate",
    "RecoveryVerdict",
    "RecoveryEngine",
]
