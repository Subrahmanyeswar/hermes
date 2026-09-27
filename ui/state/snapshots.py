# ui/state/snapshots.py
"""
Immutable Point-In-Time Runtime State Snapshots.

Ensures the UI selector pipeline operates on a coherent, non-mutating view of runtime state.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.runtime_state.models import HermesRuntimeState


@dataclass(frozen=True)
class RuntimeStateSnapshot:
    """An immutable, detached snapshot of HermesRuntimeState."""
    state_version: int
    last_event_sequence: int
    timestamp: float
    data: Dict[str, Any]

    @classmethod
    def from_state(cls, state: HermesRuntimeState) -> RuntimeStateSnapshot:
        """Capture deepcopy dictionary snapshot of current runtime state."""
        return cls(
            state_version=state.state_version,
            last_event_sequence=state.last_event_sequence,
            timestamp=time.time(),
            data=copy.deepcopy(state.to_dict()),
        )
