# core/runtime_state/models.py
"""
Authoritative Runtime State Models for HERMES 2.x.
Provides strongly-typed, immutable/serializable state representations across
all runtime subsystems: mission, task, goal, progress, tool, model,
verification, network, permission, session, evidence, and checkpoint.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any


# ── Enums ────────────────────────────────────────────────────────────────────

class MissionStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WaitReason(str, Enum):
    NONE = "NONE"
    WORKING = "WORKING"
    WAITING_FOR_MODEL = "WAITING_FOR_MODEL"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    WAITING_FOR_VERIFICATION = "WAITING_FOR_VERIFICATION"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    WAITING_FOR_NETWORK = "WAITING_FOR_NETWORK"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolStatus(str, Enum):
    IDLE = "IDLE"
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ModelStatus(str, Enum):
    IDLE = "IDLE"
    QUEUED = "QUEUED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STREAMING = "STREAMING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    CANCELLED = "CANCELLED"


class VerificationStatus(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class NetworkConnectivity(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class PermissionStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    PAUSED = "PAUSED"
    DISCONNECTED = "DISCONNECTED"
    RESUMING = "RESUMING"
    CLOSED = "CLOSED"


class EvidenceKind(str, Enum):
    TOOL_RESULT = "TOOL_RESULT"
    FILESYSTEM = "FILESYSTEM"
    TEST_RESULT = "TEST_RESULT"
    VERIFICATION = "VERIFICATION"
    MODEL_OBSERVATION = "MODEL_OBSERVATION"
    ARTIFACT = "ARTIFACT"
    NETWORK = "NETWORK"
    USER_CONFIRMATION = "USER_CONFIRMATION"


class CheckpointStatus(str, Enum):
    NONE = "NONE"
    CREATING = "CREATING"
    AVAILABLE = "AVAILABLE"
    RESTORING = "RESTORING"
    RESTORED = "RESTORED"
    FAILED = "FAILED"


# ── Child State Definitions ──────────────────────────────────────────────────

@dataclass
class MissionState:
    mission_id: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    status: MissionStatus = MissionStatus.CREATED
    title: str = ""
    prompt: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    current_task_id: Optional[str] = None
    task_count: int = 0
    completed_task_count: int = 0
    failed_task_count: int = 0
    blocked_task_count: int = 0
    cancelled: bool = False
    abort_reason: Optional[str] = None
    completion_reason: Optional[str] = None
    execution_mode: str = "auto"
    workspace_root: str = ""
    last_event_sequence: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.ABORTED,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class TaskState:
    task_id: str
    mission_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    order_index: int = 0
    dependencies: List[str] = field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    attempts: int = 0
    current_iteration: int = 1
    max_iterations: int = 5
    current_model_request_id: Optional[str] = None
    current_tool_call_id: Optional[str] = None
    verification_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    repair_state: str = "NOT_REQUIRED"
    failure_reason: Optional[str] = None
    completion_reason: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class GoalState:
    goal_id: str
    mission_id: str
    description: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    progress: float = 0.0
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    remaining_objectives: List[str] = field(default_factory=list)
    achieved_objectives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ProgressState:
    completed_tasks: int = 0
    total_tasks: int = 0
    active_task_id: Optional[str] = None
    active_task_index: int = 0
    overall_fraction: float = 0.0
    current_stage: int = 0
    current_stage_name: str = ""
    current_action: str = ""
    last_successful_action: Optional[str] = None
    last_state_change_at: float = field(default_factory=time.time)
    elapsed_time: float = 0.0
    waiting_reason: WaitReason = WaitReason.NONE

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["waiting_reason"] = self.waiting_reason.value
        return d


@dataclass
class ToolExecutionState:
    active_tool_call_id: Optional[str] = None
    task_id: Optional[str] = None
    tool_name: Optional[str] = None
    arguments_summary: str = ""
    status: ToolStatus = ToolStatus.IDLE
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    exit_code: Optional[int] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    retry_count: int = 0
    risk_level: str = "NORMAL"
    workspace_target: Optional[str] = None
    recent_tools: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ModelExecutionState:
    active_request_id: Optional[str] = None
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    tier: int = 1
    provider: str = ""
    model: str = ""
    status: ModelStatus = ModelStatus.IDLE
    started_at: Optional[float] = None
    first_byte_at: Optional[float] = None
    first_token_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    tokens_generated: Optional[int] = None
    retry_count: int = 0
    attempt_number: int = 1
    stream_status: str = "IDLE"
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    waiting_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class VerificationState:
    verification_id: Optional[str] = None
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    status: VerificationStatus = VerificationStatus.IDLE
    method: str = "DETERMINISTIC"
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    risk_score: Optional[float] = None
    issues: List[str] = field(default_factory=list)
    evidence_references: List[str] = field(default_factory=list)
    classification: str = "LEVEL_0"
    repair_required: bool = False
    attempt: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class NetworkState:
    connectivity: NetworkConnectivity = NetworkConnectivity.UNKNOWN
    provider: str = ""
    endpoint: str = ""
    request_id: Optional[str] = None
    connected_at: Optional[float] = None
    disconnected_at: Optional[float] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    reconnecting: bool = False
    latency_ms: Optional[float] = None
    health_status: str = "HEALTHY"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["connectivity"] = self.connectivity.value
        return d


@dataclass
class PermissionState:
    permission_request_id: Optional[str] = None
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    action: str = ""
    risk: str = "NORMAL"
    status: PermissionStatus = PermissionStatus.NONE
    requested_at: Optional[float] = None
    resolved_at: Optional[float] = None
    decision: Optional[str] = None
    resolution_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class SessionState:
    session_id: str
    mission_id: Optional[str] = None
    status: SessionStatus = SessionStatus.CREATED
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    current_workspace: str = ""
    branch: Optional[str] = None
    active_model: str = ""
    ui_connected: bool = True
    generation_version: int = 1
    resumable: bool = True
    last_checkpoint_id: Optional[str] = None
    last_event_sequence: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class EvidenceState:
    evidence_id: str
    mission_id: str
    task_id: Optional[str] = None
    source: str = "tool"
    kind: EvidenceKind = EvidenceKind.TOOL_RESULT
    status: str = "VALID"
    timestamp: float = field(default_factory=time.time)
    artifact_path: Optional[str] = None
    verification_reference: Optional[str] = None
    digest: Optional[str] = None
    confidence: Optional[float] = None
    valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class CheckpointState:
    checkpoint_id: Optional[str] = None
    mission_id: Optional[str] = None
    sequence: int = 0
    created_at: Optional[float] = None
    reason: Optional[str] = None
    status: CheckpointStatus = CheckpointStatus.NONE
    resumable: bool = False
    state_version: int = 0
    event_sequence: int = 0
    workspace_snapshot_ref: Optional[str] = None
    session_snapshot_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ── Canonical Root State Tree ────────────────────────────────────────────────

@dataclass
class HermesRuntimeState:
    """
    Authoritative root runtime state for HERMES 2.x.
    All UI, telemetry, and logging views are derived projections of this tree.
    """
    mission: MissionState
    goal: GoalState = field(default_factory=lambda: GoalState(goal_id="", mission_id=""))
    progress: ProgressState = field(default_factory=ProgressState)
    current_task: Optional[TaskState] = None
    tasks: Dict[str, TaskState] = field(default_factory=dict)
    tool_execution: ToolExecutionState = field(default_factory=ToolExecutionState)
    model_execution: ModelExecutionState = field(default_factory=ModelExecutionState)
    verification: VerificationState = field(default_factory=VerificationState)
    network: NetworkState = field(default_factory=NetworkState)
    permission: PermissionState = field(default_factory=PermissionState)
    session: SessionState = field(default_factory=lambda: SessionState(session_id=""))
    evidence: Dict[str, EvidenceState] = field(default_factory=dict)
    checkpoint: CheckpointState = field(default_factory=CheckpointState)
    state_version: int = 0
    last_event_sequence: int = 0
    last_updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create_empty(cls, mission_id: str, session_id: Optional[str] = None) -> HermesRuntimeState:
        s_id = session_id or f"sess_{mission_id}"
        m_state = MissionState(mission_id=mission_id, session_id=s_id)
        g_state = GoalState(goal_id=f"goal_{mission_id}", mission_id=mission_id)
        sess_state = SessionState(session_id=s_id, mission_id=mission_id)
        return cls(
            mission=m_state,
            goal=g_state,
            session=sess_state,
            state_version=0,
            last_event_sequence=0,
            last_updated_at=time.time(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission": self.mission.to_dict(),
            "goal": self.goal.to_dict(),
            "progress": self.progress.to_dict(),
            "current_task": self.current_task.to_dict() if self.current_task else None,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "tool_execution": self.tool_execution.to_dict(),
            "model_execution": self.model_execution.to_dict(),
            "verification": self.verification.to_dict(),
            "network": self.network.to_dict(),
            "permission": self.permission.to_dict(),
            "session": self.session.to_dict(),
            "evidence": {k: v.to_dict() for k, v in self.evidence.items()},
            "checkpoint": self.checkpoint.to_dict(),
            "state_version": self.state_version,
            "last_event_sequence": self.last_event_sequence,
            "last_updated_at": self.last_updated_at,
            "metadata": self.metadata,
        }
