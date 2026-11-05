# core/runtime_state/reducer.py
"""
Deterministic State Reducer for HERMES 2.x.
Pure, side-effect free state transition engine:
    current_state + event = next_state

Enforces:
- Mathematical pureness: zero I/O, no network, no models, no widgets.
- Terminal state protection: once a mission or task reaches a terminal state,
  late out-of-order events cannot resurrect or regress it.
- Monotonic state versioning and causal sequence tracking.
"""

from __future__ import annotations

import copy
import time
from typing import Dict, Any, Optional

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    is_legal_mission_transition,
    TaskStatus,
    GoalStatus,
    WaitReason,
    ToolStatus,
    ModelStatus,
    VerificationStatus,
    NetworkConnectivity,
    PermissionStatus,
    SessionStatus,
    EvidenceKind,
    EvidenceState,
    CheckpointStatus,
    TaskState,
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    ExecutionMode,
    PlanState,
    PlanStatus,
    PlanStep,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
    TodoState,
    TodoStatus,
    AgentType,
    SubagentStatus,
    JobKind,
    JobStatus,
    JobLifecycle,
    WorktreeStatus,
    WorktreeMode,
    WorktreeIntegrationPolicy,
    SubagentToolPolicy,
    SubagentBudget,
    AgentResourceUsage,
    SubagentResult,
    SubagentHandoff,
    AgentRecord,
    SubagentTaskRecord,
    WorktreeRecord,
    BackgroundJobRecord,
    RepairState,
    EscalationState,
    RepairStatus,
    EscalationDecisionType,
    DisagreementClass,
    EvidenceFreshness,
    EvidenceTrustClass,
    FailureClass,
)
from core.runtime_state.events import HermesEvent, EventType


