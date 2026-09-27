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
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    AT_RISK = "AT_RISK"
    ACHIEVED = "ACHIEVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class RequirementCategory(str, Enum):
    FUNCTIONAL = "functional"
    QUALITY = "quality"
    SECURITY = "security"
    PERFORMANCE = "performance"
    INTEGRATION = "integration"
    UI = "ui"
    DOCUMENTATION = "documentation"
    VERIFICATION = "verification"


class RequirementPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RequirementStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    PASSING = "PASSING"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class AcceptanceCheckStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class TodoStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class ExecutionMode(str, Enum):
    PLAN_MODE = "PLAN_MODE"
    EXECUTION_MODE = "EXECUTION_MODE"


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
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"



class NetworkConnectivity(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STREAMING = "STREAMING"
    STALLING = "STALLING"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    RECOVERED = "RECOVERED"
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
    title: str = ""
    description: str = ""
    user_request: str = ""
    explicit_constraints: List[str] = field(default_factory=list)
    explicit_preferences: List[str] = field(default_factory=list)
    clarifications: List[str] = field(default_factory=list)
    success_condition: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    progress: float = 0.0
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    goal_version: int = 1
    blocked_reason: Optional[str] = None
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

    # Prompt 9 extensions: Semantic progress & focus
    last_meaningful_change: str = ""
    current_focus: Optional[str] = None
    next_action: str = ""
    known_failures: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    recent_evidence: List[str] = field(default_factory=list)
    overall_status: str = "IDLE"
    verified_requirements_count: int = 0
    total_requirements_count: int = 0
    passing_checks_count: int = 0
    total_checks_count: int = 0
    progress_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["waiting_reason"] = self.waiting_reason.value
        return d


@dataclass
class AcceptanceCheck:
    """A concrete observable acceptance check belonging to a requirement."""
    check_id: str
    requirement_id: str
    description: str
    status: AcceptanceCheckStatus = AcceptanceCheckStatus.NOT_RUN
    critical: bool = True
    evidence_refs: List[str] = field(default_factory=list)
    verification_method: str = "test"  # "test", "command", "file_exists", "ast_check", "manual"
    last_run_at: Optional[float] = None
    error_message: Optional[str] = None
    source_file_versions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class AcceptanceLedger:
    """Authoritative completion contract recording concrete verification proofs."""
    goal_id: str = ""
    version: int = 1
    checks: Dict[str, AcceptanceCheck] = field(default_factory=dict)
    requirement_checks: Dict[str, List[str]] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def add_check(self, check: AcceptanceCheck) -> None:
        self.checks[check.check_id] = check
        if check.requirement_id not in self.requirement_checks:
            self.requirement_checks[check.requirement_id] = []
        if check.check_id not in self.requirement_checks[check.requirement_id]:
            self.requirement_checks[check.requirement_id].append(check.check_id)
        self.updated_at = time.time()

    def record_result(
        self,
        check_id: str,
        status: AcceptanceCheckStatus,
        evidence_ref: Optional[str] = None,
        error: Optional[str] = None,
        source_versions: Optional[Dict[str, str]] = None,
    ) -> bool:
        check = self.checks.get(check_id)
        if not check:
            return False
        check.status = status
        check.last_run_at = time.time()
        if evidence_ref and evidence_ref not in check.evidence_refs:
            check.evidence_refs.append(evidence_ref)
        if error:
            check.error_message = error
        if source_versions:
            check.source_file_versions.update(source_versions)
        self.updated_at = time.time()
        return True

    def get_checks_for_requirement(self, requirement_id: str) -> List[AcceptanceCheck]:
        check_ids = self.requirement_checks.get(requirement_id, [])
        return [self.checks[cid] for cid in check_ids if cid in self.checks]

    def is_requirement_passing(self, requirement_id: str) -> Tuple[bool, List[str]]:
        """
        Evaluate if requirement passes its acceptance checks.
        Returns: (is_passing: bool, issues: List[str])
        """
        checks = self.get_checks_for_requirement(requirement_id)
        if not checks:
            return False, ["No acceptance checks defined for requirement"]

        issues = []
        has_evidence = False

        for c in checks:
            if c.critical and c.status != AcceptanceCheckStatus.PASS:
                issues.append(f"Critical check '{c.description}' is {c.status.value}")
            elif c.status == AcceptanceCheckStatus.FAIL:
                issues.append(f"Check '{c.description}' failed: {c.error_message or 'Unspecified failure'}")
            elif c.status == AcceptanceCheckStatus.NOT_RUN:
                issues.append(f"Check '{c.description}' has not been executed yet")
            elif c.status == AcceptanceCheckStatus.BLOCKED:
                issues.append(f"Check '{c.description}' is blocked")

            if c.status == AcceptanceCheckStatus.PASS and c.evidence_refs:
                has_evidence = True

        if not has_evidence:
            issues.append("No verified evidence references recorded for passing checks")

        return len(issues) == 0, issues

    def mark_stale_for_files(self, modified_files: Set[str]) -> List[str]:
        """Mark checks stale if their recorded source files were modified."""
        stale_check_ids = []
        for check in self.checks.values():
            if check.status == AcceptanceCheckStatus.PASS:
                overlap = set(check.source_file_versions.keys()).intersection(modified_files)
                if overlap:
                    check.status = AcceptanceCheckStatus.NOT_RUN
                    check.evidence_refs.clear()
                    stale_check_ids.append(check.check_id)
        if stale_check_ids:
            self.updated_at = time.time()
        return stale_check_ids

    def report(self) -> Dict[str, Any]:
        total = len(self.checks)
        passed = sum(1 for c in self.checks.values() if c.status == AcceptanceCheckStatus.PASS)
        failed = sum(1 for c in self.checks.values() if c.status == AcceptanceCheckStatus.FAIL)
        not_run = sum(1 for c in self.checks.values() if c.status == AcceptanceCheckStatus.NOT_RUN)
        blocked = sum(1 for c in self.checks.values() if c.status == AcceptanceCheckStatus.BLOCKED)
        critical_failed = sum(
            1 for c in self.checks.values() if c.critical and c.status in (AcceptanceCheckStatus.FAIL, AcceptanceCheckStatus.BLOCKED)
        )
        return {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "not_run": not_run,
            "blocked": blocked,
            "critical_failed": critical_failed,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "version": self.version,
            "checks": {k: v.to_dict() for k, v in self.checks.items()},
            "requirement_checks": self.requirement_checks,
            "updated_at": self.updated_at,
        }


@dataclass
class RequirementState:
    """A single concrete required outcome for the user's goal."""
    requirement_id: str
    goal_id: str
    title: str
    description: str = ""
    category: RequirementCategory = RequirementCategory.FUNCTIONAL
    priority: RequirementPriority = RequirementPriority.MEDIUM
    status: RequirementStatus = RequirementStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    acceptance_check_ids: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    active: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempt_count: int = 0
    last_failure: Optional[str] = None
    waiver_reason: Optional[str] = None
    waiver_actor: Optional[str] = None
    waiver_timestamp: Optional[float] = None
    version: int = 1
    history: List[Dict[str, Any]] = field(default_factory=list)

    def transition_status(self, new_status: RequirementStatus, reason: str = "", actor: str = "system") -> None:
        if self.status == new_status:
            return
        self.history.append({
            "from_status": self.status.value,
            "to_status": new_status.value,
            "reason": reason,
            "actor": actor,
            "timestamp": time.time(),
        })
        self.status = new_status
        self.updated_at = time.time()
        self.version += 1

    def waive(self, reason: str, actor: str) -> None:
        self.waiver_reason = reason
        self.waiver_actor = actor
        self.waiver_timestamp = time.time()
        self.transition_status(RequirementStatus.WAIVED, reason=f"Waived by {actor}: {reason}", actor=actor)

    def reopen(self, reason: str) -> None:
        self.transition_status(RequirementStatus.FAILED, reason=f"Reopened: {reason}", actor="verifier")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["priority"] = self.priority.value
        d["status"] = self.status.value
        return d


@dataclass
class TodoState:
    """A concrete engineering work item supporting one or more requirements."""
    todo_id: str
    goal_id: str
    requirement_ids: List[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    status: TodoStatus = TodoStatus.PENDING
    priority: RequirementPriority = RequirementPriority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    owner: str = "T1"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempt_count: int = 0
    last_failure: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority"] = self.priority.value
        d["status"] = self.status.value
        return d


@dataclass
class PlanStep:
    """Proposed step in an execution plan."""
    step_id: str
    title: str
    description: str = ""
    requirement_ids: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    verification_strategy: str = ""
    status: str = "PROPOSED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlanState:
    """Proposed strategy decomposing the mission goal into ordered steps."""
    plan_id: str
    goal_id: str
    version: int = 1
    steps: List[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    risks: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    reason_changed: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "version": self.version,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "risks": self.risks,
            "unknowns": self.unknowns,
            "open_questions": self.open_questions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "reason_changed": self.reason_changed,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }


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
    evidence_required: bool = False
    escalation_required: bool = False
    blocked: bool = False
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
    attempt_id: Optional[str] = None
    connected_at: Optional[float] = None
    disconnected_at: Optional[float] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    last_failure_classification: Optional[str] = None
    reconnecting: bool = False
    latency_ms: Optional[float] = None
    health_status: str = "HEALTHY"
    circuit_state: str = "CLOSED"
    streaming_active: bool = False
    ttft_ms: Optional[float] = None
    deltas_received: int = 0

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
    freshness: str = "FRESH"
    trust_class: str = "TOOL_DERIVED_OBSERVATION"
    requirement_id: Optional[str] = None
    acceptance_check_id: Optional[str] = None

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


# ── Prompt 10 Subagents, Worktrees, and Background Execution Models ──────────

class AgentType(str, Enum):
    PRIMARY = "PRIMARY"
    EXPLORER = "EXPLORER"
    REVIEWER = "REVIEWER"
    TESTER = "TESTER"
    IMPLEMENTER = "IMPLEMENTER"
    ANALYST = "ANALYST"
    CUSTOM = "CUSTOM"


class SubagentStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETING = "COMPLETING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
    ORPHANED = "ORPHANED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            SubagentStatus.SUCCEEDED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLED,
            SubagentStatus.TIMED_OUT,
            SubagentStatus.RESOURCE_EXCEEDED,
            SubagentStatus.ORPHANED,
        )


class JobKind(str, Enum):
    SUBAGENT = "SUBAGENT"
    SHELL = "SHELL"
    SERVER = "SERVER"
    TEST = "TEST"
    BUILD = "BUILD"
    CUSTOM = "CUSTOM"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
    ORPHANED = "ORPHANED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMED_OUT,
            JobStatus.RESOURCE_EXCEEDED,
            JobStatus.ORPHANED,
        )


