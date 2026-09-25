# core/runtime_state/selectors.py
"""
Deterministic View Models and Selectors for HERMES 2.x.
Provides safe, read-only projections of the authoritative HermesRuntimeState.

Guarantees:
- Zero side-effects: no network, no models, no files, no state mutations.
- Partial-state safety: transforms None/null into render-safe semantic labels
  (e.g., confidence=None -> "Pending", tool_name=None -> "Unknown tool").
- Unambiguous "Why Waiting?" resolution based on active runtime contracts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    TaskStatus,
    WaitReason,
    ToolStatus,
    ModelStatus,
    VerificationStatus,
    NetworkConnectivity,
    PermissionStatus,
)


@dataclass(frozen=True)
class MissionViewModel:
    mission_id: str
    status_label: str
    progress_label: str
    elapsed_label: str
    is_terminal: bool
    prompt_summary: str


@dataclass(frozen=True)
class TaskViewModel:
    task_id: str
    title: str
    status_badge: str
    iteration_label: str
    is_active: bool
    error_label: Optional[str] = None


@dataclass(frozen=True)
class ModelViewModel:
    display_name: str
    provider_label: str
    tier_label: str
    status_label: str
    latency_label: str
    is_streaming: bool


@dataclass(frozen=True)
class ToolViewModel:
    tool_label: str
    status_badge: str
    exit_code_label: str
    duration_label: str
    is_running: bool
    target_label: str


@dataclass(frozen=True)
class VerificationViewModel:
    status_label: str
    verdict_badge: str
    confidence_label: str
    issues_summary: str
    repair_needed: bool


@dataclass(frozen=True)
class NetworkViewModel:
    status_label: str
    endpoint_label: str
    latency_label: str
    is_reconnecting: bool
    is_healthy: bool


@dataclass(frozen=True)
class PermissionViewModel:
    has_pending_request: bool
    action_summary: str
    risk_badge: str
    request_id: Optional[str]


@dataclass(frozen=True)
class ProgressViewModel:
    headline: str
    completed_ratio: str
    fraction: float
    waiting_reason_label: str
    current_stage_label: str


@dataclass(frozen=True)
class HermesViewModelBundle:
    mission: MissionViewModel
    progress: ProgressViewModel
    tasks: List[TaskViewModel]
    active_task: Optional[TaskViewModel]
    model: ModelViewModel
    tool: ToolViewModel
    verification: VerificationViewModel
    network: NetworkViewModel
    permission: PermissionViewModel


class ViewModelBuilder:
    """
    Deterministic projection builder transforming raw runtime state into
    bulletproof, crash-resistant view representations for UI rendering.
    """

    @classmethod
    def build(cls, state: HermesRuntimeState) -> HermesViewModelBundle:
        now = time.time()
        m = state.mission
        prog = state.progress
        m_exec = state.model_execution
        t_exec = state.tool_execution
        v_state = state.verification
        net = state.network
        perm = state.permission

        # ── 1. Mission View Model ─────────────────────────────────────────────
        elapsed_sec = (m.end_time or now) - m.start_time if m.start_time else 0.0
        elapsed_str = f"{elapsed_sec:.1f}s" if elapsed_sec < 60 else f"{int(elapsed_sec // 60)}m {int(elapsed_sec % 60)}s"
        mission_vm = MissionViewModel(
            mission_id=m.mission_id,
            status_label=m.status.value,
            progress_label=f"{prog.completed_tasks}/{prog.total_tasks}",
            elapsed_label=elapsed_str,
            is_terminal=m.is_terminal,
            prompt_summary=(m.prompt[:60] + "...") if len(m.prompt) > 60 else m.prompt,
        )

        # ── 2. Progress View Model ────────────────────────────────────────────
        headline = cls._derive_progress_headline(state)
        progress_vm = ProgressViewModel(
            headline=headline,
            completed_ratio=f"{prog.completed_tasks}/{prog.total_tasks}",
            fraction=prog.overall_fraction,
            waiting_reason_label=prog.waiting_reason.value,
            current_stage_label=f"Stage {prog.current_stage}: {prog.current_stage_name}" if prog.current_stage > 0 else "",
        )

        # ── 3. Task View Models ───────────────────────────────────────────────
        tasks_vm: List[TaskViewModel] = []
        active_task_vm: Optional[TaskViewModel] = None
        for tid, t in sorted(state.tasks.items(), key=lambda item: item[1].order_index):
            is_act = (tid == m.current_task_id)
            badge = {
                TaskStatus.PENDING: "○ Pending",
                TaskStatus.READY: "◇ Ready",
                TaskStatus.RUNNING: "▶ Running",
                TaskStatus.WAITING: "◌ Waiting",
                TaskStatus.VERIFYING: "◈ Verifying",
                TaskStatus.REPAIRING: "⚠ Repairing",
                TaskStatus.BLOCKED: "⊘ Blocked",
                TaskStatus.COMPLETED: "✓ Completed",
                TaskStatus.FAILED: "✗ Failed",
                TaskStatus.CANCELLED: "⊘ Cancelled",
            }.get(t.status, "○ Pending")

            tvm = TaskViewModel(
                task_id=tid,
                title=t.title or tid,
                status_badge=badge,
                iteration_label=f"iter {t.current_iteration}/{t.max_iterations}",
                is_active=is_act,
                error_label=t.failure_reason,
            )
            tasks_vm.append(tvm)
            if is_act:
                active_task_vm = tvm

        # ── 4. Model View Model ───────────────────────────────────────────────
        m_name = m_exec.model if m_exec.model else "Tier 1 (NVIDIA NIM)"
        m_prov = m_exec.provider if m_exec.provider else "nvidia_nim"
        m_lat = f"{m_exec.duration_seconds:.2f}s" if m_exec.duration_seconds is not None else "-"
        model_vm = ModelViewModel(
            display_name=m_name,
            provider_label=m_prov,
            tier_label=f"Tier {m_exec.tier}",
            status_label=m_exec.status.value,
            latency_label=m_lat,
            is_streaming=(m_exec.status == ModelStatus.STREAMING),
        )

        # ── 5. Tool View Model ────────────────────────────────────────────────
        # Invariant: tool_name is NEVER None in the UI layer
        tool_name_safe = t_exec.tool_name if t_exec.tool_name else "Unknown tool"
        t_badge = {
            ToolStatus.IDLE: "Idle",
            ToolStatus.REQUESTED: "Requested",
            ToolStatus.VALIDATING: "Validating",
            ToolStatus.STARTED: "Starting",
            ToolStatus.RUNNING: "Executing",
            ToolStatus.SUCCEEDED: "✓ Succeeded",
            ToolStatus.FAILED: "✗ Failed",
            ToolStatus.CANCELLED: "Cancelled",
        }.get(t_exec.status, "Idle")

        t_exit = str(t_exec.exit_code) if t_exec.exit_code is not None else "-"
        t_dur = f"{t_exec.duration_seconds:.2f}s" if t_exec.duration_seconds is not None else "-"
        tool_vm = ToolViewModel(
            tool_label=tool_name_safe,
            status_badge=t_badge,
            exit_code_label=t_exit,
            duration_label=t_dur,
            is_running=(t_exec.status == ToolStatus.RUNNING),
            target_label=t_exec.workspace_target or "-",
        )

        # ── 6. Verification View Model ────────────────────────────────────────
        # Invariant: confidence=None produces "Pending", NEVER crashing format string
        if v_state.confidence is not None:
            conf_str = f"{v_state.confidence:.2f}"
        else:
            conf_str = "Pending"

        v_badge = {
            VerificationStatus.IDLE: "Not Started",
            VerificationStatus.PENDING: "Pending",
            VerificationStatus.RUNNING: "Evaluating",
            VerificationStatus.PASSED: "✓ Passed",
            VerificationStatus.FAILED: "✗ Failed",
            VerificationStatus.NEEDS_IMPROVEMENT: "⚠ Needs Improvement",
            VerificationStatus.BLOCKED: "Blocked",
            VerificationStatus.CANCELLED: "Cancelled",
        }.get(v_state.status, "Not Started")

        issues_summary = "; ".join(v_state.issues[:2]) if v_state.issues else "None"
        verification_vm = VerificationViewModel(
            status_label=v_state.status.value,
            verdict_badge=v_badge,
            confidence_label=conf_str,
            issues_summary=issues_summary,
            repair_needed=v_state.repair_required,
        )

        # ── 7. Network View Model ─────────────────────────────────────────────
        net_lat = f"{net.latency_ms:.0f}ms" if net.latency_ms is not None else "-"
        network_vm = NetworkViewModel(
            status_label=net.connectivity.value,
            endpoint_label=net.endpoint or "api.nvidia.com",
            latency_label=net_lat,
            is_reconnecting=net.reconnecting,
            is_healthy=(net.connectivity == NetworkConnectivity.CONNECTED),
        )

        # ── 8. Permission View Model ──────────────────────────────────────────
        permission_vm = PermissionViewModel(
            has_pending_request=(perm.status == PermissionStatus.REQUESTED),
            action_summary=perm.action or "No action pending",
            risk_badge=perm.risk,
            request_id=perm.permission_request_id,
        )

        return HermesViewModelBundle(
            mission=mission_vm,
            progress=progress_vm,
            tasks=tasks_vm,
            active_task=active_task_vm,
            model=model_vm,
            tool=tool_vm,
            verification=verification_vm,
            network=network_vm,
            permission=permission_vm,
        )

    @classmethod
    def _derive_progress_headline(cls, state: HermesRuntimeState) -> str:
        """Derive explicit, informative 'Why Waiting?' progress text."""
        reason = state.progress.waiting_reason
        if reason == WaitReason.WAITING_FOR_MODEL:
            m = state.model_execution.model or "model"
            if state.model_execution.status == ModelStatus.STREAMING:
                return f"Generating response from {m}..."
            return f"Waiting for model {m}..."
        elif reason == WaitReason.WAITING_FOR_TOOL:
            t = state.tool_execution.tool_name or "tool"
            return f"Executing {t}..."
        elif reason == WaitReason.WAITING_FOR_VERIFICATION:
            return "Running structural verification..."
        elif reason == WaitReason.WAITING_FOR_PERMISSION:
            return "Waiting for user permission approval..."
        elif reason == WaitReason.WAITING_FOR_NETWORK:
            if state.network.reconnecting:
                return f"Reconnecting to provider endpoint (attempt {state.network.retry_count})..."
            return "Waiting for network connectivity..."
        elif reason == WaitReason.WAITING_FOR_USER:
            return "Waiting for user input..."
        elif reason == WaitReason.REPAIRING:
            return "Running automated repair loop..."
        elif reason == WaitReason.COMPLETED:
            return "Mission completed successfully"
        elif reason == WaitReason.FAILED:
            return f"Mission failed: {state.mission.abort_reason or 'Unknown error'}"
        elif reason == WaitReason.CANCELLED:
            return "Mission cancelled"
        elif reason == WaitReason.WORKING:
            if state.current_task:
                return f"Working on {state.current_task.title}"
            return "Working..."
        return "Idle"
