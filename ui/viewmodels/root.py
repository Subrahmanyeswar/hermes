# ui/viewmodels/root.py
"""
Authoritative Root ViewModel for HERMES 2.x TUI.

STRICT INVARIANTS:
1. Frozen / Immutable dataclass.
2. Complete absence of live backend objects, file handles, DB connections, or sockets.
3. Explicit metadata for causal tracking (sequence, revision, state_version, session_id).
4. No hidden chain-of-thought or sensitive secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from ui.viewmodels.mission import MissionViewModel, ProgressViewModel
from ui.viewmodels.chat import ChatViewModel
from ui.viewmodels.tasks import TaskQueueViewModel
from ui.viewmodels.tools import ToolTraceViewModel
from ui.viewmodels.verification import VerificationViewModel
from ui.viewmodels.security import SecurityViewModel, ApprovalModalViewModel
from ui.viewmodels.session import SessionViewModel
from ui.viewmodels.checkpoint import CheckpointSelectorViewModel
from ui.viewmodels.recovery import RecoveryViewModel, RewindPreviewViewModel
from ui.viewmodels.network import NetworkViewModel
from ui.viewmodels.jobs import JobViewModel
from ui.viewmodels.memory import MemoryViewModel


@dataclass(frozen=True)
class HermesViewModel:
    """Canonical root viewmodel representing a single frame's display state."""
    sequence: int = 0
    revision: int = 0
    state_version: int = 0
    mission_id: str = "N/A"
    session_id: str = "N/A"

    mission: MissionViewModel = field(default_factory=MissionViewModel)
    progress: ProgressViewModel = field(default_factory=ProgressViewModel)
    chat: ChatViewModel = field(default_factory=ChatViewModel)
    tasks: TaskQueueViewModel = field(default_factory=TaskQueueViewModel)
    tools: ToolTraceViewModel = field(default_factory=ToolTraceViewModel)
    verification: VerificationViewModel = field(default_factory=VerificationViewModel)
    security: SecurityViewModel = field(default_factory=SecurityViewModel)
    session: SessionViewModel = field(default_factory=SessionViewModel)
    checkpoint: CheckpointSelectorViewModel = field(default_factory=CheckpointSelectorViewModel)
    recovery: RecoveryViewModel = field(default_factory=RecoveryViewModel)
    rewind_preview: RewindPreviewViewModel = field(default_factory=RewindPreviewViewModel)
    network: NetworkViewModel = field(default_factory=NetworkViewModel)
    jobs: JobViewModel = field(default_factory=JobViewModel)
    memory: MemoryViewModel = field(default_factory=MemoryViewModel)

    active_notifications: Tuple[str, ...] = ()
    input_prompt_placeholder: str = "Enter mission instruction or /command..."
    active_tab: str = "chat"     # "chat", "tools", "tasks", "verification", "session"
    is_fallback_active: bool = False