class JobLifecycle(str, Enum):
    CHILD_BOUND = "CHILD_BOUND"
    DETACHED = "DETACHED"


class WorktreeStatus(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    IN_USE = "IN_USE"
    HANDOFF = "HANDOFF"
    INTEGRATED = "INTEGRATED"
    CONFLICT = "CONFLICT"
    ORPHANED = "ORPHANED"
    CLEANED = "CLEANED"


class WorktreeMode(str, Enum):
    NO_WORKTREE = "NO_WORKTREE"
    READ_ONLY_SHARED_WORKSPACE = "READ_ONLY_SHARED_WORKSPACE"
    ISOLATED_WORKTREE = "ISOLATED_WORKTREE"


class WorktreeIntegrationPolicy(str, Enum):
    PATCH_ONLY = "PATCH_ONLY"
    FAST_FORWARD = "FAST_FORWARD"
    MERGE_COMMIT = "MERGE_COMMIT"
    MANUAL = "MANUAL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass
class SubagentToolPolicy:
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    read_only: bool = True
    can_mutate: bool = False
    can_shell: bool = False
    can_network: bool = False
    can_delegate: bool = False

    def is_tool_allowed(self, tool_name: str) -> Tuple[bool, str]:
        canonical = tool_name.strip().lower()
        if canonical in [t.lower() for t in self.denied_tools]:
            return False, f"Tool '{tool_name}' is explicitly denied by subagent policy."
        if not self.can_delegate and canonical in ("task.delegate", "delegate"):
            return False, "Subagent is prohibited from recursive delegation (can_delegate=False)."
        if self.read_only and canonical in ("fs.write", "fs.edit", "write_file", "edit_file"):
            return False, f"Mutating tool '{tool_name}' prohibited by read-only subagent policy."
        if not self.can_shell and canonical in ("shell.bash", "bash"):
            return False, "Shell command execution prohibited by subagent policy."
        if self.allowed_tools and not any(canonical == a.lower() or canonical.startswith(a.lower() + ".") for a in self.allowed_tools):
            return False, f"Tool '{tool_name}' is not in allowed tools list {self.allowed_tools}."
        return True, "Allowed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubagentBudget:
    max_input_tokens: int = 50_000
    max_output_tokens: int = 4_096
    max_total_tokens: int = 60_000
    max_turns: int = 15
    max_tool_calls: int = 30
    max_runtime_seconds: float = 120.0
    max_output_bytes: int = 100_000
    max_children: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResourceUsage:
    turns: int = 0
    tool_calls: int = 0
    wall_time_ms: float = 0.0
    output_bytes: int = 0
    context_peak_estimate: int = 0
    worktree_disk_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubagentResult:
    status: SubagentStatus
    task_id: str
    agent_id: str
    summary: str
    findings: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    changes: List[Dict[str, Any]] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    tests: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    next_recommendation: Optional[str] = None
    duration: float = 0.0
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    partial: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class SubagentHandoff:
    task_id: str
    agent_id: str
    goal: str
    requirements: List[str] = field(default_factory=list)
    scope_paths: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    budget: SubagentBudget = field(default_factory=SubagentBudget)
    workspace_path: str = ""
    worktree_id: Optional[str] = None
    relevant_context_refs: List[str] = field(default_factory=list)
    expected_output: str = ""
    deadline: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["budget"] = self.budget.to_dict()
        return d


@dataclass
class AgentRecord:
    agent_id: str
    agent_type: AgentType
    mission_id: str
    parent_agent_id: Optional[str] = None
    task_id: Optional[str] = None
    context_id: str = ""
    worktree_id: Optional[str] = None
    execution_mode: str = "EXECUTION_MODE"
    status: SubagentStatus = SubagentStatus.CREATED
    budget: SubagentBudget = field(default_factory=SubagentBudget)
    tool_policy: SubagentToolPolicy = field(default_factory=SubagentToolPolicy)
    resource_usage: AgentResourceUsage = field(default_factory=AgentResourceUsage)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "mission_id": self.mission_id,
            "parent_agent_id": self.parent_agent_id,
            "task_id": self.task_id,
            "context_id": self.context_id,
            "worktree_id": self.worktree_id,
            "execution_mode": self.execution_mode,
            "status": self.status.value,
            "budget": self.budget.to_dict(),
            "tool_policy": self.tool_policy.to_dict(),
            "resource_usage": self.resource_usage.to_dict(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


@dataclass
class SubagentTaskRecord:
    task_id: str
    parent_task_id: Optional[str] = None
    mission_id: str = ""
    goal_id: Optional[str] = None
    requirement_ids: List[str] = field(default_factory=list)
    todo_ids: List[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    mode: str = "auto"
    status: SubagentStatus = SubagentStatus.CREATED
    agent_id: Optional[str] = None
    owner_agent_id: str = ""
    parent_agent_id: Optional[str] = None
    depth: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class WorktreeRecord:
    worktree_id: str
    path: str
    branch: str
    base_commit: str
    agent_id: str
    task_id: str
    status: WorktreeStatus = WorktreeStatus.CREATED
    created_at: float = field(default_factory=time.time)
    deleted_at: Optional[float] = None
    dirty: bool = False
    sparse_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class BackgroundJobRecord:
    job_id: str
    owner_agent_id: str
    task_id: str
    kind: JobKind = JobKind.SUBAGENT
    status: JobStatus = JobStatus.QUEUED
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    pid: Optional[int] = None
    process_group: Optional[int] = None
    worktree_id: Optional[str] = None
    artifact_ref: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    command: Optional[str] = None
    cwd: str = ""
    lifecycle: JobLifecycle = JobLifecycle.CHILD_BOUND

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
# ── Prompt 11 Evidence, Verification, Repair, and Escalation Models ──────────

class EvidenceFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"
    UNKNOWN = "UNKNOWN"


class EvidenceTrustClass(str, Enum):
    DIRECT_ENVIRONMENT_OBSERVATION = "DIRECT_ENVIRONMENT_OBSERVATION"
    TOOL_DERIVED_OBSERVATION = "TOOL_DERIVED_OBSERVATION"
    DERIVED_ASSERTION = "DERIVED_ASSERTION"
    SUBAGENT_REPORTED = "SUBAGENT_REPORTED"
    MODEL_CLAIM = "MODEL_CLAIM"
    USER_ASSERTION = "USER_ASSERTION"


class FailureClass(str, Enum):
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    BUILD_FAILURE = "BUILD_FAILURE"
    MISSING_ARTIFACT = "MISSING_ARTIFACT"
    WRONG_ARTIFACT = "WRONG_ARTIFACT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PATH_ERROR = "PATH_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    REQUIREMENT_AMBIGUITY = "REQUIREMENT_AMBIGUITY"
    SECURITY_RISK = "SECURITY_RISK"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    ASSERTION_FAILED = "ASSERTION_FAILED"
    FILE_CORRUPTED = "FILE_CORRUPTED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    TEST_FAILED = "TEST_FAILED"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    PERMISSION_VIOLATION = "PERMISSION_VIOLATION"
    TIMEOUT = "TIMEOUT"
    OTHER = "OTHER"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RepairStatus(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    REPAIRING = "REPAIRING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"
    STALLED = "STALLED"


class EscalationDecisionType(str, Enum):
    NO_ESCALATION = "NO_ESCALATION"
    T1_REPAIR = "T1_REPAIR"
    T2_REQUIRED = "T2_REQUIRED"
    T3_REQUIRED = "T3_REQUIRED"
    USER_REQUIRED = "USER_REQUIRED"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE_TO_USER = "ESCALATE_TO_USER"
    WAIVE_OPTIONAL_REQUIREMENT = "WAIVE_OPTIONAL_REQUIREMENT"


class DisagreementClass(str, Enum):
    NO_DISAGREEMENT = "NO_DISAGREEMENT"
    WEAK_DISAGREEMENT = "WEAK_DISAGREEMENT"
    EVIDENCE_DISAGREEMENT = "EVIDENCE_DISAGREEMENT"
    INTERPRETATION_DISAGREEMENT = "INTERPRETATION_DISAGREEMENT"
    EVIDENCE_INTERPRETATION = "EVIDENCE_INTERPRETATION"
    HIGH_RISK_DISAGREEMENT = "HIGH_RISK_DISAGREEMENT"
    PERSISTENT_DISAGREEMENT = "PERSISTENT_DISAGREEMENT"


@dataclass
class RepairState:
    repair_id: str
    mission_id: str
    requirement_id: Optional[str] = None
    check_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3
    status: RepairStatus = RepairStatus.IDLE
    failure_class: FailureClass = FailureClass.UNKNOWN_FAILURE
    failure_reason: str = ""
    repair_action: Optional[str] = None
    fingerprints: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["failure_class"] = self.failure_class.value
        return d


@dataclass
class EscalationState:
    escalation_id: str
    mission_id: str
    requirement_id: Optional[str] = None
    check_id: Optional[str] = None
    decision: EscalationDecisionType = EscalationDecisionType.NO_ESCALATION
    level: str = "LEVEL_0"
    t2_verdict: Optional[str] = None
    t3_decision: Optional[str] = None
    disagreement_class: DisagreementClass = DisagreementClass.NO_DISAGREEMENT
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        d["disagreement_class"] = self.disagreement_class.value
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

    # Prompt 9 extensions: Authoritative Goal, Requirement, Acceptance, Todo, and Plan state
    requirements: Dict[str, RequirementState] = field(default_factory=dict)
    acceptance_ledger: AcceptanceLedger = field(default_factory=AcceptanceLedger)
    todos: Dict[str, TodoState] = field(default_factory=dict)
    plan: Optional[PlanState] = None
    execution_mode: ExecutionMode = ExecutionMode.EXECUTION_MODE

    # Prompt 10 extensions: Subagents, Delegated Tasks, Worktrees, and Background Jobs
    agents: Dict[str, AgentRecord] = field(default_factory=dict)
    subagent_tasks: Dict[str, SubagentTaskRecord] = field(default_factory=dict)
    worktrees: Dict[str, WorktreeRecord] = field(default_factory=dict)
    background_jobs: Dict[str, BackgroundJobRecord] = field(default_factory=dict)

    # Prompt 11 extensions: T1 Self-Repair and Selective Escalations
    repairs: Dict[str, RepairState] = field(default_factory=dict)
    escalations: Dict[str, EscalationState] = field(default_factory=dict)

    state_version: int = 0
    last_event_sequence: int = 0
    last_updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create_empty(cls, mission_id: str, session_id: Optional[str] = None) -> HermesRuntimeState:
        s_id = session_id or f"sess_{mission_id}"
        m_state = MissionState(mission_id=mission_id, session_id=s_id)
        g_state = GoalState(goal_id=f"goal_{mission_id}", mission_id=mission_id)
        ledger = AcceptanceLedger(goal_id=f"goal_{mission_id}")
        sess_state = SessionState(session_id=s_id, mission_id=mission_id)
        return cls(
            mission=m_state,
            goal=g_state,
            acceptance_ledger=ledger,
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
            "requirements": {k: v.to_dict() for k, v in self.requirements.items()},
            "acceptance_ledger": self.acceptance_ledger.to_dict(),
            "todos": {k: v.to_dict() for k, v in self.todos.items()},
            "plan": self.plan.to_dict() if self.plan else None,
            "execution_mode": self.execution_mode.value,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "subagent_tasks": {k: v.to_dict() for k, v in self.subagent_tasks.items()},
            "worktrees": {k: v.to_dict() for k, v in self.worktrees.items()},
            "background_jobs": {k: v.to_dict() for k, v in self.background_jobs.items()},
            "repairs": {k: v.to_dict() for k, v in self.repairs.items()},
            "escalations": {k: v.to_dict() for k, v in self.escalations.items()},
            "state_version": self.state_version,
            "last_event_sequence": self.last_event_sequence,
            "last_updated_at": self.last_updated_at,
            "metadata": self.metadata,
        }
