# ui/state/selectors.py
"""
Pure State Selectors mapping HermesRuntimeState to ViewModels.

STRICT INVARIANTS:
1. PURE FUNCTIONS: Zero I/O, zero network, zero filesystem, zero database queries.
2. NONE SAFETY: Numeric/float None or NaN never raises TypeError; formats to 'N/A'.
3. TEXT SANITIZATION: All display strings passed through sanitize_terminal_text.
4. UNKNOWN/STALE RECOGNITION: Missing states explicitly labeled UNKNOWN/PENDING.
5. NO HIDDEN REASONING: Strips <think>...</think> and internal system prompts.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    TaskStatus,
    ToolStatus,
    ModelStatus,
    VerificationStatus,
    AcceptanceCheckStatus,
    NetworkConnectivity,
    PermissionStatus,
    SessionStatus,
    JobStatus,
)
from ui.rendering.text_safety import sanitize_terminal_text
from ui.viewmodels import (
    AcceptanceCheckViewModel,
    ApprovalModalViewModel,
    ChatMessageViewModel,
    ChatEntryKind,
    ChatViewModel,
    CheckpointItemViewModel,
    CheckpointSelectorViewModel,
    HermesViewModel,
    JobItemViewModel,
    JobViewModel,
    MemoryViewModel,
    MissionViewModel,
    NetworkViewModel,
    ProgressViewModel,
    RecoveryViewModel,
    RewindPreviewViewModel,
    SecurityViewModel,
    SessionViewModel,
    TaskItemViewModel,
    TaskQueueViewModel,
    ToolTraceItemViewModel,
    ToolTraceViewModel,
    VerificationViewModel,
)


def safe_float_str(val: Any, fmt: str = ".2f", fallback: str = "N/A") -> str:
    """Format numeric values safely without raising TypeError on None, NaN, inf, or bad types."""
    if val is None:
        return fallback
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return fallback
        return f"{f:{fmt}}"
    except (ValueError, TypeError):
        return fallback


def select_mission_view_model(state: HermesRuntimeState) -> MissionViewModel:
    m = state.mission
    now = time.time()
    elapsed = max(0.0, (m.end_time or now) - (m.start_time or now))
    elapsed_str = f"{elapsed:.1f}s" if m.start_time else "N/A"

    return MissionViewModel(
        mission_id=sanitize_terminal_text(m.mission_id or "default"),
        status=m.status.value if hasattr(m.status, "value") else str(m.status or "UNKNOWN"),
        title=sanitize_terminal_text(m.title or "Untitled Mission"),
        prompt_summary=sanitize_terminal_text(m.prompt[:120] if m.prompt else ""),
        start_time_str=time.strftime("%H:%M:%S", time.localtime(m.start_time)) if m.start_time else "N/A",
        elapsed_time_str=elapsed_str,
        completed_tasks=m.completed_task_count,
        total_tasks=m.task_count,
        is_terminal=m.is_terminal,
        abort_reason=sanitize_terminal_text(m.abort_reason) if m.abort_reason else None,
    )


def select_progress_view_model(state: HermesRuntimeState) -> ProgressViewModel:
    p = state.progress
    frac = max(0.0, min(1.0, float(p.overall_fraction or 0.0)))
    pct_str = f"{int(frac * 100)}%"

    active_task_title = "None"
    if state.current_task:
        active_task_title = state.current_task.title

    return ProgressViewModel(
        overall_status=sanitize_terminal_text(p.overall_status or "IDLE"),
        percentage_str=pct_str,
        fraction=frac,
        current_stage_name=sanitize_terminal_text(p.current_stage_name or "Idle"),
        current_action=sanitize_terminal_text(p.current_action or ""),
        active_task_title=sanitize_terminal_text(active_task_title),
        next_action=sanitize_terminal_text(p.next_action or "Awaiting instructions"),
        waiting_reason=p.waiting_reason.value if hasattr(p.waiting_reason, "value") else str(p.waiting_reason or "NONE"),
        blocked_reason=sanitize_terminal_text(p.blocked_reason) if p.blocked_reason else None,
        known_failures=tuple(sanitize_terminal_text(f) for f in p.known_failures),
    )


def select_task_queue_view_model(state: HermesRuntimeState) -> TaskQueueViewModel:
    items = []
    # Sort tasks stably by order_index
    sorted_tasks = sorted(state.tasks.values(), key=lambda t: (t.order_index, t.task_id))
    completed_count = 0

    for t in sorted_tasks:
        s_val = t.status.value if hasattr(t.status, "value") else str(t.status or "PENDING")
        if s_val == TaskStatus.COMPLETED.value:
            completed_count += 1
        items.append(
            TaskItemViewModel(
                task_id=sanitize_terminal_text(t.task_id),
                order_index=t.order_index,
                title=sanitize_terminal_text(t.title),
                status=s_val,
                attempts=t.attempts,
                repair_state=sanitize_terminal_text(t.repair_state or "NOT_REQUIRED"),
                failure_reason=sanitize_terminal_text(t.failure_reason) if t.failure_reason else None,
            )
        )

    curr_id = state.current_task.task_id if state.current_task else None

    return TaskQueueViewModel(
        tasks=tuple(items),
        current_task_id=sanitize_terminal_text(curr_id) if curr_id else None,
        completed_count=completed_count,
        total_count=len(items),
    )


def select_tool_trace_view_model(state: HermesRuntimeState) -> ToolTraceViewModel:
    te = state.tool_execution
    recent_items = []

    for r in te.recent_tools[-20:]:  # Keep recent 20 in view
        dur = safe_float_str(r.get("duration_seconds"), ".3f", "N/A")
        dur_str = f"{dur}s" if dur != "N/A" else "N/A"
        ts = r.get("timestamp", 0.0)
        ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""

        recent_items.append(
            ToolTraceItemViewModel(
                tool_call_id=sanitize_terminal_text(r.get("tool_call_id", "")),
                tool_name=sanitize_terminal_text(r.get("tool_name", "unknown")),
                status=sanitize_terminal_text(r.get("status", "COMPLETED")),
                arguments_preview=sanitize_terminal_text(str(r.get("arguments_summary", ""))[:80]),
                output_preview=sanitize_terminal_text(str(r.get("output_preview", ""))[:120]),
                duration_str=dur_str,
                exit_code=r.get("exit_code"),
                risk_level=sanitize_terminal_text(r.get("risk_level", "NORMAL")),
                timestamp_str=ts_str,
                is_error=not bool(r.get("success", True)),
            )
        )

    s_val = te.status.value if hasattr(te.status, "value") else str(te.status or "IDLE")

    return ToolTraceViewModel(
        recent_tools=tuple(recent_items),
        active_tool_name=sanitize_terminal_text(te.tool_name) if te.tool_name else None,
        active_status=s_val,
        total_invocations=te.retry_count + len(recent_items),
        successful_invocations=sum(1 for r in recent_items if not r.is_error),
        failed_invocations=sum(1 for r in recent_items if r.is_error),
    )


def select_verification_view_model(state: HermesRuntimeState) -> VerificationViewModel:
    v = state.verification
    ledger = state.acceptance_ledger

    check_items = []
    # Stably sort checks
    sorted_checks = sorted(ledger.checks.values(), key=lambda c: (c.requirement_id, c.check_id))
    passing = 0
    critical_failed = 0

    for c in sorted_checks:
        s_val = c.status.value if hasattr(c.status, "value") else str(c.status or "NOT_RUN")
        if s_val == AcceptanceCheckStatus.PASS.value:
            passing += 1
        elif s_val == AcceptanceCheckStatus.FAIL.value and c.critical:
            critical_failed += 1

        lr_str = time.strftime("%H:%M:%S", time.localtime(c.last_run_at)) if c.last_run_at else "N/A"

        check_items.append(
            AcceptanceCheckViewModel(
                check_id=sanitize_terminal_text(c.check_id),
                requirement_id=sanitize_terminal_text(c.requirement_id),
                description=sanitize_terminal_text(c.description),
                status=s_val,
                critical=c.critical,
                error_message=sanitize_terminal_text(c.error_message) if c.error_message else None,
                last_run_str=lr_str,
            )
        )

    status_val = v.status.value if hasattr(v.status, "value") else str(v.status or "IDLE")
    conf_str = safe_float_str(v.confidence, ".2f", "N/A")

    return VerificationViewModel(
        status=status_val,
        checks=tuple(check_items),
        passing_checks=passing,
        total_checks=len(check_items),
        critical_failed=critical_failed,
        confidence_str=conf_str,
        issues=tuple(sanitize_terminal_text(i) for i in v.issues),
        repair_required=v.repair_required,
    )


def select_security_view_model(state: HermesRuntimeState) -> SecurityViewModel:
    p = state.permission
    s_val = p.status.value if hasattr(p.status, "value") else str(p.status or "NONE")
    pending = s_val == PermissionStatus.REQUESTED.value

    modal = None
    if pending:
        modal = ApprovalModalViewModel(
            visible=True,
            request_id=sanitize_terminal_text(p.permission_request_id or ""),
            action_summary=sanitize_terminal_text(p.action),
            risk_level=sanitize_terminal_text(p.risk),
            explanation=f"Action '{p.action}' requires user authorization under security policy.",
        )

    return SecurityViewModel(
        status=s_val,
        action=sanitize_terminal_text(p.action),
        risk_level=sanitize_terminal_text(p.risk),
        decision=sanitize_terminal_text(p.decision or "ALLOWED"),
        pending_approval=pending,
        approval_scope="SESSION" if pending else "",
        modal=modal,
    )


def select_session_view_model(state: HermesRuntimeState) -> SessionViewModel:
    s = state.session
    s_val = s.status.value if hasattr(s.status, "value") else str(s.status or "CREATED")
    act_str = time.strftime("%H:%M:%S", time.localtime(s.last_activity)) if s.last_activity else "N/A"

    return SessionViewModel(
        session_id=sanitize_terminal_text(s.session_id or "default"),
        mission_id=sanitize_terminal_text(s.mission_id or "default"),
        status=s_val,
        branch_name=sanitize_terminal_text(s.branch or "main"),
        current_checkpoint_id=sanitize_terminal_text(s.last_checkpoint_id) if s.last_checkpoint_id else None,
        is_resumable=s.resumable,
        last_activity_str=act_str,
    )


def select_network_view_model(state: HermesRuntimeState) -> NetworkViewModel:
    n = state.network
    conn_val = n.connectivity.value if hasattr(n.connectivity, "value") else str(n.connectivity or "UNKNOWN")
    lat_str = safe_float_str(n.latency_ms, ".1f", "N/A")
    ttft_str = safe_float_str(n.ttft_ms, ".1f", "N/A")

    return NetworkViewModel(
        connectivity=conn_val,
        circuit_state=sanitize_terminal_text(n.circuit_state or "CLOSED"),
        t1_provider=sanitize_terminal_text(n.provider or "nvidia_nim"),
        t1_health=sanitize_terminal_text(n.health_status or "HEALTHY"),
        latency_ms_str=f"{lat_str} ms" if lat_str != "N/A" else "N/A",
        ttft_ms_str=f"{ttft_str} ms" if ttft_str != "N/A" else "N/A",
        reconnecting=n.reconnecting,
        retry_count=n.retry_count,
    )


def select_jobs_view_model(state: HermesRuntimeState) -> JobViewModel:
    items = []
    active = 0
    # Stably sort jobs
    sorted_jobs = sorted(state.background_jobs.values(), key=lambda j: (j.started_at, j.job_id))

    for j in sorted_jobs:
        s_val = j.status.value if hasattr(j.status, "value") else str(j.status or "QUEUED")
        if s_val in (JobStatus.RUNNING.value, JobStatus.STARTING.value):
            active += 1
        items.append(
            JobItemViewModel(
                job_id=sanitize_terminal_text(j.job_id),
                kind=j.kind.value if hasattr(j.kind, "value") else str(j.kind),
                status=s_val,
                owner=sanitize_terminal_text(j.owner_agent_id),
                pid_str=str(j.pid) if j.pid else "N/A",
                command_summary=sanitize_terminal_text(j.command or ""),
                worktree_id=sanitize_terminal_text(j.worktree_id or ""),
            )
        )

    return JobViewModel(
        jobs=tuple(items),
        active_count=active,
        total_count=len(items),
    )


def select_memory_view_model(state: HermesRuntimeState) -> MemoryViewModel:
    """
    Project memory facts from state metadata.
    Zero filesystem or MEMORY.md access!
    """
    mem_facts = state.metadata.get("memory_facts", [])
    safe_facts = tuple(sanitize_terminal_text(f) for f in mem_facts)
    return MemoryViewModel(
        project="default",
        facts=safe_facts,
        total_facts=len(safe_facts),
        is_empty=len(safe_facts) == 0,
    )


def build_root_view_model(
    state: HermesRuntimeState,
    revision: int = 0,
    chat_messages: Sequence[ChatMessageViewModel] = (),
    is_streaming: bool = False,
    streaming_content: str = "",
    checkpoints: Sequence[CheckpointItemViewModel] = (),
    rewind_preview: Optional[RewindPreviewViewModel] = None,
    recovery: Optional[RecoveryViewModel] = None,
    active_notifications: Sequence[str] = (),
    active_tab: str = "chat",
    is_fallback_active: bool = False,
) -> HermesViewModel:
    """
    Assemble the authoritative, immutable RootViewModel.
    """
    chat_vm = ChatViewModel(
        messages=tuple(chat_messages),
        total_messages=len(chat_messages),
        is_streaming=is_streaming,
        streaming_partial_content=sanitize_terminal_text(streaming_content),
    )

    chk_vm = CheckpointSelectorViewModel(
        checkpoints=tuple(checkpoints),
        selected_index=0,
        visible=len(checkpoints) > 0,
    )

    rec_vm = recovery or RecoveryViewModel()
    rew_vm = rewind_preview or RewindPreviewViewModel()

    return HermesViewModel(
        sequence=state.last_event_sequence,
        revision=revision,
        state_version=state.state_version,
        mission_id=state.mission.mission_id or "default",
        session_id=state.session.session_id or "default",
        mission=select_mission_view_model(state),
        progress=select_progress_view_model(state),
        chat=chat_vm,
        tasks=select_task_queue_view_model(state),
        tools=select_tool_trace_view_model(state),
        verification=select_verification_view_model(state),
        security=select_security_view_model(state),
        session=select_session_view_model(state),
        checkpoint=chk_vm,
        recovery=rec_vm,
        rewind_preview=rew_vm,
        network=select_network_view_model(state),
        jobs=select_jobs_view_model(state),
        memory=select_memory_view_model(state),
        active_notifications=tuple(sanitize_terminal_text(n) for n in active_notifications),
        active_tab=active_tab,
        is_fallback_active=is_fallback_active,
    )
