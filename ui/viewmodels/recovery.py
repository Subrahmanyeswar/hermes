# ui/viewmodels/recovery.py
"""Recovery and Rewind Preview ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class RewindPreviewViewModel:
    checkpoint_id: str = ""
    reason: str = ""
    created_at_str: str = ""
    files_changed_count: int = 0
    additions_count: int = 0
    deletions_count: int = 0
    user_conflicts_count: int = 0
    conflicts_details: Tuple[str, ...] = ()
    restore_files_count: int = 0
    preserve_files_count: int = 0
    can_proceed: bool = True
    visible: bool = False


@dataclass(frozen=True)
class RecoveryViewModel:
    status: str = "IDLE"   # IDLE, RESTORING, RECONCILING, VALIDATING, COMPLETED, FAILED
    phase_summary: str = ""
    is_recovering: bool = False
    warnings: Tuple[str, ...] = ()
    error_message: Optional[str] = None
