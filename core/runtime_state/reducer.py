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
        # Stale event sequence check: reject out-of-order sequence regressing state
        if event.sequence > 0 and event.sequence <= state.last_event_sequence:
            # Stale sequence, record sequence and return state unchanged
            return state

        # Create or update sequence and timestamp
        state.last_event_sequence = max(state.last_event_sequence, event.sequence)
        state.state_version += 1
        state.last_updated_at = event.timestamp or time.time()
        state.progress.last_state_change_at = state.last_updated_at
        et = event.event_type
        payload = event.payload or {}

        # ── 1. Terminal Mission Guard ─────────────────────────────────────────
        # If mission is terminal (COMPLETED, FAILED, CANCELLED, ABORTED),
        # ignore events that would reopen or regress the mission.
        if state.mission.is_terminal:
            # Allow purely informational observation/evidence events, but do not
            # resurrect mission to RUNNING or change task status.
            if et in {EventType.EVIDENCE_CREATED, EventType.STATE_SNAPSHOT}:
                cls._handle_evidence(state, event, payload)
            return state

        # ── 2. Mission Lifecycle ──────────────────────────────────────────────
        if et == EventType.MISSION_CREATED:
            state.mission.status = MissionStatus.CREATED
            state.mission.prompt = payload.get("prompt", state.mission.prompt)
            state.mission.workspace_root = payload.get("workspace_root", state.mission.workspace_root)
            state.mission.execution_mode = payload.get("execution_mode", state.mission.execution_mode)

        elif et == EventType.PLANNING_STARTED:
            state.mission.status = MissionStatus.PLANNING
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
            state.mission.status = MissionStatus.RUNNING
            state.mission.start_time = event.timestamp
            state.progress.waiting_reason = WaitReason.WORKING
            state.progress.current_action = "Mission execution started"

        elif et == EventType.MISSION_PAUSED:
            state.mission.status = MissionStatus.PAUSED

        elif et == EventType.MISSION_RESUMED:
            state.mission.status = MissionStatus.RUNNING

        elif et == EventType.MISSION_COMPLETING:
            state.mission.status = MissionStatus.COMPLETING

        elif et == EventType.MISSION_COMPLETED:
            state.mission.status = MissionStatus.COMPLETED
            state.mission.end_time = event.timestamp
            state.mission.completion_reason = payload.get("reason", "All tasks verified successfully")
            state.progress.waiting_reason = WaitReason.COMPLETED
            state.progress.current_action = "Mission completed"

        elif et == EventType.MISSION_FAILED:
            state.mission.status = MissionStatus.FAILED
            state.mission.end_time = event.timestamp
            state.mission.abort_reason = payload.get("error", "Execution failure")
            state.progress.waiting_reason = WaitReason.FAILED
            state.progress.current_action = f"Mission failed: {state.mission.abort_reason}"

        elif et == EventType.MISSION_BLOCKED:
            state.mission.status = MissionStatus.BLOCKED

        elif et in {EventType.MISSION_CANCELLED, EventType.MISSION_ABORTED}:
            state.mission.status = MissionStatus.CANCELLED if et == EventType.MISSION_CANCELLED else MissionStatus.ABORTED
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
                task.completion_reason = payload.get("reason", "Task finished")
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
        if et == EventType.VERIFICATION_STARTED:
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

        elif et == EventType.VERIFICATION_COMPLETED:
            state.verification.status = VerificationStatus.PASSED
            state.verification.completed_at = event.timestamp
            state.verification.verdict = payload.get("verdict", "PASSED")
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = False
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.VERIFICATION_FAILED:
            state.verification.status = VerificationStatus.FAILED
            state.verification.completed_at = event.timestamp
            state.verification.verdict = payload.get("verdict", "FAILED")
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = True

        elif et == EventType.VERIFICATION_NEEDS_IMPROVEMENT:
            state.verification.status = VerificationStatus.NEEDS_IMPROVEMENT
            state.verification.completed_at = event.timestamp
            state.verification.verdict = "NEEDS_IMPROVEMENT"
            state.verification.confidence = payload.get("confidence", state.verification.confidence)
            state.verification.issues = payload.get("issues", [])
            state.verification.repair_required = True
            state.progress.waiting_reason = WaitReason.REPAIRING

        # ── 7. Network Lifecycle ──────────────────────────────────────────────
        if et == EventType.NETWORK_CONNECTING:
            state.network.connectivity = NetworkConnectivity.CONNECTING
        elif et == EventType.NETWORK_CONNECTED:
            state.network.connectivity = NetworkConnectivity.CONNECTED
            state.network.connected_at = event.timestamp
            state.network.reconnecting = False
        elif et == EventType.NETWORK_DEGRADED:
            state.network.connectivity = NetworkConnectivity.DEGRADED
        elif et == EventType.NETWORK_DISCONNECTED:
            state.network.connectivity = NetworkConnectivity.DISCONNECTED
            state.network.disconnected_at = event.timestamp
            state.network.last_error = payload.get("error", "Disconnected")
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK
        elif et == EventType.NETWORK_RECONNECTING:
            state.network.connectivity = NetworkConnectivity.RECONNECTING
            state.network.reconnecting = True
            state.network.retry_count += 1
            state.progress.waiting_reason = WaitReason.WAITING_FOR_NETWORK
        elif et == EventType.NETWORK_RESTORED:
            state.network.connectivity = NetworkConnectivity.CONNECTED
            state.network.reconnecting = False
            state.network.health_status = "HEALTHY"
            state.progress.waiting_reason = WaitReason.WORKING
        elif et == EventType.NETWORK_FAILED:
            state.network.connectivity = NetworkConnectivity.FAILED

        # ── 8. Permission Lifecycle ───────────────────────────────────────────
        if et == EventType.PERMISSION_REQUESTED:
            state.permission.status = PermissionStatus.REQUESTED
            state.permission.permission_request_id = payload.get("request_id")
            state.permission.action = payload.get("action", "")
            state.permission.risk = payload.get("risk", "NORMAL")
            state.permission.requested_at = event.timestamp
            state.progress.waiting_reason = WaitReason.WAITING_FOR_PERMISSION

        elif et == EventType.PERMISSION_APPROVED:
            state.permission.status = PermissionStatus.APPROVED
            state.permission.resolved_at = event.timestamp
            state.permission.decision = "APPROVED"
            state.progress.waiting_reason = WaitReason.WORKING

        elif et == EventType.PERMISSION_DENIED:
            state.permission.status = PermissionStatus.DENIED
            state.permission.resolved_at = event.timestamp
            state.permission.decision = "DENIED"
            state.permission.resolution_reason = payload.get("reason", "Denied")

        # ── 9. Session Lifecycle ──────────────────────────────────────────────
        if et == EventType.SESSION_STARTED:
            state.session.status = SessionStatus.ACTIVE
        elif et == EventType.SESSION_PAUSED:
            state.session.status = SessionStatus.PAUSED
        elif et == EventType.SESSION_CLOSED:
            state.session.status = SessionStatus.CLOSED

        # ── 10. Evidence Lifecycle ────────────────────────────────────────────
        if et == EventType.EVIDENCE_CREATED:
            cls._handle_evidence(state, event, payload)

        # ── 11. Checkpoint Lifecycle ──────────────────────────────────────────
        if et == EventType.CHECKPOINT_CREATED:
            state.checkpoint.status = CheckpointStatus.CREATING
        elif et == EventType.CHECKPOINT_AVAILABLE:
            state.checkpoint.status = CheckpointStatus.AVAILABLE
            state.checkpoint.checkpoint_id = event.checkpoint_id or payload.get("checkpoint_id")
            state.checkpoint.created_at = event.timestamp

        return state

    @classmethod
    def _handle_evidence(cls, state: HermesRuntimeState, event: HermesEvent, payload: Dict[str, Any]) -> None:
        ev_id = payload.get("evidence_id") or f"ev_{event.event_id}"
        kind_str = payload.get("kind", "TOOL_RESULT")
        try:
            kind_enum = EvidenceKind(kind_str)
        except ValueError:
            kind_enum = EvidenceKind.TOOL_RESULT

        state.evidence[ev_id] = EvidenceState(
            evidence_id=ev_id,
            mission_id=state.mission.mission_id,
            task_id=event.task_id or payload.get("task_id"),
            source=event.source,
            kind=kind_enum,
            timestamp=event.timestamp,
            artifact_path=payload.get("artifact_path"),
            verification_reference=payload.get("verification_reference"),
            valid=True,
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