class StateReducer:
    """
    Pure, side-effect free state reducer.
    Guarantees deterministic, idempotent replayability.
    """

    @classmethod
    def reduce(cls, state: HermesRuntimeState, event: HermesEvent) -> HermesRuntimeState:
        """
        Apply event to state and return updated state.
        Must be pure: no mutations of outside variables, no network, no I/O.
        """
        # Identity checks: drop cross-mission or stale run/attempt events
        if event.mission_id and state.mission.mission_id and event.mission_id != state.mission.mission_id:
            return state

        if (
            isinstance(event.attempt_number, int)
            and isinstance(state.mission.attempt_number, int)
            and event.attempt_number < state.mission.attempt_number
            and (not event.run_id or not state.mission.run_id or event.run_id != state.mission.run_id)
        ):
            # Stale event from a previous attempt
            return state

        if (
            event.run_id
            and state.mission.run_id
            and event.run_id != state.mission.run_id
            and (event.attempt_number or 0) <= (state.mission.attempt_number or 1)
        ):
            # Stale run event from a previous or mismatched run
            return state

        # Stale event sequence check: reject out-of-order sequence regressing state
        if event.sequence > 0 and event.sequence <= state.last_event_sequence:
            # Stale sequence, record sequence and return state unchanged
            return state

        et = event.event_type
        payload = event.payload or {}

        # Track attempt boundary: detect authorized continuation attempt
        prev_attempt = state.mission.attempt_number or 1
        is_new_attempt = bool(
            event.attempt_number
            and event.attempt_number > prev_attempt
            and et in (EventType.MISSION_RESUMED, EventType.MISSION_STARTED)
        )

        # Propagate run identity if event carries it and state doesn't have it set yet
        if event.run_id and not state.mission.run_id:
            state.mission.run_id = event.run_id
        if event.attempt_number and event.attempt_number > state.mission.attempt_number:
            state.mission.attempt_number = event.attempt_number
            if event.run_id:
                state.mission.run_id = event.run_id

        # Create or update sequence and timestamp
        state.last_event_sequence = max(state.last_event_sequence, event.sequence)
        state.state_version += 1
        state.last_updated_at = event.timestamp or time.time()
        state.progress.last_state_change_at = state.last_updated_at

        # ── 1. Terminal Mission Guard ─────────────────────────────────────────
        # If mission is terminal (COMPLETED, FAILED, CANCELLED, ABORTED),
        # ignore events that would reopen or regress the mission unless it is
        # an authorized continuation attempt with a strictly incremented attempt_number.
        if state.mission.is_terminal and not is_new_attempt:
            # Allow purely informational observation/evidence events, but do not
            # resurrect mission to RUNNING or change task status.
            if et in {EventType.EVIDENCE_CREATED, EventType.STATE_SNAPSHOT}:
                cls._handle_evidence(state, event, payload)
            return state

        # Helper to validate and apply mission transitions
        def _apply_mission_status(target_status: MissionStatus) -> bool:
            if is_new_attempt:
                state.mission.status = target_status
                return True
            if not is_legal_mission_transition(state.mission.status, target_status):
                state.metadata["last_invalid_transition"] = {
                    "from": state.mission.status.value,
                    "to": target_status.value,
                    "event_type": et.value if hasattr(et, "value") else str(et),
                    "timestamp": state.last_updated_at,
                }
                return False
            state.mission.status = target_status
            return True

        # ── 2. Mission Lifecycle ──────────────────────────────────────────────
        if et == EventType.MISSION_CREATED:
            _apply_mission_status(MissionStatus.CREATED)
            state.mission.prompt = payload.get("prompt", state.mission.prompt)
            state.mission.workspace_root = payload.get("workspace_root", state.mission.workspace_root)
            state.mission.execution_mode = payload.get("execution_mode", state.mission.execution_mode)
            if payload.get("run_id"):
                state.mission.run_id = payload.get("run_id")
            if payload.get("attempt_number"):
                state.mission.attempt_number = int(payload.get("attempt_number"))

        elif et == EventType.PLANNING_STARTED:
            if _apply_mission_status(MissionStatus.PLANNING):
                state.progress.waiting_reason = WaitReason.WORKING
                state.progress.current_action = "Planning mission decomposition"

        elif et == EventType.PLAN_CREATED:
            tasks_list = payload.get("tasks", [])
            state.mission.task_count = len(tasks_list)
            state.progress.total_tasks = len(tasks_list)
            for idx, t_dict in enumerate(tasks_list):
                t_id = t_dict.get("task_id", f"task_{idx+1}")
                if t_id not in state.tasks:
                    state.tasks[t_id] = TaskState(
                        task_id=t_id,
                        mission_id=state.mission.mission_id,
                        title=t_dict.get("title", t_id),
                        description=t_dict.get("description", ""),
                        order_index=idx,
                        dependencies=t_dict.get("dependencies", []),
                        status=TaskStatus.PENDING,
                    )

        elif et == EventType.MISSION_STARTED:
            if _apply_mission_status(MissionStatus.RUNNING):
                state.mission.start_time = event.timestamp
                state.progress.waiting_reason = WaitReason.WORKING
                state.progress.current_action = "Mission execution started"
            if payload.get("run_id"):
                state.mission.run_id = payload.get("run_id")
            if payload.get("attempt_number"):
                state.mission.attempt_number = int(payload.get("attempt_number"))
            if payload.get("workspace_root") or payload.get("workspace_path"):
                state.mission.workspace_root = payload.get("workspace_root") or payload.get("workspace_path")

        elif et == EventType.MISSION_PAUSED:
            _apply_mission_status(MissionStatus.PAUSED)

        elif et == EventType.MISSION_RESUMED:
            _apply_mission_status(MissionStatus.RUNNING)
            if payload.get("run_id") or event.run_id:
                state.mission.run_id = payload.get("run_id") or event.run_id
            if payload.get("attempt_number") or event.attempt_number:
                state.mission.attempt_number = int(payload.get("attempt_number") or event.attempt_number)
            state.progress.waiting_reason = WaitReason.WORKING
            state.progress.current_action = "Mission execution resumed"

        elif et == EventType.MISSION_WAITING:
            if _apply_mission_status(MissionStatus.WAITING):
                wr_str = payload.get("wait_reason", "WAITING_FOR_NETWORK")
                try:
                    wr_enum = WaitReason(wr_str)
                except (ValueError, TypeError):
                    wr_enum = WaitReason.WAITING_FOR_NETWORK
                state.progress.waiting_reason = wr_enum
                state.progress.current_action = f"Waiting: {payload.get('reason', wr_str)}"

        elif et == EventType.MISSION_COMPLETING:
            _apply_mission_status(MissionStatus.COMPLETING)

        elif et == EventType.MISSION_COMPLETED:
            if _apply_mission_status(MissionStatus.COMPLETED):
                state.mission.end_time = event.timestamp
                state.mission.completion_reason = payload.get("completion_reason") or payload.get("reason", "All tasks verified successfully")
                state.progress.waiting_reason = WaitReason.COMPLETED
                state.progress.current_action = "Mission completed"

        elif et == EventType.MISSION_FAILED:
            if _apply_mission_status(MissionStatus.FAILED):
                state.mission.end_time = event.timestamp
                state.mission.abort_reason = payload.get("error", "Execution failure")
                state.progress.waiting_reason = WaitReason.FAILED
                state.progress.current_action = f"Mission failed: {state.mission.abort_reason}"

        elif et == EventType.MISSION_BLOCKED:
            _apply_mission_status(MissionStatus.WAITING)

        elif et in {EventType.MISSION_CANCELLED, EventType.MISSION_ABORTED}:
            target = MissionStatus.CANCELLED if et == EventType.MISSION_CANCELLED else MissionStatus.ABORTED
            if _apply_mission_status(target):
                state.mission.cancelled = True
                state.mission.end_time = event.timestamp
                state.mission.abort_reason = payload.get("reason", "Cancelled by user")
                state.progress.waiting_reason = WaitReason.CANCELLED
                state.current_task = None
                state.tool_execution.status = ToolStatus.CANCELLED
                state.model_execution.status = ModelStatus.CANCELLED
            return state

        # ── 3. Task Lifecycle ─────────────────────────────────────────────────
        tid = event.task_id or payload.get("task_id")
        if tid:
            task = state.tasks.get(tid)
            if not task:
                task = TaskState(
                    task_id=tid,
                    mission_id=state.mission.mission_id,
                    title=payload.get("title", tid),
                    description=payload.get("description", ""),
                    status=TaskStatus.PENDING,
                )
                state.tasks[tid] = task
                state.mission.task_count = len(state.tasks)
                state.progress.total_tasks = len(state.tasks)

            if et == EventType.TASK_CREATED:
                task.title = payload.get("title", task.title)
                task.description = payload.get("description", task.description)

            elif et == EventType.TASK_READY:
                if not task.is_terminal:
                    task.status = TaskStatus.READY

            elif et == EventType.TASK_STARTED:
                # Terminal task protection: completed tasks cannot regress
                if not task.is_terminal:
                    task.status = TaskStatus.RUNNING
                    task.started_at = event.timestamp
                    task.attempts += 1
                    task.current_iteration = payload.get("inner_iteration", task.current_iteration)
                    state.mission.current_task_id = tid
                    state.current_task = task
                    state.progress.active_task_id = tid
                    state.progress.active_task_index = task.order_index
                    state.progress.waiting_reason = WaitReason.WORKING
                    state.progress.current_action = f"Task: {task.title}"

            elif et == EventType.TASK_WAITING:
                if not task.is_terminal:
                    task.status = TaskStatus.WAITING

            elif et == EventType.TASK_VERIFYING:
                if not task.is_terminal:
                    task.status = TaskStatus.VERIFYING
                    state.progress.waiting_reason = WaitReason.WAITING_FOR_VERIFICATION

            elif et == EventType.TASK_REPAIRING:
                if not task.is_terminal:
                    task.status = TaskStatus.REPAIRING
                    task.repair_state = "REPAIRING"
                    state.progress.waiting_reason = WaitReason.REPAIRING

            elif et == EventType.TASK_COMPLETED:
                task.status = TaskStatus.COMPLETED
                task.completed_at = event.timestamp
                v_ev = payload.get("verification_evidence")
                task.completion_reason = v_ev or payload.get("reason", "Task finished")
                if v_ev:
                    setattr(task, "verification_evidence", v_ev)
                if state.mission.current_task_id == tid:
                    state.mission.current_task_id = None
                    state.current_task = None
                cls._recalculate_task_counts(state)

            elif et == EventType.TASK_FAILED:
                task.status = TaskStatus.FAILED
                task.completed_at = event.timestamp
                task.failure_reason = payload.get("error", "Task execution failed")
                if state.mission.current_task_id == tid:
                    state.mission.current_task_id = None
                    state.current_task = None
                cls._recalculate_task_counts(state)

            elif et == EventType.TASK_CANCELLED:
                task.status = TaskStatus.CANCELLED
                if state.mission.current_task_id == tid:
                    state.mission.current_task_id = None
                    state.current_task = None
                cls._recalculate_task_counts(state)

        # ── 4. Tool Execution Lifecycle ───────────────────────────────────────
        if et in {EventType.TOOL_REQUESTED, EventType.TOOL_VALIDATION_STARTED}:
            state.tool_execution.status = ToolStatus.VALIDATING
            state.tool_execution.tool_name = payload.get("tool_name") or payload.get("tool")

        elif et == EventType.TOOL_VALIDATION_FAILED:
            state.tool_execution.status = ToolStatus.FAILED
            state.tool_execution.error = payload.get("error", "Validation failed")

        elif et == EventType.TOOL_STARTED:
            state.tool_execution.status = ToolStatus.RUNNING
            state.tool_execution.active_tool_call_id = event.tool_call_id or payload.get("tool_call_id")
            state.tool_execution.task_id = tid or state.mission.current_task_id
            tname = payload.get("tool_name") or payload.get("tool") or "tool"
            state.tool_execution.tool_name = tname
            state.tool_execution.arguments_summary = payload.get("arguments_summary", "")
            state.tool_execution.started_at = event.timestamp
            state.tool_execution.error = None
            state.progress.waiting_reason = WaitReason.WAITING_FOR_TOOL
            state.progress.current_action = f"Executing tool: {tname}"

        elif et == EventType.TOOL_COMPLETED:
            state.tool_execution.status = ToolStatus.SUCCEEDED
            state.tool_execution.ended_at = event.timestamp
            started = state.tool_execution.started_at or event.timestamp
            state.tool_execution.duration_seconds = payload.get("duration", max(0.0, event.timestamp - started))
            state.tool_execution.exit_code = payload.get("exit_code", 0)
            state.tool_execution.success = True
            state.tool_execution.error = None
            if payload.get("tool_name") or payload.get("tool"):
                state.tool_execution.tool_name = payload.get("tool_name") or payload.get("tool")
            # Push to bounded recent_tools
            t_record = {
                "tool_name": state.tool_execution.tool_name,
                "success": True,
                "exit_code": state.tool_execution.exit_code,
                "duration": state.tool_execution.duration_seconds,
                "timestamp": event.timestamp,
            }
            state.tool_execution.recent_tools.append(t_record)
            if len(state.tool_execution.recent_tools) > 10:
                state.tool_execution.recent_tools.pop(0)
            state.progress.last_successful_action = f"Executed {state.tool_execution.tool_name}"
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.TOOL_FAILED:
            state.tool_execution.status = ToolStatus.FAILED
            state.tool_execution.ended_at = event.timestamp
            started = state.tool_execution.started_at or event.timestamp
            state.tool_execution.duration_seconds = payload.get("duration", max(0.0, event.timestamp - started))
            state.tool_execution.exit_code = payload.get("exit_code", -1)
            state.tool_execution.success = False
            state.tool_execution.error = payload.get("error", "Tool failed")
            t_record = {
                "tool_name": state.tool_execution.tool_name,
                "success": False,
                "exit_code": state.tool_execution.exit_code,
                "error": state.tool_execution.error,
                "duration": state.tool_execution.duration_seconds,
                "timestamp": event.timestamp,
            }
            state.tool_execution.recent_tools.append(t_record)
            if len(state.tool_execution.recent_tools) > 10:
                state.tool_execution.recent_tools.pop(0)

        # ── 5. Model Execution Lifecycle ──────────────────────────────────────
        if et in {EventType.MODEL_REQUESTED, EventType.MODEL_REQUEST_STARTED}:
            state.model_execution.status = ModelStatus.QUEUED
            state.model_execution.active_request_id = event.request_id or payload.get("request_id")
            state.model_execution.mission_id = state.mission.mission_id
            state.model_execution.task_id = tid or state.mission.current_task_id
            state.model_execution.tier = payload.get("tier", 1)
            state.model_execution.model = payload.get("model", "")
            state.model_execution.provider = payload.get("provider", "")
            state.model_execution.started_at = event.timestamp
            state.model_execution.error_message = None
            state.progress.waiting_reason = WaitReason.WAITING_FOR_MODEL
            state.progress.current_action = f"Requesting model {state.model_execution.model}"

        elif et == EventType.MODEL_CONNECTING:
            state.model_execution.status = ModelStatus.CONNECTING
            state.network.connectivity = NetworkConnectivity.CONNECTING
            state.progress.waiting_reason = WaitReason.WAITING_FOR_MODEL

        elif et == EventType.MODEL_CONNECTED:
            state.model_execution.status = ModelStatus.CONNECTED
            state.network.connectivity = NetworkConnectivity.CONNECTED
            state.network.connected_at = event.timestamp

        elif et in {EventType.MODEL_STREAM_STARTED, EventType.MODEL_GENERATING}:
            state.model_execution.status = ModelStatus.STREAMING
            state.model_execution.stream_status = "STREAMING"
            state.progress.waiting_reason = WaitReason.WAITING_FOR_MODEL

        elif et in {EventType.MODEL_TTFT, EventType.MODEL_FIRST_TOKEN}:
            state.model_execution.first_token_at = event.timestamp

        elif et == EventType.MODEL_COMPLETED:
            state.model_execution.status = ModelStatus.COMPLETED
            state.model_execution.completed_at = event.timestamp
            started = state.model_execution.started_at or event.timestamp
            state.model_execution.duration_seconds = payload.get("latency", max(0.0, event.timestamp - started))
            state.model_execution.tokens_generated = payload.get("tokens")
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.MODEL_FAILED:
            state.model_execution.status = ModelStatus.FAILED
            state.model_execution.error_message = payload.get("error", "Model call failed")

        elif et == EventType.MODEL_TIMEOUT:
            state.model_execution.status = ModelStatus.TIMED_OUT
            state.model_execution.error_message = "Model call timed out"

        elif et in {EventType.TIER_SELECTED, EventType.TIER_FAILOVER_STARTED}:
            raw_tier = payload.get("to_tier") or payload.get("tier")
            if raw_tier is not None:
                try:
                    state.model_execution.tier = int(raw_tier)
                except Exception:
                    pass
            if "model" in payload and payload["model"]:
                state.model_execution.model = payload["model"]
            if "provider" in payload and payload["provider"]:
                state.model_execution.provider = payload["provider"]
                state.network.provider = payload["provider"]

        elif et == EventType.MODEL_DISCONNECTED:
            state.model_execution.status = ModelStatus.DISCONNECTED
            state.network.connectivity = NetworkConnectivity.DISCONNECTED
            state.network.disconnected_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK

        elif et == EventType.MODEL_RECONNECTING:
            state.model_execution.status = ModelStatus.RECONNECTING
            state.network.connectivity = NetworkConnectivity.RECONNECTING
            state.network.reconnecting = True
            state.network.retry_count += 1
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK

        # ── 6. Verification Lifecycle ─────────────────────────────────────────
        if et in (EventType.VERIFICATION_STARTED, EventType.AGENT_VERIFICATION_REQUESTED):
            state.verification.status = VerificationStatus.RUNNING
            state.verification.verification_id = event.verification_id or payload.get("verification_id")
            state.verification.task_id = tid or state.mission.current_task_id
            state.verification.method = payload.get("method", "DETERMINISTIC")
            state.verification.started_at = event.timestamp
            state.verification.confidence = payload.get("confidence")  # None is valid!
            state.verification.verdict = None
            state.verification.repair_required = False
            state.progress.waiting_reason = WaitReason.WAITING_FOR_VERIFICATION
            state.progress.current_action = "Running structural verification"

        elif et in (EventType.VERIFICATION_COMPLETED, EventType.VERIFICATION_PASSED):
            state.verification.status = VerificationStatus.PASSED
            state.verification.completed_at = event.timestamp
            state.verification.verdict = payload.get("verdict", "PASSED")
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = False
            state.verification.evidence_required = False
            state.verification.escalation_required = False
            state.verification.blocked = False
            state.progress.waiting_reason = WaitReason.WORKING
            cid = event.acceptance_check_id or payload.get("check_id") or payload.get("acceptance_check_id")
            if cid and cid in state.acceptance_ledger.checks:
                state.acceptance_ledger.checks[cid].status = AcceptanceCheckStatus.PASS
                cls._recalculate_acceptance_counts(state)
            rid = event.requirement_id or payload.get("requirement_id")
            if rid and rid in state.requirements:
                req_checks = [c for c in state.acceptance_ledger.checks.values() if c.requirement_id == rid]
                if req_checks and all(c.status == AcceptanceCheckStatus.PASS for c in req_checks):
                    state.requirements[rid].status = RequirementStatus.VERIFIED
                    cls._recalculate_requirement_counts(state)

        elif et == EventType.VERIFICATION_FAILED:
            state.verification.status = VerificationStatus.FAILED
            state.verification.completed_at = event.timestamp
            state.verification.verdict = payload.get("verdict", "FAILED")
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = True
            state.verification.evidence_required = False
            state.verification.escalation_required = False
            state.verification.blocked = False
            cid = event.acceptance_check_id or payload.get("check_id") or payload.get("acceptance_check_id")
            if cid and cid in state.acceptance_ledger.checks:
                state.acceptance_ledger.checks[cid].status = AcceptanceCheckStatus.FAIL
                cls._recalculate_acceptance_counts(state)
            rid = event.requirement_id or payload.get("requirement_id")
            if rid and rid in state.requirements:
                state.requirements[rid].status = RequirementStatus.FAILED
                cls._recalculate_requirement_counts(state)

        elif et == EventType.VERIFICATION_NEEDS_IMPROVEMENT:
            state.verification.status = VerificationStatus.NEEDS_IMPROVEMENT
            state.verification.completed_at = event.timestamp
            state.verification.verdict = "NEEDS_IMPROVEMENT"
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = True
            state.verification.evidence_required = False
            state.verification.escalation_required = False
            state.verification.blocked = False
            state.progress.waiting_reason = WaitReason.REPAIRING

        elif et == EventType.VERIFICATION_INCONCLUSIVE:
            state.verification.status = VerificationStatus.INCONCLUSIVE
            state.verification.completed_at = event.timestamp
            state.verification.verdict = "INCONCLUSIVE"
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = False
            state.verification.evidence_required = True
            state.verification.escalation_required = False
            state.verification.blocked = False

        elif et == EventType.VERIFICATION_BLOCKED:
            state.verification.status = VerificationStatus.BLOCKED
            state.verification.completed_at = event.timestamp
            state.verification.verdict = "BLOCKED"
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = False
            state.verification.evidence_required = False
            state.verification.escalation_required = True
            state.verification.blocked = True

        elif et == EventType.VERIFICATION_REOPENED:
            cid = event.acceptance_check_id or payload.get("check_id") or payload.get("acceptance_check_id")
            if cid and cid in state.acceptance_ledger.checks:
                state.acceptance_ledger.checks[cid].status = AcceptanceCheckStatus.PENDING
                cls._recalculate_acceptance_counts(state)
            rid = event.requirement_id or payload.get("requirement_id")
            if rid and rid in state.requirements:
                if state.requirements[rid].status == RequirementStatus.VERIFIED:
                    state.requirements[rid].status = RequirementStatus.IN_PROGRESS
                    cls._recalculate_requirement_counts(state)

        # ── 7. Network Lifecycle ──────────────────────────────────────────────
        if et == EventType.NETWORK_REQUEST_CREATED:
            state.network.request_id = payload.get("request_id")
            state.network.provider = payload.get("provider", state.network.provider)
            state.network.deltas_received = 0
            state.network.ttft_ms = None
        elif et == EventType.NETWORK_CONNECTING:
            state.network.connectivity = NetworkConnectivity.CONNECTING
            state.network.attempt_id = payload.get("attempt_id")
            if "provider" in payload:
                state.network.provider = payload["provider"]
        elif et == EventType.NETWORK_CONNECTED:
            state.network.connectivity = NetworkConnectivity.CONNECTED
            state.network.connected_at = event.timestamp
            state.network.reconnecting = False
        elif et == EventType.NETWORK_STREAMING:
            state.network.connectivity = NetworkConnectivity.STREAMING
            state.network.streaming_active = True
        elif et == EventType.REQUEST_FIRST_DELTA:
            state.network.connectivity = NetworkConnectivity.STREAMING
            state.network.streaming_active = True
            ttft = payload.get("ttft_seconds")
            if ttft is not None:
                state.network.ttft_ms = round(ttft * 1000.0, 2)
        elif et == EventType.REQUEST_PROGRESS:
            state.network.deltas_received += payload.get("deltas_count", 1)
        elif et == EventType.NETWORK_STALLING:
            state.network.connectivity = NetworkConnectivity.STALLING
            state.network.last_error = payload.get("stall_reason", "Stream stalled")
        elif et == EventType.NETWORK_DEGRADED:
            state.network.connectivity = NetworkConnectivity.DEGRADED
        elif et == EventType.NETWORK_DISCONNECTED:
            state.network.connectivity = NetworkConnectivity.DISCONNECTED
            state.network.disconnected_at = event.timestamp
            state.network.last_error = payload.get("error", payload.get("stall_reason", "Disconnected"))
            state.network.streaming_active = False
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK
        elif et == EventType.NETWORK_RECONNECTING:
            state.network.connectivity = NetworkConnectivity.RECONNECTING
            state.network.reconnecting = True
            state.network.retry_count += 1
            state.network.streaming_active = False
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK
        elif et in (EventType.NETWORK_RECOVERED, EventType.NETWORK_RESTORED):
            state.network.connectivity = NetworkConnectivity.RECOVERED if et == EventType.NETWORK_RECOVERED else NetworkConnectivity.CONNECTED
            state.network.reconnecting = False
            state.network.health_status = "HEALTHY"
            state.progress.waiting_reason = WaitReason.WORKING
        elif et == EventType.NETWORK_FAILED:
            state.network.connectivity = NetworkConnectivity.FAILED
            state.network.last_error = payload.get("error")
            state.network.last_failure_classification = payload.get("classification")
            state.network.streaming_active = False
        elif et == EventType.PROVIDER_HEALTH_CHANGED:
            state.network.health_status = payload.get("health_status", state.network.health_status)
            state.network.circuit_state = payload.get("circuit_state", state.network.circuit_state)

        # ── 8. Permission & Security Lifecycle (Prompt 13) ───────────────────
        if et in (EventType.PERMISSION_REQUESTED, EventType.PERMISSION_ASKED):
            state.permission.status = PermissionStatus.REQUESTED
            state.permission.permission_request_id = payload.get("request_id")
            state.permission.action = payload.get("action", payload.get("tool_name", ""))
            state.permission.risk = payload.get("risk", payload.get("risk_level", "NORMAL"))
            state.permission.requested_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WAITING_FOR_PERMISSION

        elif et in (EventType.PERMISSION_APPROVED, EventType.PERMISSION_GRANTED):
            state.permission.status = PermissionStatus.APPROVED
            state.permission.resolved_at = event.timestamp
            state.permission.decision = "APPROVED"
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.PERMISSION_DENIED:
            state.permission.status = PermissionStatus.DENIED
            state.permission.resolved_at = event.timestamp
            state.permission.decision = "DENIED"
            state.permission.resolution_reason = payload.get("reason", "Denied")

        elif et == EventType.SECURITY_RISK_ASSESSED:
            state.permission.action = payload.get("tool_name", state.permission.action)
            state.permission.risk = payload.get("risk_level", state.permission.risk)

        elif et == EventType.PERMISSION_EVALUATED:
            outcome = payload.get("outcome")
            if outcome == "DENY":
                state.permission.status = PermissionStatus.DENIED
                state.permission.decision = "DENIED"
                state.permission.resolution_reason = payload.get("reason", payload.get("reason_code", "Denied"))
            elif outcome == "ALLOW":
                state.permission.status = PermissionStatus.APPROVED
                state.permission.decision = "ALLOWED"

        elif et == EventType.PROMPT_INJECTION_DETECTED:
            state.metadata["last_prompt_injection"] = {
                "source_id": payload.get("source_id"),
                "family": payload.get("family"),
                "confidence": payload.get("confidence"),
                "timestamp": event.timestamp,
            }

        elif et == EventType.SECURITY_ESCALATION:
            state.progress.waiting_reason = WaitReason.FAILED
            state.metadata["security_escalation"] = {
                "reason": payload.get("reason"),
                "consecutive_denials": payload.get("consecutive_denials"),
                "timestamp": event.timestamp,
            }

        # ── 9. Session Lifecycle (Prompt 14) ──────────────────────────────────
        if et in (EventType.SESSION_STARTED, EventType.SESSION_RESUMED, EventType.RECOVERY_COMPLETED):
            state.session.status = SessionStatus.ACTIVE
            if payload.get("session_id"):
                state.session.session_id = payload["session_id"]
            if payload.get("branch_name"):
                state.session.branch = payload["branch_name"]
            state.session.last_activity = event.timestamp
        elif et == EventType.SESSION_PAUSED:
            state.session.status = SessionStatus.PAUSED
        elif et == EventType.SESSION_CLOSED:
            state.session.status = SessionStatus.CLOSED
        elif et in (EventType.SESSION_INTERRUPTED, EventType.RECOVERY_STARTED):
            state.session.status = SessionStatus.INTERRUPTED
        elif et == EventType.SESSION_FORKED:
            state.metadata["forked_session"] = {
                "child_session_id": payload.get("child_session_id"),
                "parent_session_id": payload.get("parent_session_id"),
                "checkpoint_id": payload.get("checkpoint_id"),
                "timestamp": event.timestamp,
            }

        # ── 10. Evidence Lifecycle ────────────────────────────────────────────
        if et == EventType.EVIDENCE_CREATED:
            cls._handle_evidence(state, event, payload)
        elif et == EventType.EVIDENCE_INVALIDATED:
            ev_id = payload.get("evidence_id") or event.evidence_id
            if ev_id and ev_id in state.evidence:
                state.evidence[ev_id].valid = False
                state.evidence[ev_id].freshness = EvidenceFreshness.INVALIDATED.value
            cid = event.acceptance_check_id or payload.get("acceptance_check_id")
            if cid and cid in state.acceptance_ledger.checks:
                chk = state.acceptance_ledger.checks[cid]
                if chk.status == AcceptanceCheckStatus.PASS:
                    chk.status = AcceptanceCheckStatus.PENDING
                    cls._recalculate_acceptance_counts(state)
            rid = event.requirement_id or payload.get("requirement_id")
            if rid and rid in state.requirements:
                req = state.requirements[rid]
                if req.status == RequirementStatus.VERIFIED:
                    req.status = RequirementStatus.IN_PROGRESS
                    cls._recalculate_requirement_counts(state)


        # ── 11. Checkpoint Lifecycle (Prompt 14) ──────────────────────────────
        if et in (EventType.CHECKPOINT_CREATED, EventType.CHECKPOINT_COMMITTED):
            cid = event.checkpoint_id or payload.get("checkpoint_id")
            state.checkpoint.status = CheckpointStatus.AVAILABLE
            state.checkpoint.checkpoint_id = cid
            state.checkpoint.created_at = event.timestamp
            state.checkpoint.resumable = True
            state.session.last_checkpoint_id = cid
        elif et in (EventType.CHECKPOINT_RESTORE_STARTED, EventType.REWIND_STARTED):
            state.checkpoint.status = CheckpointStatus.RESTORING
        elif et in (EventType.CHECKPOINT_RESTORED, EventType.REWIND_COMPLETED):
            cid = event.checkpoint_id or payload.get("checkpoint_id")
            state.checkpoint.status = CheckpointStatus.RESTORED
            state.checkpoint.checkpoint_id = cid
            state.session.last_checkpoint_id = cid

        # ── 12. Agent Loop Lifecycle & Decisions (Prompt 4) ────────────────────
        elif et == EventType.AGENT_TURN_STARTED:
            turn_id = payload.get("turn_id") or event.turn_id
            state.model_execution.turn_id = turn_id
            state.progress.waiting_reason = WaitReason.WAITING_FOR_MODEL
            state.progress.current_action = f"Turn {turn_id or 'start'}: evaluating next action"

        elif et == EventType.AGENT_DECISION:
            decision = payload.get("decision_type", "")
            state.progress.current_action = f"Agent decision: {decision}"

        elif et == EventType.ACTION_REQUESTED:
            state.tool_execution.status = ToolStatus.REQUESTED
            state.tool_execution.tool_name = payload.get("tool_name")
            state.tool_execution.active_tool_call_id = payload.get("action_id") or event.tool_call_id
            state.progress.waiting_reason = WaitReason.WAITING_FOR_PERMISSION
            state.progress.current_action = f"Action requested: {payload.get('tool_name')}"

        elif et == EventType.ACTION_ALLOWED:
            state.tool_execution.status = ToolStatus.VALIDATING
            state.progress.waiting_reason = WaitReason.WAITING_FOR_TOOL

        elif et == EventType.ACTION_DENIED:
            state.tool_execution.status = ToolStatus.FAILED
            state.tool_execution.error = payload.get("reason", "Action denied by harness policy")
            state.progress.waiting_reason = WaitReason.WORKING
            state.progress.current_action = f"Action denied: {payload.get('reason', 'Policy violation')[:50]}"

        elif et == EventType.OBSERVATION_CREATED:
            cls._handle_evidence(state, event, payload)
            obs_summary = payload.get("summary", "")
            if obs_summary:
                state.progress.current_action = f"Observed: {obs_summary[:60]}"

        elif et == EventType.AGENT_WAITING:
            reason_str = payload.get("reason", "WORKING")
            try:
                state.progress.waiting_reason = WaitReason(reason_str)
            except ValueError:
                state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.AGENT_ASK_USER:
            state.progress.waiting_reason = WaitReason.WAITING_FOR_USER
            q = payload.get("question", "")
            state.progress.current_action = f"Waiting for user: {q[:60]}" if q else "Waiting for user input"

        elif et == EventType.AGENT_USER_RESPONSE:
            state.progress.waiting_reason = WaitReason.WORKING
            state.progress.current_action = "Received user input"

        elif et == EventType.AGENT_VERIFICATION_REQUESTED:
            state.progress.waiting_reason = WaitReason.WAITING_FOR_VERIFICATION
            state.verification.status = VerificationStatus.PENDING
            state.progress.current_action = "Running verification"

        elif et == EventType.AGENT_COMPLETION_CANDIDATE:
            state.mission.status = MissionStatus.COMPLETING
            state.progress.waiting_reason = WaitReason.WAITING_FOR_VERIFICATION
            state.progress.current_action = "Evaluating completion evidence"

        elif et == EventType.AGENT_REPAIR_REQUESTED:
            state.progress.waiting_reason = WaitReason.REPAIRING
            reason = payload.get("reason", "")
            state.progress.current_action = f"Repairing: {reason[:60]}" if reason else "Repairing defect"

        elif et == EventType.AGENT_STALL_DETECTED:
            stall_reason = payload.get("reason", "Repeated action pattern detected")
            state.progress.current_action = f"Stall detected: {stall_reason[:60]}"

        elif et == EventType.AGENT_STOPPED:
            state.progress.waiting_reason = WaitReason.NONE
            state.progress.current_action = payload.get("reason", "Agent stopped")

        elif et == EventType.AGENT_FAILED:
            state.progress.waiting_reason = WaitReason.FAILED
            state.progress.current_action = payload.get("error", "Agent failed")

        # ── 13. Goal, Requirement, Todo, Acceptance, Progress & Plan (Prompt 9) ──
        elif et == EventType.GOAL_CREATED:
            g_id = payload.get("goal_id", f"goal_{state.mission.mission_id}")
            state.goal.goal_id = g_id
            state.goal.title = payload.get("title", "")
            state.goal.description = payload.get("description", "")
            state.goal.user_request = payload.get("user_request", state.mission.prompt)
            state.goal.explicit_constraints = payload.get("explicit_constraints", [])
            state.goal.explicit_preferences = payload.get("explicit_preferences", [])
            state.goal.clarifications = payload.get("clarifications", [])
            state.goal.success_condition = payload.get("success_condition", "")
            state.goal.status = GoalStatus.ACTIVE
            state.goal.updated_at = event.timestamp
            state.acceptance_ledger.goal_id = g_id

        elif et == EventType.GOAL_UPDATED:
            for k, v in payload.items():
                if hasattr(state.goal, k):
                    setattr(state.goal, k, v)
            state.goal.updated_at = event.timestamp

        elif et == EventType.GOAL_COMPLETED:
            state.goal.status = GoalStatus.COMPLETED
            state.goal.updated_at = event.timestamp
            state.progress.overall_status = "COMPLETED"

        elif et == EventType.GOAL_BLOCKED:
            state.goal.status = GoalStatus.BLOCKED
            state.goal.blocked_reason = payload.get("reason", "Blocked")
            state.goal.updated_at = event.timestamp

        elif et == EventType.REQUIREMENT_CREATED:
            r_id = payload.get("requirement_id")
            if r_id:
                cat_str = payload.get("category", "functional")
                try:
                    cat = RequirementCategory(cat_str)
                except ValueError:
                    cat = RequirementCategory.FUNCTIONAL
                prio_str = payload.get("priority", "MEDIUM")
                try:
                    prio = RequirementPriority(prio_str)
                except ValueError:
                    prio = RequirementPriority.MEDIUM
                state.requirements[r_id] = RequirementState(
                    requirement_id=r_id,
                    goal_id=payload.get("goal_id", state.goal.goal_id),
                    title=payload.get("title", r_id),
                    description=payload.get("description", ""),
                    category=cat,
                    priority=prio,
                    status=RequirementStatus.PENDING,
                    dependencies=payload.get("dependencies", []),
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                )
                if r_id not in state.tasks:
                    state.tasks[r_id] = TaskState(
                        task_id=r_id,
                        mission_id=state.mission.mission_id,
                        title=payload.get("title", r_id),
                        description=payload.get("description", ""),
                        order_index=len(state.tasks),
                        dependencies=payload.get("dependencies", []),
                        status=TaskStatus.PENDING,
                    )
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_UPDATED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                req = state.requirements[r_id]
                for k, v in payload.items():
                    if k not in ("requirement_id", "status") and hasattr(req, k):
                        setattr(req, k, v)
                req.updated_at = event.timestamp

        elif et == EventType.REQUIREMENT_STARTED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].transition_status(RequirementStatus.IN_PROGRESS, reason=payload.get("reason", ""), actor=event.source)
                if r_id in state.tasks:
                    state.tasks[r_id].status = TaskStatus.IN_PROGRESS
                state.progress.current_focus = r_id
                state.progress.overall_status = "WORKING"
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_BLOCKED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].transition_status(RequirementStatus.BLOCKED, reason=payload.get("reason", ""), actor=event.source)
                if r_id in state.tasks:
                    state.tasks[r_id].status = TaskStatus.BLOCKED
                state.progress.blocked_reason = payload.get("reason", "")
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_COMPLETED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].transition_status(RequirementStatus.VERIFIED, reason=payload.get("reason", ""), actor=event.source)
                if r_id in state.tasks:
                    state.tasks[r_id].status = TaskStatus.COMPLETED
                ev = payload.get("evidence_ref")
                if ev and ev not in state.requirements[r_id].evidence_refs:
                    state.requirements[r_id].evidence_refs.append(ev)
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_REOPENED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].reopen(reason=payload.get("reason", "Regression detected"))
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_WAIVED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].waive(reason=payload.get("reason", ""), actor=payload.get("actor", "user"))
                cls._recalculate_requirement_counts(state)

        elif et == EventType.REQUIREMENT_CANCELLED:
            r_id = payload.get("requirement_id")
            if r_id and r_id in state.requirements:
                state.requirements[r_id].transition_status(RequirementStatus.CANCELLED, reason=payload.get("reason", ""), actor=event.source)
                cls._recalculate_requirement_counts(state)

        elif et == EventType.ACCEPTANCE_CHECK_CREATED:
            c_id = payload.get("check_id")
            r_id = payload.get("requirement_id")
            if c_id and r_id:
                check = AcceptanceCheck(
                    check_id=c_id,
                    requirement_id=r_id,
                    description=payload.get("description", ""),
                    critical=payload.get("critical", True),
                    verification_method=payload.get("verification_method", "test"),
                )
                state.acceptance_ledger.add_check(check)
                if r_id in state.requirements:
                    if c_id not in state.requirements[r_id].acceptance_check_ids:
                        state.requirements[r_id].acceptance_check_ids.append(c_id)
                cls._recalculate_acceptance_counts(state)

        elif et in (EventType.ACCEPTANCE_CHECK_PASSED, EventType.ACCEPTANCE_CHECK_FAILED, EventType.ACCEPTANCE_CHECK_BLOCKED, EventType.ACCEPTANCE_CHECK_SKIPPED):
            c_id = payload.get("check_id")
            if c_id:
                status_map = {
                    EventType.ACCEPTANCE_CHECK_PASSED: AcceptanceCheckStatus.PASS,
                    EventType.ACCEPTANCE_CHECK_FAILED: AcceptanceCheckStatus.FAIL,
                    EventType.ACCEPTANCE_CHECK_BLOCKED: AcceptanceCheckStatus.BLOCKED,
                    EventType.ACCEPTANCE_CHECK_SKIPPED: AcceptanceCheckStatus.SKIPPED,
                }
                st = status_map[et]
                state.acceptance_ledger.record_result(
                    check_id=c_id,
                    status=st,
                    evidence_ref=payload.get("evidence_ref"),
                    error=payload.get("error"),
                    source_versions=payload.get("source_versions"),
                )
                cls._recalculate_acceptance_counts(state)

        elif et == EventType.TODO_CREATED:
            t_id = payload.get("todo_id")
            if t_id:
                prio_str = payload.get("priority", "MEDIUM")
                try:
                    prio = RequirementPriority(prio_str)
                except ValueError:
                    prio = RequirementPriority.MEDIUM
                state.todos[t_id] = TodoState(
                    todo_id=t_id,
                    goal_id=payload.get("goal_id", state.goal.goal_id),
                    requirement_ids=payload.get("requirement_ids", []),
                    title=payload.get("title", ""),
                    description=payload.get("description", ""),
                    status=TodoStatus.PENDING,
                    priority=prio,
                    dependencies=payload.get("dependencies", []),
                    owner=payload.get("owner", "T1"),
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                )

        elif et == EventType.TODO_UPDATED:
            t_id = payload.get("todo_id")
            if t_id and t_id in state.todos:
                todo = state.todos[t_id]
                for k, v in payload.items():
                    if k != "todo_id" and hasattr(todo, k):
                        setattr(todo, k, v)
                todo.updated_at = event.timestamp

        elif et == EventType.TODO_COMPLETED:
            t_id = payload.get("todo_id")
            if t_id and t_id in state.todos:
                state.todos[t_id].status = TodoStatus.DONE
                state.todos[t_id].updated_at = event.timestamp

        elif et == EventType.PROGRESS_UPDATED:
            for k in ("last_meaningful_change", "current_focus", "next_action", "blocked_reason", "progress_fingerprint"):
                if k in payload:
                    setattr(state.progress, k, payload[k])
            if "known_failures" in payload:
                state.progress.known_failures = list(payload["known_failures"])
            if "recent_evidence" in payload:
                state.progress.recent_evidence = list(payload["recent_evidence"])
            if "overall_status" in payload:
                state.progress.overall_status = payload["overall_status"]

        elif et == EventType.FOCUS_CHANGED:
            state.progress.current_focus = payload.get("requirement_id")
            if payload.get("requirement_id") in state.requirements:
                state.requirements[payload["requirement_id"]].active = True

        elif et == EventType.PLAN_CREATED:
            p_id = payload.get("plan_id", f"plan_{state.mission.mission_id}")
            steps_data = payload.get("steps", [])
            steps = [PlanStep(**s) if isinstance(s, dict) else s for s in steps_data]
            state.plan = PlanState(
                plan_id=p_id,
                goal_id=payload.get("goal_id", state.goal.goal_id),
                version=payload.get("version", 1),
                steps=steps,
                status=PlanStatus.DRAFT,
                risks=payload.get("risks", []),
                unknowns=payload.get("unknowns", []),
                open_questions=payload.get("open_questions", []),
                created_at=event.timestamp,
                updated_at=event.timestamp,
            )

        elif et == EventType.PLAN_APPROVED:
            if state.plan:
                state.plan.status = PlanStatus.APPROVED

        elif et == EventType.CONTRACT_CREATED:
            from core.contracts.blueprint import ImplementationBlueprint
            from core.contracts.manifest import InterfaceManifest
            from core.contracts.rubric import QualityRubric

            bp_data = payload.get("blueprint")
            if bp_data:
                state.blueprint = ImplementationBlueprint.from_dict(bp_data) if isinstance(bp_data, dict) else bp_data
            im_data = payload.get("interface_manifest")
            if im_data:
                state.interface_manifest = InterfaceManifest.from_dict(im_data) if isinstance(im_data, dict) else im_data
            qr_data = payload.get("quality_rubric")
            if qr_data:
                state.quality_rubric = QualityRubric.from_dict(qr_data) if isinstance(qr_data, dict) else qr_data
                state.plan.approved_by = payload.get("actor", "user")
                state.plan.approved_at = event.timestamp

        elif et == EventType.PLAN_REJECTED:
            if state.plan:
                state.plan.status = PlanStatus.REJECTED

        elif et == EventType.PLAN_STALE:
            if state.plan:
                state.plan.status = PlanStatus.STALE
                state.plan.reason_changed = payload.get("reason", "Requirements changed")

        # ── Phase 6 Skills ───────────────────────────────────────────────────
        elif et == EventType.SKILL_ROUTING_COMPLETED:
            skills = payload.get("selected_skills", [])
            if skills:
                state.progress.current_action = f"Skills selected: {', '.join(skills)}"
            else:
                state.progress.current_action = "No specialized skill required for task"

        elif et == EventType.SKILL_SELECTED:
            s_name = payload.get("skill_name") or payload.get("name")
            if s_name:
                if s_name not in state.active_skills:
                    state.active_skills.append(s_name)
                if state.mission and s_name not in state.mission.active_skills:
                    state.mission.active_skills.append(s_name)

        elif et == EventType.SKILL_LOADED:
            s_name = payload.get("skill_name") or payload.get("name")
            sha = payload.get("sha256") or payload.get("sha256_hash")
            if s_name and sha:
                state.skill_fingerprints[s_name] = sha
                if state.mission:
                    state.mission.skill_fingerprints[s_name] = sha

        elif et == EventType.SKILL_INVALIDATED:
            s_name = payload.get("skill_name") or payload.get("name")
            if s_name in state.active_skills:
                state.active_skills.remove(s_name)
            state.skill_fingerprints.pop(s_name, None)
            if state.mission:
                if s_name in state.mission.active_skills:
                    state.mission.active_skills.remove(s_name)
                state.mission.skill_fingerprints.pop(s_name, None)

        elif et == EventType.PLAN_MODE_ENTERED:
            state.execution_mode = ExecutionMode.PLAN_MODE

        elif et == EventType.PLAN_MODE_EXITED:
            state.execution_mode = ExecutionMode.EXECUTION_MODE

        # ── 15. Subagent Lifecycle ────────────────────────────────────────────
        aid = event.agent_id or payload.get("agent_id")
        subtask_id = event.task_id or payload.get("task_id")

        if et == EventType.SUBAGENT_CREATED:
            if aid:
                agent_type_str = payload.get("agent_type", "CUSTOM")
                try:
                    agent_type = AgentType(agent_type_str)
                except ValueError:
                    agent_type = AgentType.CUSTOM
                state.agents[aid] = AgentRecord(
                    agent_id=aid,
                    agent_type=agent_type,
                    mission_id=state.mission.mission_id,
                    parent_agent_id=event.parent_agent_id or payload.get("parent_agent_id"),
                    task_id=subtask_id,
                    context_id=payload.get("context_id", ""),
                    worktree_id=event.worktree_id or payload.get("worktree_id"),
                    execution_mode=payload.get("execution_mode", "EXECUTION_MODE"),
                    status=SubagentStatus.CREATED,
                    budget=SubagentBudget(**payload["budget"]) if "budget" in payload and isinstance(payload["budget"], dict) else SubagentBudget(),
                    tool_policy=SubagentToolPolicy(**payload["tool_policy"]) if "tool_policy" in payload and isinstance(payload["tool_policy"], dict) else SubagentToolPolicy(),
                    created_at=event.timestamp,
                )
            if subtask_id and subtask_id not in state.subagent_tasks:
                state.subagent_tasks[subtask_id] = SubagentTaskRecord(
                    task_id=subtask_id,
                    parent_task_id=payload.get("parent_task_id"),
                    mission_id=state.mission.mission_id,
                    goal_id=payload.get("goal_id", state.goal.goal_id),
                    requirement_ids=payload.get("requirement_ids", []),
                    todo_ids=payload.get("todo_ids", []),
                    title=payload.get("title", subtask_id),
                    description=payload.get("description", ""),
                    mode=payload.get("mode", "auto"),
                    status=SubagentStatus.CREATED,
                    agent_id=aid,
                    owner_agent_id=payload.get("owner_agent_id", "primary"),
                    parent_agent_id=event.parent_agent_id or payload.get("parent_agent_id"),
                    depth=payload.get("depth", 0),
                    created_at=event.timestamp,
                )

        elif et == EventType.SUBAGENT_STARTED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.RUNNING
                state.agents[aid].started_at = event.timestamp
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.RUNNING
                state.subagent_tasks[subtask_id].started_at = event.timestamp

        elif et == EventType.SUBAGENT_PROGRESS:
            if aid and aid in state.agents:
                rec = state.agents[aid]
                if "turns" in payload:
                    rec.resource_usage.turns = payload["turns"]
                if "tool_calls" in payload:
                    rec.resource_usage.tool_calls = payload["tool_calls"]
                if "wall_time_ms" in payload:
                    rec.resource_usage.wall_time_ms = payload["wall_time_ms"]
                if "input_tokens" in payload:
                    rec.resource_usage.input_tokens = payload["input_tokens"]
                if "output_tokens" in payload:
                    rec.resource_usage.output_tokens = payload["output_tokens"]

        elif et == EventType.SUBAGENT_WAITING:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.WAITING

        elif et == EventType.SUBAGENT_COMPLETED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.SUCCEEDED
                state.agents[aid].completed_at = event.timestamp
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.SUCCEEDED
                state.subagent_tasks[subtask_id].completed_at = event.timestamp

        elif et == EventType.SUBAGENT_FAILED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.FAILED
                state.agents[aid].completed_at = event.timestamp
                state.agents[aid].error = payload.get("error", "Execution failed")
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.FAILED
                state.subagent_tasks[subtask_id].completed_at = event.timestamp

        elif et == EventType.SUBAGENT_CANCELLED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.CANCELLED
                state.agents[aid].completed_at = event.timestamp
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.CANCELLED
                state.subagent_tasks[subtask_id].completed_at = event.timestamp

        elif et == EventType.SUBAGENT_TIMED_OUT:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.TIMED_OUT
                state.agents[aid].completed_at = event.timestamp
                state.agents[aid].error = payload.get("error", "Execution timed out")
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.TIMED_OUT
                state.subagent_tasks[subtask_id].completed_at = event.timestamp

        elif et == EventType.SUBAGENT_RESOURCE_EXCEEDED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.RESOURCE_EXCEEDED
                state.agents[aid].completed_at = event.timestamp
                state.agents[aid].error = payload.get("reason", "Resource limit exceeded")
            if subtask_id and subtask_id in state.subagent_tasks and not state.subagent_tasks[subtask_id].status.is_terminal:
                state.subagent_tasks[subtask_id].status = SubagentStatus.RESOURCE_EXCEEDED
                state.subagent_tasks[subtask_id].completed_at = event.timestamp

        # ── 16. Background Jobs Lifecycle ─────────────────────────────────────
        jid = event.job_id or payload.get("job_id")
        if et == EventType.BACKGROUND_JOB_CREATED:
            if jid:
                kind_str = payload.get("kind", "SUBAGENT")
                try:
                    kind_enum = JobKind(kind_str)
                except ValueError:
                    kind_enum = JobKind.SUBAGENT
                lifecycle_str = payload.get("lifecycle", "CHILD_BOUND")
                try:
                    lc_enum = JobLifecycle(lifecycle_str)
                except ValueError:
                    lc_enum = JobLifecycle.CHILD_BOUND
                state.background_jobs[jid] = BackgroundJobRecord(
                    job_id=jid,
                    owner_agent_id=payload.get("owner_agent_id", "primary"),
                    task_id=subtask_id or "",
                    kind=kind_enum,
                    status=JobStatus.QUEUED,
                    started_at=event.timestamp,
                    pid=payload.get("pid"),
                    worktree_id=event.worktree_id or payload.get("worktree_id"),
                    command=payload.get("command"),
                    cwd=payload.get("cwd", ""),
                    lifecycle=lc_enum,
                )

        elif et == EventType.BACKGROUND_JOB_STARTED:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.RUNNING
                state.background_jobs[jid].started_at = event.timestamp
                if "pid" in payload:
                    state.background_jobs[jid].pid = payload["pid"]

        elif et == EventType.BACKGROUND_JOB_WAITING:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.WAITING

        elif et == EventType.BACKGROUND_JOB_CANCEL_REQUESTED:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.CANCEL_REQUESTED

        elif et == EventType.BACKGROUND_JOB_COMPLETED:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.SUCCEEDED
                state.background_jobs[jid].completed_at = event.timestamp
                state.background_jobs[jid].exit_code = payload.get("exit_code", 0)
                state.background_jobs[jid].artifact_ref = payload.get("artifact_ref")

        elif et == EventType.BACKGROUND_JOB_FAILED:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.FAILED
                state.background_jobs[jid].completed_at = event.timestamp
                state.background_jobs[jid].exit_code = payload.get("exit_code", 1)
                state.background_jobs[jid].error = payload.get("error")

        elif et == EventType.BACKGROUND_JOB_CANCELLED:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.CANCELLED
                state.background_jobs[jid].completed_at = event.timestamp

        elif et == EventType.BACKGROUND_JOB_TIMED_OUT:
            if jid and jid in state.background_jobs and not state.background_jobs[jid].status.is_terminal:
                state.background_jobs[jid].status = JobStatus.TIMED_OUT
                state.background_jobs[jid].completed_at = event.timestamp
                state.background_jobs[jid].error = payload.get("error", "Job timed out")

        elif et == EventType.BACKGROUND_JOB_ORPHANED:
            if jid and jid in state.background_jobs:
                state.background_jobs[jid].status = JobStatus.ORPHANED
                state.background_jobs[jid].completed_at = event.timestamp

        # ── 17. Worktree Lifecycle ────────────────────────────────────────────
        wid = event.worktree_id or payload.get("worktree_id")
        if et == EventType.WORKTREE_CREATED:
            if wid:
                state.worktrees[wid] = WorktreeRecord(
                    worktree_id=wid,
                    path=payload.get("path", ""),
                    branch=payload.get("branch", ""),
                    base_commit=payload.get("base_commit", ""),
                    agent_id=aid or payload.get("agent_id", ""),
                    task_id=subtask_id or payload.get("task_id", ""),
                    status=WorktreeStatus.CREATED,
                    created_at=event.timestamp,
                    sparse_paths=payload.get("sparse_paths", []),
                )

        elif et == EventType.WORKTREE_READY:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.READY

        elif et == EventType.WORKTREE_DIRTY:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.IN_USE
                state.worktrees[wid].dirty = True

        elif et == EventType.WORKTREE_INTEGRATION_STARTED:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.HANDOFF

        elif et == EventType.WORKTREE_INTEGRATION_COMPLETED:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.INTEGRATED

        elif et == EventType.WORKTREE_INTEGRATION_FAILED:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.CONFLICT

        elif et == EventType.WORKTREE_ORPHANED:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.ORPHANED

        elif et == EventType.WORKTREE_CLEANED:
            if wid and wid in state.worktrees:
                state.worktrees[wid].status = WorktreeStatus.CLEANED
                state.worktrees[wid].deleted_at = event.timestamp

        # ── 18. Resource Limit Events ─────────────────────────────────────────
        elif et == EventType.RESOURCE_LIMIT_TERMINATED:
            if aid and aid in state.agents and not state.agents[aid].status.is_terminal:
                state.agents[aid].status = SubagentStatus.RESOURCE_EXCEEDED
                state.agents[aid].completed_at = event.timestamp

        # ── 19. Repair Lifecycle (Prompt 11) ──────────────────────────────────
        rep_id = event.repair_id or payload.get("repair_id")
        if et == EventType.REPAIR_ATTEMPTED:
            if rep_id:
                fc_val = payload.get("failure_class", FailureClass.UNKNOWN_FAILURE.value)
                try:
                    fc_enum = FailureClass(fc_val)
                except ValueError:
                    fc_enum = FailureClass.UNKNOWN_FAILURE
                state.repairs[rep_id] = RepairState(
                    repair_id=rep_id,
                    mission_id=state.mission.mission_id,
                    requirement_id=event.requirement_id or payload.get("requirement_id"),
                    check_id=event.acceptance_check_id or payload.get("check_id"),
                    task_id=event.task_id or payload.get("task_id"),
                    attempt=payload.get("attempt_number", 1),
                    status=RepairStatus.IN_PROGRESS,
                    failure_class=fc_enum,
                    failure_reason=payload.get("error_message", ""),
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                )
                state.progress.waiting_reason = WaitReason.REPAIRING

        elif et == EventType.REPAIR_COMPLETED:
            if rep_id:
                if rep_id not in state.repairs:
                    state.repairs[rep_id] = RepairState(
                        repair_id=rep_id,
                        mission_id=state.mission.mission_id,
                        attempt=payload.get("attempt_number", 1),
                        status=RepairStatus.COMPLETED,
                        created_at=event.timestamp,
                        updated_at=event.timestamp,
                    )
                else:
                    state.repairs[rep_id].status = RepairStatus.COMPLETED
                    state.repairs[rep_id].updated_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WORKING

        elif et in (EventType.REPAIR_FAILED, EventType.REPAIR_EXHAUSTED):
            if rep_id and rep_id in state.repairs:
                state.repairs[rep_id].status = RepairStatus.FAILED
                state.repairs[rep_id].updated_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.REPAIR_STALLED:
            if rep_id and rep_id in state.repairs:
                state.repairs[rep_id].status = RepairStatus.STALLED
                state.repairs[rep_id].updated_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WORKING

        # ── 20. Escalation Lifecycle (Prompt 11) ──────────────────────────────
        esc_id = event.escalation_id or payload.get("escalation_id")
        if esc_id and esc_id not in state.escalations and et.name.startswith(("ESCALATION_", "T2_", "T3_")):
            state.escalations[esc_id] = EscalationState(
                escalation_id=esc_id,
                mission_id=state.mission.mission_id,
                requirement_id=event.requirement_id or payload.get("requirement_id"),
                check_id=event.acceptance_check_id or payload.get("check_id"),
                decision=EscalationDecisionType.NO_ESCALATION,
                created_at=event.timestamp,
                updated_at=event.timestamp,
            )

        if et in (EventType.T2_REQUESTED, EventType.T2_STARTED):
            if esc_id and esc_id in state.escalations:
                state.escalations[esc_id].level = "T2_CRITIC"
                state.escalations[esc_id].updated_at = event.timestamp

        elif et == EventType.T2_COMPLETED:
            if esc_id and esc_id in state.escalations:
                approved = payload.get("approved", False)
                state.escalations[esc_id].t2_verdict = "APPROVED" if approved else "REJECTED"
                state.escalations[esc_id].updated_at = event.timestamp

        elif et in (EventType.T3_REQUESTED, EventType.T3_STARTED):
            if esc_id and esc_id in state.escalations:
                state.escalations[esc_id].level = "T3_JUDGE"
                state.escalations[esc_id].updated_at = event.timestamp

        elif et == EventType.T3_COMPLETED:
            if esc_id and esc_id in state.escalations:
                decision_val = payload.get("decision", "REJECT")
                try:
                    dec_enum = EscalationDecisionType(decision_val)
                except ValueError:
                    dec_enum = EscalationDecisionType.REJECT
                state.escalations[esc_id].decision = dec_enum
                state.escalations[esc_id].t3_decision = decision_val
                state.escalations[esc_id].updated_at = event.timestamp

        return state

    @classmethod
    def _handle_evidence(cls, state: HermesRuntimeState, event: HermesEvent, payload: Dict[str, Any]) -> None:
        ev_id = payload.get("evidence_id") or event.evidence_id or f"ev_{event.event_id}"
        kind_str = payload.get("kind", "TOOL_RESULT")
        try:
            kind_enum = EvidenceKind(kind_str)
        except ValueError:
            kind_enum = EvidenceKind.TOOL_RESULT

        state.evidence[ev_id] = EvidenceState(
            evidence_id=ev_id,
            mission_id=state.mission.mission_id,
            task_id=event.task_id or payload.get("task_id"),
            source=event.source or payload.get("source", "tool"),
            kind=kind_enum,
            timestamp=event.timestamp,
            artifact_path=payload.get("artifact_path"),
            verification_reference=payload.get("verification_reference") or event.acceptance_check_id or payload.get("acceptance_check_id"),
            digest=payload.get("digest"),
            valid=payload.get("valid", True),
            freshness=payload.get("freshness", "FRESH"),
            trust_class=payload.get("trust_class", "TOOL_DERIVED_OBSERVATION"),
            requirement_id=event.requirement_id or payload.get("requirement_id"),
            acceptance_check_id=event.acceptance_check_id or payload.get("acceptance_check_id"),
        )

    @classmethod
    def _recalculate_task_counts(cls, state: HermesRuntimeState) -> None:
        completed = sum(1 for t in state.tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in state.tasks.values() if t.status == TaskStatus.FAILED)
        total = len(state.tasks)

        state.mission.completed_task_count = completed
        state.mission.failed_task_count = failed
        state.progress.completed_tasks = completed
        state.progress.total_tasks = total
        state.progress.overall_fraction = (completed / total) if total > 0 else 0.0

    @classmethod
    def _recalculate_requirement_counts(cls, state: HermesRuntimeState) -> None:
        total = len(state.requirements)
        verified = sum(1 for r in state.requirements.values() if r.status in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED))
        state.progress.total_requirements_count = total
        state.progress.verified_requirements_count = verified

    @classmethod
    def _recalculate_acceptance_counts(cls, state: HermesRuntimeState) -> None:
        total = len(state.acceptance_ledger.checks)
        passed = sum(1 for c in state.acceptance_ledger.checks.values() if c.status == AcceptanceCheckStatus.PASS)
        state.progress.total_checks_count = total
        state.progress.passing_checks_count = passed
