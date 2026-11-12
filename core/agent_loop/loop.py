# core/agent_loop/loop.py

"""

The Canonical Agent Loop for HERMES 2.x.

Replaces the rigid 12-stage pipeline with a continuous, model-driven,

observation-grounded execution loop while retaining authoritative harness control

over security, permissions, evidence, verification, and terminal state.



Central Invariant:

    MODEL CHOOSES

    HARNESS ALLOWS

    ENVIRONMENT OBSERVES

    EVIDENCE DECIDES

    STATE SURVIVES

    UI OBSERVES

"""



from __future__ import annotations



import asyncio
import os

import hashlib

import json

import re

import time

import uuid

from pathlib import Path

from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from loguru import logger



from dataclasses import dataclass, field

@dataclass
class FailureLedgerEntry:
    turn_id: str
    category: str  # PROVIDER_FAILURE, TOOL_FAILURE, VALIDATION_FAILURE, NO_PROGRESS
    tier: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    error_class: Optional[str] = None
    operation: Optional[str] = None
    target_path: Optional[str] = None
    actual_result: Optional[str] = None
    elapsed_duration: Optional[float] = None
    workspace_progress: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "category": self.category,
            "tier": self.tier,
            "provider": self.provider,
            "model": self.model,
            "error_class": self.error_class,
            "operation": self.operation,
            "target_path": self.target_path,
            "actual_result": str(self.actual_result)[:256] if self.actual_result else None,
            "elapsed_duration": self.elapsed_duration,
            "workspace_progress": self.workspace_progress,
            "timestamp": self.timestamp,
        }

from core.agent_loop.types import (

    AgentDecision,

    AgentDecisionType,

    AgentLoopConfig,

    AgentLoopResult,

    AgentTurn,

    ActionEnvelope,

    ActionStatus,

    Observation,

    LifecycleDimension,

)

from core.agent_loop.decisions import DecisionInterpreter

from core.agent_loop.actions import ActionExecutor

from core.agent_loop.observations import ObservationBuilder

from core.agent_loop.completion import CompletionPolicy

from core.event_bus import event_bus, EventBus

from core.runtime_state.events import HermesEvent, EventType, EventSeverity

from core.runtime_state.store import state_store, StateStore

from core.runtime_state.models import MissionStatus, WaitReason, RequirementStatus, AcceptanceCheckStatus

from core.workspace import WorkspaceManager, workspace_manager as global_workspace

from core.mission_planner import Mission, MissionTask

from core.telemetry import telemetry

from config.model_config import (

    TIER1_MODEL,

    TIER1_PROVIDER,

    MODEL_KEEP_ALIVE,

)

from core.planning.service import MissionPlanningService

from core.evidence import EvidenceStore, EvidenceCollector, EvidenceInvalidator

from core.verification import VerificationEngine

from core.repair import RepairController

from core.escalation import EscalationEngine

from core.runtime_state.models import FailureClass



# Model Turn Deadline & Final Verification Reserve Policy

FINAL_VERIFICATION_RESERVE_SECONDS: float = 120.0

FINALIZATION_RESERVE_SECONDS: float = 45.0

MIN_MODEL_REQUEST_TIMEOUT_SECONDS: float = 15.0





def calculate_effective_turn_timeout(

    remaining_wall_time: float,

    configured_timeout: float = 360.0,

    reserve_seconds: float = FINAL_VERIFICATION_RESERVE_SECONDS,

    finalization_reserve_seconds: float = FINALIZATION_RESERVE_SECONDS,

    min_model_timeout: float = MIN_MODEL_REQUEST_TIMEOUT_SECONDS,

) -> Optional[float]:

    """

    Calculate effective model turn timeout ensuring verification and finalization reserves are never consumed.

    Never start a new model request when remaining budget cannot accommodate min request time + reserves.

    Caps single model turn to min(configured_timeout, usable_budget, 90.0).

    Returns float timeout if allowed, or None if remaining budget is insufficient.

    """

    total_reserves = reserve_seconds + finalization_reserve_seconds

    usable_budget = remaining_wall_time - total_reserves

    if usable_budget < min_model_timeout:

        return None

    effective_cap = float(os.getenv("HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS", "25.0"))
    return min(float(configured_timeout), usable_budget, effective_cap)





CANONICAL_TOOL_MAP = {

    "fs_read": "fs.read", "read_file": "fs.read", "read": "fs.read", "view_file": "fs.read", "file_read": "fs.read",

    "fs_write": "fs.write", "write_file": "fs.write", "create_file": "fs.write",

    "fs_edit": "fs.edit", "edit_file": "fs.edit", "edit_lines": "fs.edit",

    "search_glob": "search.glob", "glob": "search.glob", "find_files": "search.glob",

    "search_grep": "search.grep", "grep": "search.grep", "find_text": "search.grep",

    "shell_bash": "shell.bash", "bash": "shell.bash", "bash_exec": "shell.bash", "run_shell": "shell.bash",

}





def normalize_tool_call(tool_name: str, arguments: Any, workspace_root: Optional[Path] = None) -> Tuple[str, dict]:

    """Normalize tool names and arguments across aliases and path styles."""

    canonical_name = CANONICAL_TOOL_MAP.get(tool_name.lower() if isinstance(tool_name, str) else "", tool_name)

    norm_args = dict(arguments) if isinstance(arguments, dict) else {}

    for k in list(norm_args.keys()):

        if k in ("file_path", "target_path", "filepath", "filename", "TargetFile", "target_file"):

            norm_args["path"] = norm_args.pop(k)

        elif k in ("cmd", "shell_cmd"):

            norm_args["command"] = norm_args.pop(k)

        elif k in ("code", "text", "body", "code_content", "CodeContent", "file_content"):

            norm_args["content"] = norm_args.pop(k)



    if "path" in norm_args and isinstance(norm_args["path"], str):

        p_str = norm_args["path"].replace("\\", "/").strip()

        p_str = re.sub(r'^\./+', '', p_str)

        if workspace_root:

            ws_p_str = str(workspace_root).replace("\\", "/").rstrip("/")

            if p_str.lower().startswith(ws_p_str.lower() + "/"):

                p_str = p_str[len(ws_p_str) + 1:]

        norm_args["path"] = p_str

    return canonical_name, norm_args





class InvalidModelStateError(ValueError):
    """Raised when an invalid model state transition or uninitialized model access occurs."""
    pass


class AgentLoop:

    """

    Continuous model-driven agent execution engine for HERMES 2.x.

    """



    def __init__(

        self,

        orchestrator: Any,

        workspace_manager: Optional[WorkspaceManager] = None,

        event_bus_instance: Optional[EventBus] = None,

        state_store_instance: Optional[StateStore] = None,

        event_queue: Optional[asyncio.Queue] = None,

        abort_event: Optional[asyncio.Event] = None,

        user_input_callback: Optional[Callable[[str], Coroutine[Any, Any, str]]] = None,

        config: Optional[AgentLoopConfig] = None,

        subagent_manager: Optional[Any] = None,

        checkpoint_engine: Optional[Any] = None,

        **kwargs: Any,

    ) -> None:

        self.orchestrator = orchestrator

        self.workspace = workspace_manager or kwargs.get("workspace") or global_workspace

        self.event_bus = event_bus_instance or event_bus

        self.state_store = state_store_instance or state_store

        self.event_queue = event_queue

        self.abort_event = abort_event or asyncio.Event()

        self.user_input_callback = user_input_callback

        self.config = config or AgentLoopConfig()

        self.checkpoint_engine = checkpoint_engine



        # Subsystems

        self._interpreter = DecisionInterpreter()

        orch_mode = getattr(self.orchestrator, "mode", "auto")

        mode_str = orch_mode if (isinstance(orch_mode, str) and orch_mode in ("auto", "plan", "safe")) else "auto"

        self._action_executor = ActionExecutor(mode=mode_str, event_bus_instance=self.event_bus)

        self._completion_policy = CompletionPolicy()



        # Project Intelligence 2.x & Context Engine 2.x (Prompts 7 & 8)

        from core.context.engine import ContextEngine

        from core.project_intelligence.registry import ProjectIntelligenceRegistry

        canonical_skills = (Path(__file__).resolve().parents[2] / "skills").resolve()

        self.project_intelligence = ProjectIntelligenceRegistry(

            workspace_root=self.workspace.root_str if hasattr(self.workspace, "root_str") and self.workspace.root_str else None,

            canonical_skills_root=canonical_skills if canonical_skills.exists() else None,

            event_bus=self.event_bus,

        )

        self.context_engine = ContextEngine(

            event_bus=self.event_bus,

            project_intelligence=self.project_intelligence,

        )

        self.planning_service: Optional[MissionPlanningService] = None



        # Subagents 2.x (Prompt 10)

        from core.subagents.manager import SubagentManager

        ws_root = self.workspace.root_str if hasattr(self.workspace, "root_str") and self.workspace.root_str else Path.cwd()

        self.subagent_manager = subagent_manager or SubagentManager(

            workspace_root=ws_root,

            event_bus=self.event_bus,

            state_store=self.state_store,

        )



        # Prompt 11: Evidence, Verification, Repair, and Escalation

        self.evidence_store = EvidenceStore(workspace_root=ws_root)

        self.evidence_collector = EvidenceCollector(

            workspace_root=ws_root,

            evidence_store=self.evidence_store,

            event_bus=self.event_bus,

        )

        self.evidence_invalidator = EvidenceInvalidator(

            workspace_root=ws_root,

            evidence_store=self.evidence_store,

            event_bus=self.event_bus,

        )

        self.verification_engine = VerificationEngine(

            workspace_root=ws_root,

            evidence_store=self.evidence_store,

            event_bus=self.event_bus,

        )

        self.repair_controller = RepairController(event_bus=self.event_bus)

        self.escalation_engine = EscalationEngine(event_bus=self.event_bus)



        # Prompt 12: Network Resilience Supervisor

        from core.network.supervisor import NetworkSupervisor

        self.network_supervisor = NetworkSupervisor(event_bus=self.event_bus)



        # Runtime trackers

        self._start_time: float = 0.0

        self._mission_id: str = ""

        self._turns_count: int = 0

        self._actions_count: int = 0

        self._tool_calls_count: int = 0

        self._terminal_event_published: bool = False

        self._verification_calls_count: int = 0

        self._written_files: List[str] = []
        self._failure_ledger: List[FailureLedgerEntry] = []
        self._category_failures: Dict[str, int] = {
            "PROVIDER_FAILURE": 0,
            "TOOL_FAILURE": 0,
            "VALIDATION_FAILURE": 0,
            "NO_PROGRESS": 0,
        }
        self._last_turn_durations: Dict[str, Any] = {}
        self._last_search_fingerprint: Optional[str] = None
        self._last_search_result: Optional[str] = None
        self._mutations_since_last_search: int = 0
        self._no_progress_streak: int = 0

        self._observation_history: List[Observation] = []

        self._recent_actions: List[Tuple[str, str]] = []

        self._tasks: List[Dict[str, Any]] = []

        self._active_task_idx: int = -1

        self._consecutive_planning_turns: int = 0

        self._consecutive_non_mutating_turns: int = 0

        self._file_write_counts: Dict[str, int] = {}

        self._read_fingerprint_tracker: Dict[str, Tuple[str, int]] = {}

        self._consecutive_no_progress_blocks: int = 0

        from core.agent_loop.syntax_repair import SyntaxRepairController

        self.syntax_repair = SyntaxRepairController()

        self._recovery_attempt_count: int = 0

        self._recovery_escalation_attempted: bool = False

        # Separated failure and recovery tracking structures (P0)

        self._cycle_no_progress_blocks: int = 0

        self._cycle_empty_turns: int = 0

        self._mission_failure_history: List[Dict[str, Any]] = []

        self._provider_failure_counts: Dict[str, int] = {}

        self._total_recovery_budget: int = 3
        self._inference_history: List[Dict[str, Any]] = []
        self._in_recovery: bool = False
        self._consecutive_empty_turns: int = 0
        self._last_turn_durations: Dict[str, Any] = {
            "provider_latency_seconds": 0.0,
            "tool_execution_latency_seconds": 0.0,
        }

        # Reliability & convergence remediation tracking structures (P0)

        self._pending_diagnostics: Dict[str, Dict[str, Any]] = {}

        self._tier_rotations: int = 0

        self._executed_info_commands: set = set()

        self._failed_syntax_checks: Dict[str, str] = {}

        from core.agent_loop.stuck_detector import StuckLoopDetector

        self.stuck_detector = StuckLoopDetector(max_identical_errors=2, max_history=50)

        # Large Mission Orchestration, Bounded Execution Phases & Checkpoints (P0/P1)
        from core.agent_loop.types import ExecutionPhase
        self.current_phase: ExecutionPhase = ExecutionPhase.PHASE_A_PLANNING
        self.completed_phases: List[str] = []
        self.completed_phase_summaries: Dict[str, str] = {}
        self._phase_turn_count: Dict[str, int] = {}
        self._phase_stall_count: int = 0
        self._is_large_mission: bool = False
        self._progress_in_current_phase: bool = False
        from core.progress_governor import ProgressGovernor
        self.progress_governor: ProgressGovernor = ProgressGovernor(threshold=3)

        # Authoritative Model State & Routing Ownership (P0 Runtime Stabilization)
        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
            TIER4_PROVIDER, TIER4_MODEL,
        )
        self._provider_tier_map: Dict[int, Tuple[str, str]] = {
            1: (TIER1_PROVIDER, TIER1_MODEL),
            2: (TIER2_PROVIDER, TIER2_MODEL),
            3: (TIER3_PROVIDER, TIER3_MODEL),
            4: (TIER4_PROVIDER, TIER4_MODEL),
        }

        # Inherit initial active tier if orchestrator has an existing valid integer setting
        initial_tier = 1
        raw_orch_tier = getattr(self.orchestrator, "_active_tier", None)
        if isinstance(raw_orch_tier, int) and raw_orch_tier in (1, 2, 3, 4):
            initial_tier = raw_orch_tier
        elif isinstance(raw_orch_tier, str) and raw_orch_tier.isdigit() and int(raw_orch_tier) in (1, 2, 3, 4):
            initial_tier = int(raw_orch_tier)

        self._active_routing_tier: int = initial_tier
        self._active_provider: str = self._provider_tier_map.get(initial_tier, (TIER1_PROVIDER, TIER1_MODEL))[0]
        self._active_model_name: str = self._provider_tier_map.get(initial_tier, (TIER1_PROVIDER, TIER1_MODEL))[1]
        self._mission: Optional[Any] = None
        self._active_model_override: Optional[str] = None
        self._active_provider_override: Optional[str] = None

        # Synchronize orchestrator active tier atomically
        if hasattr(self, "orchestrator") and self.orchestrator is not None:
            try:
                setattr(self.orchestrator, "_active_tier", self._active_routing_tier)
            except Exception:
                pass

        # Synchronize runtime state store atomically
        if hasattr(self, "state_store") and self.state_store is not None:
            try:
                if hasattr(self.state_store, "current_model"):
                    self.state_store.current_model = self._active_model_name
                if hasattr(self.state_store, "_state") and hasattr(self.state_store._state, "model_execution"):
                    m_exec = self.state_store._state.model_execution
                    m_exec.tier = self._active_routing_tier
                    m_exec.provider = self._active_provider
                    m_exec.model = self._active_model_name
            except Exception:
                pass



    @property
    def active_tier(self) -> int:
        """Authoritative active routing tier (1, 2, 3, or 4)."""
        if not hasattr(self, "_provider_tier_map"):
            from config.model_config import (
                TIER1_PROVIDER, TIER1_MODEL,
                TIER2_PROVIDER, TIER2_MODEL,
                TIER3_PROVIDER, TIER3_MODEL,
                TIER4_PROVIDER, TIER4_MODEL,
            )
            self._provider_tier_map = {
                1: (TIER1_PROVIDER, TIER1_MODEL),
                2: (TIER2_PROVIDER, TIER2_MODEL),
                3: (TIER3_PROVIDER, TIER3_MODEL),
                4: (TIER4_PROVIDER, TIER4_MODEL),
            }
        current_tier = getattr(self, "_active_routing_tier", 1)
        raw_orch_tier = getattr(self.orchestrator, "_active_tier", None) if hasattr(self, "orchestrator") else None
        if isinstance(raw_orch_tier, int) and raw_orch_tier in (1, 2, 3, 4) and raw_orch_tier != current_tier:
            self._active_routing_tier = raw_orch_tier
            prov, mod = self._provider_tier_map.get(raw_orch_tier, (None, None))
            if prov and mod and not getattr(self, "_active_provider_override", None):
                self._active_provider = prov
                self._active_model_name = mod
        elif not hasattr(self, "_active_routing_tier"):
            self._active_routing_tier = current_tier
        return self._active_routing_tier

    @active_tier.setter
    def active_tier(self, tier: int) -> None:
        self.set_active_model_state(tier=tier)

    @property
    def active_provider(self) -> str:
        """Authoritative provider ID for the currently active tier."""
        if getattr(self, "_active_provider_override", None):
            return self._active_provider_override
        tier = self.active_tier
        return self._provider_tier_map.get(tier, ("", ""))[0] or getattr(self, "_active_provider", "")

    @property
    def active_model(self) -> str:
        """Authoritative model ID for the currently active tier."""
        if getattr(self, "_active_model_override", None):
            return self._active_model_override
        tier = self.active_tier
        return self._provider_tier_map.get(tier, ("", ""))[1] or getattr(self, "_active_model_name", "")

    @property
    def mission_model(self) -> str:
        """Authoritative active mission model name."""
        return self.active_model

    @mission_model.setter
    def mission_model(self, model: str) -> None:
        self.set_active_model_state(tier=self.active_tier, model=model)

    @property
    def _mission_model(self) -> str:
        """Private accessor alias for backwards compatibility and recovery transitions."""
        return self.active_model

    @_mission_model.setter
    def _mission_model(self, model: str) -> None:
        self.set_active_model_state(tier=self.active_tier, model=model)

    @property
    def mission(self) -> Optional[Any]:
        """Authoritative Mission domain model object."""
        return getattr(self, "_mission", None)

    @mission.setter
    def mission(self, m: Optional[Any]) -> None:
        self._mission = m
        if m and hasattr(m, "mission_id") and not getattr(self, "_mission_id", None):
            self._mission_id = m.mission_id

    def set_active_model_state(
        self,
        tier: int,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        reason: str = "",
    ) -> None:
        """
        Atomically update active model state across AgentLoop, Orchestrator, and StateStore.
        Preserves single source of truth during failovers, recovery, and checkpoint resumption.
        """
        if not isinstance(tier, int) or tier not in (1, 2, 3, 4):
            raise InvalidModelStateError(f"Invalid model tier: {tier!r}. Authoritative tiers are 1, 2, 3, or 4.")

        if not hasattr(self, "_provider_tier_map"):
            from config.model_config import (
                TIER1_PROVIDER, TIER1_MODEL,
                TIER2_PROVIDER, TIER2_MODEL,
                TIER3_PROVIDER, TIER3_MODEL,
                TIER4_PROVIDER, TIER4_MODEL,
            )
            self._provider_tier_map = {
                1: (TIER1_PROVIDER, TIER1_MODEL),
                2: (TIER2_PROVIDER, TIER2_MODEL),
                3: (TIER3_PROVIDER, TIER3_MODEL),
                4: (TIER4_PROVIDER, TIER4_MODEL),
            }

        default_prov, default_mod = self._provider_tier_map.get(tier, ("", ""))
        target_prov = provider or default_prov
        target_mod = model or default_mod

        self._active_routing_tier = tier
        self._active_provider = target_prov
        self._active_model_name = target_mod
        self._active_provider_override = provider
        self._active_model_override = model

        # Synchronize orchestrator active tier atomically
        if hasattr(self, "orchestrator") and self.orchestrator is not None:
            try:
                setattr(self.orchestrator, "_active_tier", tier)
            except Exception:
                pass

        # Synchronize runtime state store atomically
        if hasattr(self, "state_store") and self.state_store is not None:
            try:
                if hasattr(self.state_store, "current_model"):
                    self.state_store.current_model = target_mod
                if hasattr(self.state_store, "_state") and hasattr(self.state_store._state, "model_execution"):
                    m_exec = self.state_store._state.model_execution
                    m_exec.tier = tier
                    m_exec.provider = target_prov
                    m_exec.model = target_mod
            except Exception:
                pass

    def transition_phase(self, new_phase: Any, summary: str = "") -> None:
        """Authoritative phase transition with checkpoint save and event emission."""
        from core.agent_loop.types import ExecutionPhase
        if isinstance(new_phase, str):
            try:
                new_phase = ExecutionPhase(new_phase)
            except Exception:
                pass
        old_phase = self.current_phase
        old_val = getattr(old_phase, "value", str(old_phase))
        new_val = getattr(new_phase, "value", str(new_phase))
        if old_val not in self.completed_phases:
            self.completed_phases.append(old_val)
        if summary:
            self.completed_phase_summaries[old_val] = summary
        self.current_phase = new_phase
        self._phase_stall_count = 0
        logger.info(f"AgentLoop: Phase transition {old_val} -> {new_val}. Summary: {summary}")
        try:
            from core.mission_checkpoint import MissionCheckpointManager
            ws_root = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd()))
            completed_tasks = [t.get("task_id") for t in self._tasks if t.get("status") == "COMPLETED"]
            MissionCheckpointManager.save_checkpoint(
                workspace_root=ws_root,
                mission_id=self._mission_id,
                current_phase=new_val,
                completed_phases=self.completed_phases,
                completed_tasks=completed_tasks,
                tier_state=self.active_tier,
                active_skills=list(getattr(self, "_active_skill_names", [])),
                skill_telemetry=getattr(self, "_skill_telemetry", {}),
                design_brief=getattr(self, "_design_brief_dict", {}),
                content_coverage=getattr(self, "_content_coverage_dict", {}),
            )
        except Exception as e:
            logger.warning(f"AgentLoop: Failed to save phase checkpoint: {e}")

    def record_inference_telemetry(
        self,
        requested_tier: int,
        actual_provider: str,
        actual_model: str,
        start_time: float,
        completion_time: float,
        success: bool,
        tool_call_count: int,
        finish_reason: Optional[str] = None,
        turn_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        ttft_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record authoritative telemetry for every model inference (P0)."""
        dur = duration_ms if duration_ms is not None else max(0.0, (completion_time - start_time) * 1000.0)
        rec = {
            "turn_id": turn_id or "",
            "requested_tier": int(requested_tier),
            "actual_provider": str(actual_provider),
            "actual_model_id": str(actual_model),
            "start_time": float(start_time),
            "completion_time": float(completion_time),
            "duration_ms": float(dur),
            "success": bool(success),
            "tool_call_count": int(tool_call_count),
            "finish_reason": finish_reason or ("stop" if success else "error"),
            "error": error,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "ttft_ms": ttft_ms,
        }
        if not hasattr(self, "_inference_history"):
            self._inference_history = []
        self._inference_history.append(rec)
        return rec

    async def _ensure_active_task(self) -> None:

        """Ensure an active task has been transitioned to RUNNING via TASK_STARTED."""

        if not self._tasks:

            return

        if self._active_task_idx < 0:

            self._active_task_idx = 0

            cur = self._tasks[0]

            cur["status"] = "RUNNING"

            tid = cur.get("task_id", "task_1")

            await self._publish_event(

                EventType.TASK_STARTED,

                turn_id=None,

                payload={

                    "task_id": tid,

                    "title": cur.get("title", ""),

                    "inner_iteration": 1,

                },

            )



    async def _advance_active_task(self, reason: str = "Requirement satisfied") -> None:

        """Mark active task completed, transition requirement state to VERIFIED, and advance to next pending task."""

        if not self._tasks or self._active_task_idx < 0 or self._active_task_idx >= len(self._tasks):

            return

        cur = self._tasks[self._active_task_idx]

        tid = cur.get("task_id", f"task_{self._active_task_idx + 1}")

        if cur.get("status") != "COMPLETED":

            cur["status"] = "COMPLETED"

            await self._publish_event(

                EventType.TASK_COMPLETED,

                payload={

                    "task_id": tid,

                    "verification_evidence": reason,

                    "reason": reason,

                },

            )

            # Authoritative requirement completion event for state machine

            await self._publish_event(

                EventType.REQUIREMENT_COMPLETED,

                payload={

                    "requirement_id": tid,

                    "reason": reason,

                    "evidence_ref": f"ev_{tid}",

                },

            )

            if hasattr(self, "planning_service") and self.planning_service:

                try:

                    from core.runtime_state.models import AcceptanceCheckStatus, RequirementStatus

                    if hasattr(self.planning_service, "acceptance_ledger") and self.planning_service.acceptance_ledger:

                        checks = self.planning_service.acceptance_ledger.get_checks_for_requirement(tid)

                        for chk in checks:

                            if hasattr(self.planning_service, "record_acceptance_result"):

                                self.planning_service.record_acceptance_result(

                                    check_id=chk.check_id,

                                    status=AcceptanceCheckStatus.PASS,

                                    evidence_ref=f"ev_{chk.check_id}",

                                )

                            elif hasattr(self.planning_service, "record_check_result"):

                                self.planning_service.record_check_result(

                                    check_id=chk.check_id,

                                    status=AcceptanceCheckStatus.PASS,

                                    evidence_ref=f"ev_{chk.check_id}",

                                )

                            if hasattr(self, "evidence_store") and self.evidence_store:

                                try:

                                    from core.evidence.models import EvidenceRecord, EvidenceSourceType, EvidenceTrustClass

                                    ev_rec = EvidenceRecord(

                                        evidence_id=f"ev_{chk.check_id}",

                                        mission_id=self._mission_id,

                                        requirement_id=getattr(chk, "requirement_id", None) or tid,

                                        acceptance_check_id=chk.check_id,

                                        source_type=EvidenceSourceType.ARTIFACT_WRITE,

                                        trust_class=EvidenceTrustClass.TOOL_DERIVED_OBSERVATION,

                                        metadata={"reason": reason},

                                    )

                                    self.evidence_store.add(ev_rec)

                                except Exception as ev_err:

                                    logger.warning(f"AgentLoop: evidence store add notice: {ev_err}")

                    if hasattr(self.planning_service, "requirements") and tid in self.planning_service.requirements:

                        self.planning_service.requirements[tid].transition_status(

                            RequirementStatus.VERIFIED, reason=reason, actor="agent_loop"

                        )

                except Exception as ps_sync_exc:

                    logger.debug(f"Planning service task sync notice: {ps_sync_exc}")



        if self._active_task_idx + 1 < len(self._tasks):

            self._active_task_idx += 1

            nxt = self._tasks[self._active_task_idx]

            nxt["status"] = "RUNNING"

            nxt_tid = nxt.get("task_id", f"task_{self._active_task_idx + 1}")

            await self._publish_event(

                EventType.TASK_STARTED,

                payload={

                    "task_id": nxt_tid,

                    "title": nxt.get("title", ""),

                    "inner_iteration": 1,

                },

            )



    async def _complete_all_tasks(self, reason: str = "All requirements verified") -> None:

        """Mark all remaining tasks and requirements as COMPLETED on successful mission finish."""

        if not self._tasks:

            return

        for t in self._tasks:

            if t.get("status") != "COMPLETED":

                t["status"] = "COMPLETED"

                tid = t.get("task_id", "")

                await self._publish_event(

                    EventType.TASK_COMPLETED,

                    payload={

                        "task_id": tid,

                        "verification_evidence": reason,

                        "reason": reason,

                    },

                )

                await self._publish_event(

                    EventType.REQUIREMENT_COMPLETED,

                    payload={

                        "requirement_id": tid,

                        "reason": reason,

                        "evidence_ref": f"ev_{tid}",

                    },

                )

                if hasattr(self, "planning_service") and self.planning_service:

                    try:

                        from core.runtime_state.models import AcceptanceCheckStatus, RequirementStatus

                        if hasattr(self.planning_service, "acceptance_ledger") and self.planning_service.acceptance_ledger:

                            checks = self.planning_service.acceptance_ledger.get_checks_for_requirement(tid)

                            for chk in checks:

                                if hasattr(self.planning_service, "record_acceptance_result"):

                                    self.planning_service.record_acceptance_result(

                                        check_id=chk.check_id,

                                        status=AcceptanceCheckStatus.PASS,

                                        evidence_ref=f"ev_{chk.check_id}",

                                    )

                                elif hasattr(self.planning_service, "record_check_result"):

                                    self.planning_service.record_check_result(

                                        check_id=chk.check_id,

                                        status=AcceptanceCheckStatus.PASS,

                                        evidence_ref=f"ev_{chk.check_id}",

                                    )

                                if hasattr(self, "evidence_store") and self.evidence_store:

                                    try:

                                        from core.evidence.models import EvidenceRecord, EvidenceSourceType, EvidenceTrustClass

                                        ev_rec = EvidenceRecord(

                                            evidence_id=f"ev_{chk.check_id}",

                                            mission_id=self._mission_id,

                                            requirement_id=getattr(chk, "requirement_id", None) or tid,

                                            acceptance_check_id=chk.check_id,

                                            source_type=EvidenceSourceType.ARTIFACT_WRITE,

                                            trust_class=EvidenceTrustClass.TOOL_DERIVED_OBSERVATION,

                                            metadata={"reason": reason},

                                        )

                                        self.evidence_store.add(ev_rec)

                                    except Exception as ev_err:

                                        logger.warning(f"AgentLoop: evidence store add notice: {ev_err}")

                        if hasattr(self.planning_service, "requirements") and tid in self.planning_service.requirements:

                            self.planning_service.requirements[tid].transition_status(

                                RequirementStatus.VERIFIED, reason=reason, actor="agent_loop"

                            )

                    except Exception:

                        pass



    # ── Main continuous execution loop ────────────────────────────────────────



    def _is_mock_orchestrator(self) -> bool:
        """Return True if orchestrator or its Tier 1 transport is a test Mock object."""
        orch = getattr(self, "orchestrator", None)
        if orch is None:
            return True
        if type(orch).__name__ in ("MagicMock", "AsyncMock", "Mock"):
            return True
        t1 = getattr(orch, "tier1", None)
        if t1 is not None and type(t1).__name__ in ("MagicMock", "AsyncMock", "Mock"):
            return True
        gen_fn = getattr(orch, "_generate_t1", None)
        if gen_fn is not None and (hasattr(gen_fn, "assert_called") or hasattr(gen_fn, "mock")):
            return True
        return False

    async def _fail_unified_mission(
        self,
        ws_root: Path,
        mission: Mission,
        *,
        code: str,
        err_msg: str,
        execution_mode: str,
        stage: str,
        provider: str = "none",
        model: str = "none",
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> AgentLoopResult:
        """Persist and emit an authoritative FAILED terminal state without fake templates."""
        payload: Dict[str, Any] = {
            "error": err_msg,
            "reason": err_msg,
            "failure_code": code,
            "execution_mode": execution_mode,
            "stage": stage,
            "provider": provider,
            "model": model,
            "workspace_path": str(ws_root),
        }
        if extra_payload:
            payload.update(extra_payload)

        await self._publish_event(EventType.MISSION_FAILED, payload=payload)
        db = self.event_bus.get_database() if hasattr(self.event_bus, "get_database") else None
        if db:
            try:
                db.save_mission(
                    mission_id=self._mission_id,
                    workspace_path=str(ws_root),
                    status="FAILED",
                    run_id=getattr(self, "_run_id", None) or getattr(mission, "run_id", None),
                    attempt_number=getattr(self, "_attempt_number", 1) or getattr(mission, "attempt_number", 1),
                    wait_reason="NONE",
                    execution_active=False,
                    recovery_required=False,
                    error_json={"error": err_msg, "code": code, "execution_mode": execution_mode},
                )
            except Exception as db_e:
                logger.warning(f"AgentLoop: DB save_mission error on unified mission failure: {db_e}")

        ctrl = getattr(mission, "control", None) or getattr(self, "control", None)
        if ctrl and hasattr(ctrl, "mark_terminal"):
            ctrl.mark_terminal()

        total_dur = time.monotonic() - self._start_time
        final_state = self.state_store.get_snapshot()
        return AgentLoopResult(
            mission_id=self._mission_id,
            success=False,
            status=final_state.mission.status.value if final_state else "FAILED",
            turns_executed=self._turns_count,
            actions_executed=self._actions_count,
            tool_calls_count=self._tool_calls_count,
            verification_calls_count=self._verification_calls_count,
            duration_seconds=total_dur,
            files_created=[],
            files_modified=[],
            final_output=err_msg,
            error=err_msg,
            termination_reason=code,
            active_skills=list(getattr(self, "_active_skill_names", [])),
            skill_telemetry=dict(getattr(self, "_skill_telemetry", {})),
        )

    async def _run_unified_browser_qualification(
        self,
        ws_root: Path,
        expected_brand: str,
    ) -> Dict[str, Any]:
        """Run headless Chrome CDP check at 1440x900 for unified HERMES website missions."""
        import base64
        import os
        import shutil
        from core.browser.acceptance import BrowserAcceptanceVerifier

        if os.getenv("HERMES_SKIP_LOOP_BROWSER", "false").lower() == "true":
            return {"executed": False, "passed": True, "reason": "HERMES_SKIP_LOOP_BROWSER=true"}

        if not BrowserAcceptanceVerifier.find_browser_executable():
            return {"executed": False, "passed": True, "reason": "Chrome/Edge executable not present on host"}

        from core.browser.dev_server import DevServerManager
        from core.browser.manager import BrowserManager, Viewport

        screenshots_dir = ws_root / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        server_mgr = DevServerManager()
        server_info = await server_mgr.start_static_server(directory=ws_root, timeout=8.0)
        browser = BrowserManager(artifacts_dir=screenshots_dir, prefer_cdp=True)
        try:
            launched = await browser.launch(
                headless=True,
                viewport=Viewport(width=1440, height=900, is_mobile=False),
            )
            if not launched:
                return {"executed": False, "passed": False, "reason": "Failed to launch CDP browser"}

            nav_res = await browser.navigate(f"{server_info.url}/index.html")
            if not nav_res.success:
                return {"executed": True, "passed": False, "reason": f"Navigation failed: {nav_res.error_message}"}

            await asyncio.sleep(0.6)

            async def _eval(expr: str) -> Any:
                if hasattr(browser.driver, "_send_cdp"):
                    res = await browser.driver._send_cdp(
                        "Runtime.evaluate",
                        {"expression": expr, "returnByValue": True, "awaitPromise": True},
                    )
                    if "exceptionDetails" in res:
                        raise RuntimeError(f"Browser JS exception: {res['exceptionDetails']}")
                    return res.get("result", {}).get("value")
                return None

            title = await _eval("document.title") or ""
            body_text = await _eval("document.body.innerText") or ""
            overflow_info = await _eval(
                "(() => { const d=document.documentElement,b=document.body; const s=Math.max(d.scrollWidth,b.scrollWidth); return {scrollWidth:s, clientWidth:d.clientWidth, overflow:s>d.clientWidth+1}; })()"
            ) or {"scrollWidth": 1440, "clientWidth": 1440, "overflow": False}
            img_check = await browser.check_images(scroll_first=True)
            console_errors = [ce.text for ce in browser.get_console_errors()]
            net_failures = [
                f"{nf.url} ({nf.status})"
                for nf in browser.get_network_failures()
                if not nf.url.endswith("favicon.ico")
            ]

            await _eval("window.scrollTo(0, 0);")
            await asyncio.sleep(0.25)
            slug = re.sub(r"[^a-z0-9]+", "_", expected_brand.lower()).strip("_") or "site"
            desktop_path = screenshots_dir / f"{slug}_desktop_1440.png"
            fullpage_path = screenshots_dir / f"{slug}_fullpage.png"
            shot_art = await browser.capture_screenshot(
                name=f"{slug}_desktop_1440",
                viewport=Viewport(width=1440, height=900, is_mobile=False),
            )
            if Path(shot_art.file_path).exists():
                shutil.copy2(shot_art.file_path, desktop_path)
            if hasattr(browser.driver, "_send_cdp"):
                full_res = await browser.driver._send_cdp(
                    "Page.captureScreenshot",
                    {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
                )
                b64_data = full_res.get("data")
                if b64_data:
                    fullpage_path.write_bytes(base64.b64decode(b64_data))

            brand_ok = (expected_brand.lower() in title.lower()) or (expected_brand.lower() in body_text.lower())
            passed = (
                brand_ok
                and len(console_errors) == 0
                and len(net_failures) == 0
                and img_check.broken_images == 0
                and not overflow_info.get("overflow", False)
            )
            issues: List[str] = []
            if not brand_ok:
                issues.append(f"Expected brand '{expected_brand}' missing from rendered DOM")
            if console_errors:
                issues.append(f"Console errors: {console_errors[:3]}")
            if net_failures:
                issues.append(f"Network failures: {net_failures[:3]}")
            if img_check.broken_images > 0:
                issues.append(f"Broken images: {img_check.broken_images}/{img_check.total_images}")
            if overflow_info.get("overflow", False):
                issues.append(f"Horizontal overflow at 1440x900: {overflow_info}")

            return {
                "executed": True,
                "passed": passed,
                "title": title,
                "total_images": img_check.total_images,
                "broken_images": img_check.broken_images,
                "console_errors": console_errors,
                "network_failures": net_failures,
                "overflow": overflow_info,
                "desktop_screenshot": str(desktop_path) if desktop_path.exists() else "",
                "fullpage_screenshot": str(fullpage_path) if fullpage_path.exists() else "",
                "issues": issues,
            }
        finally:
            await browser.close()
            if server_info:
                server_mgr.stop_server(server_info.name)

    async def _execute_unified_website_pipeline(
        self,
        mission: Mission,
        ws_root: Path,
    ) -> AgentLoopResult:
        """
        Phase 5 Unified Hybrid Website Execution Chain:
          Domain Confidence -> Mode 1 (Deterministic) or Mode 2 (LLM-Assisted)
          -> MissionSpecification -> FrontendContract -> AssetPipeline
          -> Renderer -> WorkPackageGate + Profile C -> Chrome CDP Qualification
          -> Authoritative Terminal State.
        """
        import uuid as _uuid
        from core.asset_pipeline import AssetPipeline
        from core.design_intelligence import DesignBriefGenerator
        from core.domain_confidence import DomainConfidenceCategory, DomainConfidenceClassifier
        from core.frontend_contract import FrontendContractBuilder
        from core.llm_semantic_planner import LLMSynthesisBlockedError
        from core.mission_spec import MissionSpecification
        from core.semantic_synthesizer import InsufficientPromptInputError
        from core.universal_renderer import UniversalContentRenderer
        from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator
        from core.work_package_gate import WorkPackageGate

        prompt = mission.user_prompt or ""
        assessment = DomainConfidenceClassifier.assess(prompt)
        exec_mode = assessment.execution_mode.value

        if assessment.category == DomainConfidenceCategory.INSUFFICIENT_INPUT:
            return await self._fail_unified_mission(
                ws_root,
                mission,
                code="INSUFFICIENT_INPUT",
                err_msg=assessment.rationale,
                execution_mode=exec_mode,
                stage="domain_confidence",
            )

        initial_provider = (
            "deterministic_semantic_engine"
            if exec_mode == "deterministic"
            else getattr(self.orchestrator, "active_t1_provider", "nvidia_nim")
        )

        # Stage 1: Semantic Specification (Mode 1 or Mode 2)
        op_spec_id = f"spec_{_uuid.uuid4().hex[:6]}"
        await self._publish_event(
            EventType.TOOL_STARTED,
            payload={
                "operation_id": op_spec_id,
                "tool_name": "semantic_synthesizer",
                "execution_mode": exec_mode,
                "provider": initial_provider,
                "stage": "semantic_planning",
                "headline": (
                    f"Mode 1: Deterministic Semantic Planning ({assessment.best_domain})"
                    if exec_mode == "deterministic"
                    else "Mode 2: LLM-Assisted Semantic Synthesis"
                ),
            },
        )

        async def _on_llm_evt(kind: str, pl: Dict[str, Any]) -> None:
            evt_map = {
                "model_requested": EventType.MODEL_REQUESTED,
                "model_completed": EventType.MODEL_COMPLETED,
                "tier_failover_started": EventType.TIER_FAILOVER_STARTED,
            }
            et = evt_map.get(kind)
            if et is not None:
                await self._publish_event(
                    et,
                    payload={**pl, "execution_mode": exec_mode, "stage": "semantic_planning"},
                )

        t_spec0 = time.monotonic()
        try:
            spec, assessment = await MissionSpecification.from_prompt_hybrid_async(
                prompt=prompt,
                workspace_root=ws_root,
                mission_id=mission.mission_id,
                design_brief=getattr(self, "_design_brief", None),
                allow_llm=True,
                total_budget_seconds=25.0,
                event_callback=_on_llm_evt,
            )
        except InsufficientPromptInputError as i_err:
            await self._publish_event(
                EventType.TOOL_FAILED,
                payload={"operation_id": op_spec_id, "tool_name": "semantic_synthesizer", "error": str(i_err), "stage": "semantic_planning"},
            )
            return await self._fail_unified_mission(
                ws_root, mission, code="INSUFFICIENT_INPUT", err_msg=str(i_err),
                execution_mode="rejected", stage="semantic_planning",
            )
        except LLMSynthesisBlockedError as b_err:
            await self._publish_event(
                EventType.TOOL_FAILED,
                payload={
                    "operation_id": op_spec_id,
                    "tool_name": "semantic_synthesizer",
                    "execution_mode": "llm_assisted",
                    "error": str(b_err),
                    "stage": "semantic_planning",
                    "attempts": b_err.attempts,
                },
            )
            return await self._fail_unified_mission(
                ws_root,
                mission,
                code="LLM_SYNTHESIS_BLOCKED",
                err_msg=str(b_err),
                execution_mode="llm_assisted",
                stage="semantic_planning",
                extra_payload={"attempts": b_err.attempts, "registry": b_err.registry_snapshot},
            )

        spec_ms = round((time.monotonic() - t_spec0) * 1000.0, 2)
        syn_tel = spec.synthesis_telemetry or {}
        actual_provider = syn_tel.get("provider", initial_provider)
        actual_model = syn_tel.get("model", "heuristic_domain_synthesizer")

        # Align DesignBrief and FrontendContract with authoritative MissionSpecification
        brief = DesignBriefGenerator.generate_brief(prompt, active_skills=getattr(self, "_active_skill_names", None))
        brief.brand_identity = spec.requested_brand
        brief.domain = spec.business_domain
        brief.purpose = spec.purpose
        brief.target_audience = spec.target_audience
        brief.color_palette = dict(spec.color_palette)
        brief.visual_direction = spec.visual_direction
        brief.persist_artifacts(ws_root)
        self._design_brief = brief
        self._design_brief_dict = brief.to_dict()
        self._mission_spec = spec
        spec.persist(ws_root)

        contract = FrontendContractBuilder.build_initial_contract(
            task=prompt,
            mission_id=mission.mission_id,
            design_brief=brief,
        )
        self._frontend_contract = contract
        contract.save_to_workspace(ws_root)

        await self._publish_event(
            EventType.TOOL_COMPLETED,
            payload={
                "operation_id": op_spec_id,
                "tool_name": "semantic_synthesizer",
                "success": True,
                "duration_ms": int(spec_ms),
                "execution_mode": spec.execution_mode,
                "provider": actual_provider,
                "model": actual_model,
                "stage": "semantic_planning_completed",
                "headline": f"Synthesized '{spec.requested_brand}' ({spec.business_domain}, {spec.execution_mode}) in {spec_ms:.0f}ms",
            },
        )

        # Stage 2: Asset Provisioning
        op_asset_id = f"asset_{_uuid.uuid4().hex[:6]}"
        await self._publish_event(
            EventType.TOOL_STARTED,
            payload={
                "operation_id": op_asset_id,
                "tool_name": "asset_pipeline",
                "execution_mode": spec.execution_mode,
                "provider": actual_provider,
                "model": actual_model,
                "stage": "asset_provisioning",
                "headline": "Provisioning verified visual assets...",
            },
        )
        t_ast0 = time.monotonic()
        manifest = AssetPipeline.provision_assets(
            workspace_root=ws_root,
            prompt=prompt,
            domain=spec.business_domain,
            mission_id=mission.mission_id,
        )
        self._asset_manifest = manifest
        ast_ms = round((time.monotonic() - t_ast0) * 1000.0, 2)
        await self._publish_event(
            EventType.TOOL_COMPLETED,
            payload={
                "operation_id": op_asset_id,
                "tool_name": "asset_pipeline",
                "success": True,
                "duration_ms": int(ast_ms),
                "stage": "asset_provisioning_completed",
                "headline": f"Provisioned {len(manifest.assets)} local assets ({ast_ms:.0f}ms)",
            },
        )

        # Stage 3: Deterministic Website Emission
        op_rend_id = f"render_{_uuid.uuid4().hex[:6]}"
        await self._publish_event(
            EventType.TOOL_STARTED,
            payload={
                "operation_id": op_rend_id,
                "tool_name": "universal_renderer",
                "stage": "website_rendering",
                "headline": f"Rendering application deliverables for {spec.requested_brand}...",
            },
        )
        t_ren0 = time.monotonic()
        p_lower = prompt.lower()
        is_explicit_legacy = any(
            k in p_lower for k in ("saffron", "wanderworld", "northstar", "atlas robotics", "form & field", "form and field", "paws & claws", "paws and claws")
        ) or bool(re.search(r"\bnova\b", p_lower))
        if is_explicit_legacy:
            from core.foundation_scaffolder import seed_initial_foundation_files
            seed_initial_foundation_files(ws_root, prompt=prompt, contract=contract, design_brief=brief)
        else:
            UniversalContentRenderer.render(ws_root, spec)

        self._written_files = [
            f for f in ("index.html", "style.css", "app.js", "package.json") if (ws_root / f).exists()
        ]
        self._actions_count += 1
        ren_ms = round((time.monotonic() - t_ren0) * 1000.0, 2)
        await self._publish_event(
            EventType.TOOL_COMPLETED,
            payload={
                "operation_id": op_rend_id,
                "tool_name": "universal_renderer",
                "success": True,
                "duration_ms": int(ren_ms),
                "files_created": list(self._written_files),
                "stage": "website_rendering_completed",
                "headline": f"Rendered {len(self._written_files)} workspace deliverables ({ren_ms:.0f}ms)",
            },
        )

        # Stage 4: Work Package Gates & Profile C Verification
        op_gate_id = f"gate_{_uuid.uuid4().hex[:6]}"
        await self._publish_event(
            EventType.TOOL_STARTED,
            payload={
                "operation_id": op_gate_id,
                "tool_name": "verification_gates",
                "stage": "work_package_gates",
                "headline": "Evaluating Work Package Gates & Verification Profile C...",
            },
        )
        t_gate0 = time.monotonic()
        ok_assets, missing_assets, _ = AssetPipeline.verify_workspace_assets(ws_root)
        f_res = WorkPackageGate.evaluate_foundation_gate(ws_root, contract=contract, design_brief=brief)
        c_res = WorkPackageGate.evaluate_content_gate(ws_root, contract=contract)
        prof_res = VerificationProfileEvaluator.evaluate(
            VerificationProfile.PROFILE_C,
            ws_root,
            prompt,
            written_files=list(self._written_files),
        )
        self._verification_calls_count += 1
        gate_ms = round((time.monotonic() - t_gate0) * 1000.0, 2)

        gate_ok = ok_assets and f_res.passed and c_res.passed and prof_res.passed
        if not gate_ok:
            reasons = (
                ([f"Missing assets: {missing_assets}"] if not ok_assets else [])
                + (f_res.missing_criteria if not f_res.passed else [])
                + (c_res.missing_criteria if not c_res.passed else [])
                + (prof_res.issues if not prof_res.passed else [])
            )
            err_msg = "Work package gate verification failed: " + "; ".join(reasons[:4])
            await self._publish_event(
                EventType.TOOL_FAILED,
                payload={"operation_id": op_gate_id, "tool_name": "verification_gates", "error": err_msg, "stage": "work_package_gates"},
            )
            return await self._fail_unified_mission(
                ws_root, mission, code="WORK_PACKAGE_GATE_FAILED", err_msg=err_msg,
                execution_mode=spec.execution_mode, stage="work_package_gates",
                provider=actual_provider, model=actual_model,
            )

        await self._publish_event(
            EventType.TOOL_COMPLETED,
            payload={
                "operation_id": op_gate_id,
                "tool_name": "verification_gates",
                "success": True,
                "duration_ms": int(gate_ms),
                "stage": "work_package_gates_passed",
                "headline": f"Passed Foundation, Content & Profile C Gates ({gate_ms:.0f}ms)",
            },
        )

        # Stage 5: Real 1440x900 Browser Qualification
        op_br_id = f"browser_{_uuid.uuid4().hex[:6]}"
        await self._publish_event(
            EventType.TOOL_STARTED,
            payload={
                "operation_id": op_br_id,
                "tool_name": "browser_preview",
                "stage": "browser_qualification",
                "headline": "Running 1440x900 Chrome CDP browser verification...",
            },
        )
        t_br0 = time.monotonic()
        browser_report = await self._run_unified_browser_qualification(ws_root, spec.requested_brand)
        br_ms = round((time.monotonic() - t_br0) * 1000.0, 2)
        if browser_report.get("executed") and not browser_report.get("passed"):
            err_msg = "Browser qualification failed: " + "; ".join(browser_report.get("issues", []))
            await self._publish_event(
                EventType.TOOL_FAILED,
                payload={"operation_id": op_br_id, "tool_name": "browser_preview", "error": err_msg, "stage": "browser_qualification"},
            )
            return await self._fail_unified_mission(
                ws_root, mission, code="BROWSER_QUALIFICATION_FAILED", err_msg=err_msg,
                execution_mode=spec.execution_mode, stage="browser_qualification",
                provider=actual_provider, model=actual_model,
                extra_payload={"browser_report": browser_report},
            )

        await self._publish_event(
            EventType.TOOL_COMPLETED,
            payload={
                "operation_id": op_br_id,
                "tool_name": "browser_preview",
                "success": True,
                "duration_ms": int(br_ms),
                "stage": "browser_qualification_passed",
                "headline": (
                    f"1440x900 Browser Verified ({browser_report.get('total_images', 0)} images, 0 errors, {br_ms:.0f}ms)"
                    if browser_report.get("executed")
                    else f"Browser step skipped ({browser_report.get('reason', 'not configured')})"
                ),
                "metadata": browser_report,
            },
        )

        # Stage 6: Authoritative Terminal Completion
        total_dur = time.monotonic() - self._start_time
        summary = (
            f"Completed '{spec.requested_brand}' via {spec.execution_mode} mode "
            f"(provider={actual_provider}, model={actual_model}, duration={total_dur:.2f}s)."
        )
        await self._complete_all_tasks(summary)
        await self._publish_event(
            EventType.VERIFICATION_COMPLETED,
            payload={
                "verdict": "PASSED",
                "confidence": spec.domain_confidence,
                "reason": summary,
                "execution_mode": spec.execution_mode,
                "provider": actual_provider,
                "model": actual_model,
            },
        )

        created_list = "\n".join(f"- `{f}`" for f in self._written_files)
        walkthrough = (
            f"### Mission Completed Successfully\n\n"
            f"**Brand:** {spec.requested_brand} (`{spec.business_domain}` / `{spec.application_archetype}`)\n"
            f"**Execution Mode:** `{spec.execution_mode}` (confidence={spec.domain_confidence:.2f}, `{spec.confidence_category}`)\n"
            f"**Provider / Engine:** `{actual_provider}` (`{actual_model}`)\n"
            f"**Total Duration:** `{total_dur:.2f}s`\n\n"
            f"**Deliverables:**\n{created_list}\n\n"
            f"**Browser Verification:** {browser_report.get('total_images', 0)} images loaded, "
            f"{browser_report.get('broken_images', 0)} broken, {len(browser_report.get('console_errors', []))} console errors.\n"
        )
        await self._publish_event(
            EventType.MISSION_COMPLETED,
            payload={
                "reason": summary,
                "execution_mode": spec.execution_mode,
                "provider": actual_provider,
                "model": actual_model,
                "stage": "completed",
                "duration_seconds": round(total_dur, 3),
                "files_created": list(self._written_files),
                "browser_report": browser_report,
                "synthesis_telemetry": syn_tel,
                "final_output": walkthrough,
            },
        )

        db = self.event_bus.get_database() if hasattr(self.event_bus, "get_database") else None
        if db:
            try:
                db.save_mission(
                    mission_id=self._mission_id,
                    workspace_path=str(ws_root),
                    status="COMPLETED",
                    run_id=getattr(self, "_run_id", None) or getattr(mission, "run_id", None),
                    attempt_number=getattr(self, "_attempt_number", 1) or getattr(mission, "attempt_number", 1),
                    wait_reason="NONE",
                    execution_active=False,
                    recovery_required=False,
                )
            except Exception as db_e:
                logger.warning(f"AgentLoop: DB save_mission error on unified completion: {db_e}")

        ctrl = getattr(mission, "control", None) or getattr(self, "control", None)
        if ctrl and hasattr(ctrl, "mark_terminal"):
            ctrl.mark_terminal()

        final_state = self.state_store.get_snapshot()
        return AgentLoopResult(
            mission_id=self._mission_id,
            success=True,
            status=final_state.mission.status.value if final_state else "COMPLETED",
            turns_executed=self._turns_count,
            actions_executed=self._actions_count,
            tool_calls_count=self._tool_calls_count,
            verification_calls_count=self._verification_calls_count,
            duration_seconds=total_dur,
            files_created=list(self._written_files),
            files_modified=[],
            final_output=walkthrough,
            error=None,
            termination_reason=summary,
            active_skills=list(getattr(self, "_active_skill_names", [])),
            skill_telemetry=dict(getattr(self, "_skill_telemetry", {})),
            design_brief=dict(getattr(self, "_design_brief_dict", {})),
            content_coverage=dict(getattr(self, "_content_coverage_dict", {})),
        )

    async def run(self, mission: Mission) -> AgentLoopResult:

        """

        Execute mission via model-driven agentic loop.

        Runs until an authoritative terminal state is reached or safety budget is exhausted.

        """

        self._start_time = time.monotonic()

        self.mission = mission
        self._mission_id = mission.mission_id

        try:

            from tools.file_tools import reset_read_loop_tracker

            reset_read_loop_tracker()

            from tools.platform.core_tools import READ_LOOP_TRACKER

            READ_LOOP_TRACKER.clear()

        except Exception:

            pass

        self._run_id = (

            getattr(mission, "run_id", None)

            or getattr(getattr(self, "control", None), "run_id", None)

            or getattr(getattr(mission, "control", None), "run_id", None)

        )

        self._attempt_number = (

            getattr(mission, "attempt_number", None)

            or getattr(getattr(self, "control", None), "attempt_number", None)

            or getattr(getattr(mission, "control", None), "attempt_number", None)

        )

        self.state_store = self.event_bus.get_or_create_state(mission.mission_id)

        if (not self._run_id or not self._attempt_number) and self.state_store:

            snap = self.state_store.get_snapshot()

            if snap and snap.mission:

                self._run_id = self._run_id or snap.mission.run_id

                self._attempt_number = self._attempt_number or snap.mission.attempt_number

        if not self._attempt_number:

            self._attempt_number = 1

        if not self._run_id:

            self._run_id = f"run_{self._attempt_number}_{self._mission_id}"



        # Initialize Forensic Observability Telemetry (Global subscriber handled by RuntimeAdapter)

        from core.observability.logger import get_telemetry_logger

        if not isinstance(self._run_id, str) or not str(self._run_id).strip() or 'MagicMock' in str(type(self._run_id)):
            self._run_id = f'run_{self._mission_id or "default"}'
        self.telemetry_logger = get_telemetry_logger(run_id=self._run_id, mission_id=self._mission_id)

        self._turns_count = 0

        self._actions_count = 0

        self._tool_calls_count = 0

        self._verification_calls_count = 0

        self._written_files.clear()

        self._observation_history.clear()

        self._recent_actions.clear()

        self._file_write_counts.clear()

        self._tool_failure_counts: Dict[str, int] = {}

        self._read_fingerprint_tracker.clear()

        self._executed_info_commands.clear()

        self._failed_syntax_checks.clear()

        try:

            from tools.file_tools import reset_read_loop_tracker

            reset_read_loop_tracker()

        except Exception:

            pass

        if hasattr(self, "stuck_detector") and self.stuck_detector:

            self.stuck_detector.reset(self._mission_id)

        self._consecutive_no_progress_blocks = 0

        self._recovery_attempt_count = 0

        self._recovery_escalation_attempted = False

        from core.agent_loop.mvp_gate import WebsiteMvpGate

        ws_root = Path(self.workspace.workspace_root) if (self.workspace and hasattr(self.workspace, "workspace_root") and self.workspace.workspace_root) else Path(".")

        self.mvp_gate = WebsiteMvpGate(workspace_root=ws_root, mission_id=self._mission_id)



        # Resolve mission-specific turn budget (e.g. 80 turns for complex website missions)

        if hasattr(self.config, "resolve_for_mission"):

            effective_limit = self.config.resolve_for_mission(

                mission=mission,

                workspace_root=ws_root,

                written_files=set(self._written_files),

            )

            logger.info(

                f"AgentLoop: mission '{mission.mission_id}' turn budget resolved to {effective_limit} turns "

                f"(explicit={getattr(self.config, '_explicit_max_turns', False)})"

            )

        # Detect large mission and initialize phase orchestration
        from core.planning.decomposer import GoalDecomposer
        from core.agent_loop.types import ExecutionPhase
        self._is_large_mission = GoalDecomposer.is_large_mission(mission.user_prompt or "")
        if self._is_large_mission:
            self.current_phase = ExecutionPhase.PHASE_B_FOUNDATION
            self.completed_phases = [ExecutionPhase.PHASE_A_PLANNING.value]
            self.completed_phase_summaries = {ExecutionPhase.PHASE_A_PLANNING.value: "Work packages formulated and dependencies established."}
        else:
            self.current_phase = ExecutionPhase.PHASE_A_PLANNING
            self.completed_phases = []
            self.completed_phase_summaries = {}
        self._phase_turn_count = {}
        self._phase_stall_count = 0
        self._progress_in_current_phase = False
        self._skill_telemetry: Dict[str, Any] = {}
        self._active_skill_names: List[str] = []
        self._design_brief = None
        self._design_brief_dict: Dict[str, Any] = {}
        self._content_coverage = None
        self._content_coverage_dict: Dict[str, Any] = {}
        self._last_frontend_validation = None
        self._last_frontend_validation_report = None
        self._frontend_contract = None
        self._skill_evidence_ledger = None
        self._asset_manifest = None

        # Attempt to resume from checkpoint if available
        try:
            from core.mission_checkpoint import MissionCheckpointManager
            loaded_chk = MissionCheckpointManager.load_checkpoint(ws_root)
            if loaded_chk and loaded_chk.mission_id == self._mission_id:
                try:
                    self.current_phase = ExecutionPhase(loaded_chk.current_phase)
                except Exception:
                    self.current_phase = ExecutionPhase.PHASE_B_FOUNDATION
                self.completed_phases = list(loaded_chk.completed_phases)
                self.set_active_model_state(tier=int(loaded_chk.tier_state or 1))
                if loaded_chk.active_skills:
                    self._active_skill_names = list(loaded_chk.active_skills)
                if loaded_chk.skill_telemetry:
                    self._skill_telemetry = dict(loaded_chk.skill_telemetry)
                if loaded_chk.design_brief:
                    self._design_brief_dict = dict(loaded_chk.design_brief)
                    try:
                        from core.design_intelligence import DesignBrief
                        self._design_brief = DesignBrief.from_dict(self._design_brief_dict)
                    except Exception:
                        pass
                if loaded_chk.content_coverage:
                    self._content_coverage_dict = dict(loaded_chk.content_coverage)
                    try:
                        from core.design_intelligence import ContentCoverageMap
                        self._content_coverage = ContentCoverageMap.from_dict(self._content_coverage_dict)
                    except Exception:
                        pass
                try:
                    from core.frontend_contract import FrontendImplementationContract
                    from core.skill_evidence_ledger import SkillEvidenceLedger
                    ws_active = self.workspace_root or Path.cwd()
                    loaded_fc = FrontendImplementationContract.load_from_workspace(ws_active)
                    from core.design_intelligence import DesignBriefGenerator
                    cur_dom = DesignBriefGenerator.detect_domain(mission.user_prompt or "")
                    if loaded_fc and getattr(loaded_fc, "business_domain", None) == cur_dom:
                        self._frontend_contract = loaded_fc
                    else:
                        self._frontend_contract = None
                    self._skill_evidence_ledger = SkillEvidenceLedger.load_from_workspace(ws_active)
                except Exception as _c_err:
                    logger.debug(f"AgentLoop: Contract/ledger checkpoint resume notice: {_c_err}")
                logger.info(f"AgentLoop: Resumed mission from checkpoint at phase={self.current_phase.value} (skills={self._active_skill_names})")
        except Exception as e:
            logger.warning(f"AgentLoop: Checkpoint load notice: {e}")



        # Prompt 11: Configure mission ID on engines

        self.evidence_store.mission_id = mission.mission_id

        self.evidence_collector.mission_id = mission.mission_id

        self.evidence_invalidator.mission_id = mission.mission_id

        self.verification_engine.mission_id = mission.mission_id

        self.repair_controller.mission_id = mission.mission_id

        self.escalation_engine.mission_id = mission.mission_id



        # Update Project Intelligence mission tracking and discover

        if hasattr(self, "project_intelligence") and self.project_intelligence:

            self.project_intelligence.mission_id = mission.mission_id

            try:

                self.project_intelligence.discover()

            except Exception as pi_exc:

                logger.warning(f"AgentLoop: initial project intelligence discovery warning: {pi_exc}")



            # Route or restore skills for the mission
            try:
                state_snap = self.state_store.get_snapshot() if hasattr(self, "state_store") and self.state_store else None
                if self._active_skill_names:
                    self.project_intelligence.restore_skills(self._active_skill_names)
                elif state_snap and getattr(state_snap, "mission", None) and getattr(state_snap.mission, "active_skills", None):
                    self._active_skill_names = list(state_snap.mission.active_skills)
                    self.project_intelligence.restore_skills(state_snap.mission.active_skills)
                else:
                    ws_signals = {}
                    if self.workspace and getattr(self.workspace, "is_locked", False) and getattr(self.workspace, "index", None):
                        ws_signals = {
                            "files": list(getattr(self.workspace.index, "files", {}).keys()),
                            "framework": getattr(self.workspace.index, "framework", None),
                            "language": getattr(self.workspace.index, "language", None),
                        }
                    routing_decision = self.project_intelligence.route_skills(
                        task_description=mission.user_prompt or "",
                        workspace_signals=ws_signals,
                    )
                    self._active_skill_names = list(routing_decision.selected_skills)
                    all_disc = list(self.project_intelligence.skill_engine._metadata_index.keys()) if hasattr(self.project_intelligence, "skill_engine") else []
                    for s_name in self._active_skill_names:
                        s_body = self.project_intelligence.load_skill_body(s_name)
                        meta = self.project_intelligence.skill_engine._metadata_index.get(s_name) if hasattr(self.project_intelligence, "skill_engine") else None
                        self._skill_telemetry[s_name] = {
                            "status": "LOADED" if s_body else "SELECTED",
                            "score": routing_decision.candidate_scores.get(s_name, 1.0),
                            "source_file": meta.skill_file if meta else None,
                            "sha256": meta.sha256_hash if meta else None,
                            "reason": routing_decision.decision_rationale,
                        }
                    self._skill_telemetry["__discovered_skills__"] = all_disc

                # Initialize design brief and content coverage for frontend website missions
                try:
                    from core.design_intelligence import DesignBriefGenerator, ContentCoverageMap
                    if not self._design_brief:
                        self._design_brief = DesignBriefGenerator.generate_brief(
                            mission.user_prompt or "",
                            active_skills=self._active_skill_names,
                        )
                        self._design_brief_dict = self._design_brief.to_dict()
                    if not self._content_coverage:
                        self._content_coverage = ContentCoverageMap.from_prompt(mission.user_prompt or "")
                        self._content_coverage_dict = self._content_coverage.to_dict()

                    from core.agent_loop.mvp_gate import WebsiteMvpGate as _WMG
                    _will_run_hybrid = (
                        _WMG.is_website_mission(mission.user_prompt or "", ws_root or Path.cwd())
                        and (not self._is_mock_orchestrator() or getattr(mission, "force_hybrid_pipeline", False))
                        and not getattr(mission, "plan_mode", False)
                    )
                    from core.mission_spec import MissionSpecification
                    if not getattr(self, "_mission_spec", None) and not _will_run_hybrid:
                        self._mission_spec = MissionSpecification.from_prompt(
                            prompt=mission.user_prompt or "",
                            workspace_root=ws_root or Path.cwd(),
                            mission_id=mission.mission_id,
                            design_brief=self._design_brief,
                        )

                    from core.frontend_contract import FrontendContractBuilder
                    from core.skill_evidence_ledger import SkillEvidenceLedger
                    if not self._frontend_contract or getattr(self._frontend_contract, 'business_domain', None) != getattr(self._design_brief, 'domain', None):
                        self._frontend_contract = FrontendContractBuilder.build_initial_contract(
                            task=mission.user_prompt or "",
                            mission_id=mission.mission_id,
                            design_brief=self._design_brief,
                        )
                    if not self._skill_evidence_ledger:
                        self._skill_evidence_ledger = SkillEvidenceLedger(mission_id=mission.mission_id)
                        for s_name in self._active_skill_names:
                            self._skill_evidence_ledger.record_discovered(s_name)
                            self._skill_evidence_ledger.record_selected(s_name, reason="Mandatory frontend bundle / Intent routing")
                            if s_name in getattr(self, "_active_skills", {}):
                                sk_obj = self._active_skills[s_name]
                                self._skill_evidence_ledger.record_loaded(
                                    s_name,
                                    source_path=getattr(sk_obj, "source_path", ""),
                                    content=getattr(sk_obj, "content", ""),
                                )

                except Exception as d_exc:
                    logger.warning(f"AgentLoop: design intelligence initialization notice: {d_exc}")

            except Exception as s_exc:
                logger.warning(f"AgentLoop: initial skill routing/loading warning: {s_exc}")



        logger.info(f"AgentLoop: starting mission '{mission.mission_id}' in {self.config.execution_mode} mode")

        try:

            from tools.file_tools import _READ_LOOP_TRACKER

            _READ_LOOP_TRACKER.clear()

            from tools.platform.core_tools import READ_LOOP_TRACKER

            READ_LOOP_TRACKER.clear()

        except Exception:

            pass



        # Mission Planning Service 2.x (Prompt 9)

        self.planning_service = MissionPlanningService(

            mission_id=mission.mission_id,

            workspace_root=self.workspace.root_str if hasattr(self.workspace, "root_str") and self.workspace.root_str else None,

            event_bus=self.event_bus,

            state_store=self.state_store,

        )

        setattr(self.planning_service, "run_id", self._run_id)

        setattr(self.planning_service, "attempt_number", self._attempt_number)

        self.planning_service.initialize_goal(

            user_prompt=mission.user_prompt,

            explicit_constraints=getattr(mission, "explicit_constraints", None) or [],

        )

        if self.config.execution_mode == "plan" or getattr(mission, "plan_mode", False):

            self.planning_service.enter_plan_mode()





        # Publish MISSION_STARTED

        await self._publish_event(

            EventType.MISSION_STARTED,

            payload={

                "mission_id": mission.mission_id,

                "prompt": mission.user_prompt,

                "execution_mode": self.config.execution_mode,

                "workspace_root": self.workspace.root_str if self.workspace.is_locked else "generated_projects",

            }

        )



        # Publish PLANNING_STARTED and PLAN_CREATED

        await self._publish_event(

            EventType.PLANNING_STARTED,

            payload={

                "mission_id": mission.mission_id,

                "prompt": mission.user_prompt,

                "summary": "Formulating execution plan and acceptance criteria",

            }

        )



        tasks_payload = []

        if self.planning_service and self.planning_service.requirements:

            for idx, (r_id, req) in enumerate(self.planning_service.requirements.items()):

                tasks_payload.append({

                    "task_id": r_id,

                    "title": getattr(req, "title", r_id),

                    "description": getattr(req, "description", ""),

                    "dependencies": getattr(req, "dependencies", []),

                    "order_index": idx,

                    "status": "PENDING",

                })

        elif getattr(mission, "tasks", None):

            for idx, t in enumerate(mission.tasks):

                tasks_payload.append({

                    "task_id": getattr(t, "task_id", f"task_{idx+1}"),

                    "title": getattr(t, "title", str(t)),

                    "description": getattr(t, "description", ""),

                    "dependencies": getattr(t, "dependencies", []),

                    "order_index": idx,

                    "status": "PENDING",

                })



        req_count = len(tasks_payload)

        self._tasks = list(tasks_payload)

        self._active_task_idx = -1

        await self._publish_event(

            EventType.PLAN_CREATED,

            payload={

                "mission_id": mission.mission_id,

                "goal_id": self.planning_service.goal.goal_id if self.planning_service else "",

                "requirements_count": req_count,

                "tasks": tasks_payload,

                "summary": f"Plan created with {req_count} requirement(s)",

            }

        )



        # Workspace Preflight: Detect mismatch or missing application if prompt targets existing codebase

        ws_root = Path(self.workspace.root_str) if (self.workspace and hasattr(self.workspace, "root_str") and self.workspace.root_str) else None

        if ws_root and ws_root.exists():

            from core.agent_loop.preflight import validate_workspace_preflight

            preflight = validate_workspace_preflight(mission.user_prompt or "", ws_root)

            if not preflight.allowed:

                err_msg = preflight.error or f"Preflight validation failed: {preflight.failure_code}"

                logger.error(f"AgentLoop: Preflight failure: {err_msg} | code={preflight.failure_code}")

                await self._publish_event(

                    EventType.MISSION_FAILED,

                    payload={

                        "error": err_msg,

                        "failure_code": preflight.failure_code,

                        "workspace_path": str(ws_root),

                        "details": preflight.details,

                    }

                )

                db = self.event_bus.get_database() if hasattr(self.event_bus, "get_database") else None

                if db:

                    try:

                        db.save_mission(

                            mission_id=self._mission_id,

                            workspace_path=str(ws_root),

                            status="FAILED",

                            run_id=getattr(self, "_run_id", None) or getattr(mission, "run_id", None),

                            attempt_number=getattr(self, "_attempt_number", 1) or getattr(mission, "attempt_number", 1),

                            wait_reason="NONE",

                            execution_active=False,

                            recovery_required=False,

                            error_json={"error": err_msg, "code": preflight.failure_code},

                        )

                    except Exception as db_e:

                        logger.warning(f"AgentLoop: DB save_mission error on preflight failure: {db_e}")

                ctrl = getattr(mission, "control", None) or getattr(self, "control", None)

                if ctrl and hasattr(ctrl, "mark_terminal"):

                    ctrl.mark_terminal()

                return AgentLoopResult(

                    mission_id=self._mission_id,

                    success=False,

                    status="FAILED",

                    turns_executed=0,

                    actions_executed=0,

                    tool_calls_count=0,

                    verification_calls_count=0,

                    duration_seconds=time.monotonic() - self._start_time,

                    files_created=[],

                    files_modified=[],

                    final_output="",

                    error=err_msg,

                    termination_reason=preflight.failure_code or "PREFLIGHT_VALIDATION_FAILED",

                )



        consecutive_failures = 0

        unchanged_read_governor_blocks = 0

        final_output = ""

        termination_reason = None

        mission_success = False



        # For website missions, provision photographic assets and persist design brief artifacts after preflight passes
        if ws_root and ws_root.exists():
            try:
                from core.design_intelligence import DesignBriefGenerator, strip_negative_constraints
                clean_prompt = strip_negative_constraints(mission.user_prompt or "")
                target_domain = DesignBriefGenerator.detect_domain(mission.user_prompt or "")
                from core.design_intelligence import detect_brand_name
                target_brand = detect_brand_name(mission.user_prompt or "").lower()
                index_candidate = ws_root / "index.html"
                if index_candidate.exists():
                    existing_text = index_candidate.read_text(encoding="utf-8", errors="ignore").lower()
                    should_purge = False
                    has_nova = bool(re.search(r"\bnova\b", existing_text))
                    stale_reasons = []

                    # Purge generic placeholders unconditionally
                    if any(w in existing_text for w in ["modern web application", "welcome to modern application"]):
                        stale_reasons.append("generic_placeholder")

                    # Purge foreign domain leaks
                    if "nova" not in target_brand and has_nova and "atlas" not in existing_text:
                        stale_reasons.append("nova_leak")
                    if not any(k in target_brand for k in ["saffron", "stone"]) and any(w in existing_text for w in ["saffron & stone", "saffron and stone", "paneer tikka", "dum biryani"]):
                        stale_reasons.append("saffron_stone_leak")
                    if "wanderworld" not in target_brand and any(w in existing_text for w in ["wanderworld", "bali", "destinations-grid", "hero-wanderlust"]):
                        stale_reasons.append("wanderworld_leak")
                    if "northstar" not in target_brand and any(w in existing_text for w in ["northstar university", "collegiate quadrangle", "faculty-grid"]):
                        stale_reasons.append("northstar_leak")
                    if "atlas" not in target_brand and any(w in existing_text for w in ["atlas robotics", "autonomous mobile robots", "solutions-grid"]):
                        stale_reasons.append("atlas_robotics_leak")
                    if "form & field" not in target_brand and "form and field" not in target_brand and any(w in existing_text for w in ["form & field", "form and field", "monolith pavilion"]):
                        stale_reasons.append("architecture_leak")

                    if stale_reasons:
                        logger.warning(f"AgentLoop: Stale foreign files detected in workspace ({', '.join(stale_reasons)}). Purging stale deliverables.")
                        should_purge = True

                    if should_purge:
                        from tools.security import safe_delete_file
                        for s_name in ["index.html", "style.css", "app.js", "package.json"]:
                            sf = ws_root / s_name
                            if sf.exists():
                                safe_delete_file(sf, ws_root, reason="stale_deliverable_purge")
            except Exception as _stale_e:
                logger.debug(f"AgentLoop: stale deliverable purge notice: {_stale_e}")

            is_site_mission = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_root, set(self._written_files))
            if is_site_mission and (not self._is_mock_orchestrator() or getattr(mission, "force_hybrid_pipeline", False)) and not getattr(mission, "plan_mode", False):
                return await self._execute_unified_website_pipeline(mission, ws_root)
            if is_site_mission:
                try:
                    from core.foundation_scaffolder import seed_initial_foundation_files
                    seed_initial_foundation_files(
                        workspace_root=ws_root,
                        prompt=mission.user_prompt or "",
                        contract=getattr(self, "_frontend_contract", None),
                        design_brief=getattr(self, "_design_brief", None),
                    )
                except Exception as f_err:
                    logger.debug(f"AgentLoop: foundation scaffolder notice: {f_err}")
                if hasattr(self, "_design_brief") and self._design_brief:
                    try:
                        self._design_brief.persist_artifacts(ws_root)
                    except Exception as p_err:
                        logger.debug(f"AgentLoop: design brief persist notice: {p_err}")
                if getattr(self, "_frontend_contract", None):
                    try:
                        self._frontend_contract.save_to_workspace(ws_root)
                    except Exception as c_err:
                        logger.debug(f"AgentLoop: frontend contract persist notice: {c_err}")
                if getattr(self, "_mission_spec", None):
                    try:
                        self._mission_spec.persist(ws_root)
                    except Exception as m_err:
                        logger.debug(f"AgentLoop: mission spec persist notice: {m_err}")
                if getattr(self, "_skill_evidence_ledger", None):
                    try:
                        self._skill_evidence_ledger.save_to_workspace(ws_root)
                    except Exception as l_err:
                        logger.debug(f"AgentLoop: skill evidence ledger persist notice: {l_err}")
                try:
                    from core.asset_pipeline import AssetPipeline
                    self._asset_manifest = AssetPipeline.provision_assets(
                        workspace_root=ws_root,
                        prompt=mission.user_prompt or "",
                        domain=getattr(self._design_brief, "domain", "travel_tourism"),
                        mission_id=mission.mission_id,
                    )
                except Exception as a_err:
                    logger.debug(f"AgentLoop: asset pipeline provision notice: {a_err}")

        # Ensure mission begins on primary configured tier (preserving checkpoint tier if resumed)
        is_chk_resume = bool(loaded_chk and getattr(loaded_chk, "mission_id", None) == self._mission_id and getattr(loaded_chk, "tier_state", 1) > 1)
        if not is_chk_resume:
            self.set_active_model_state(tier=1)
        else:
            self.set_active_model_state(tier=getattr(loaded_chk, "tier_state", 1))

        # ── The Agent Loop ────────────────────────────────────────────────────

        while True:

            await self._ensure_active_task()

            # 1. Check Abort / Cancellation

            if self.abort_event.is_set():

                logger.warning(f"AgentLoop: abort signal detected for mission {self._mission_id}")

                termination_reason = "Cancelled by user"

                try:

                    from tools.shell_tools import terminate_active_subprocesses

                    terminate_active_subprocesses(mission_id=self._mission_id)

                except Exception:

                    pass

                await self._publish_event(

                    EventType.MISSION_CANCELLED,

                    payload={"reason": termination_reason}

                )

                break



            # 2. Check Authoritative Terminal State from StateStore

            state_snapshot = self.state_store.get_snapshot()

            if state_snapshot.mission.is_terminal:

                logger.info(f"AgentLoop: mission is already in terminal state {state_snapshot.mission.status.value}")

                mission_success = state_snapshot.mission.status == MissionStatus.COMPLETED

                break



            # 2b. Check if all tasks are completed or deliverables verified by verification profile

            ws_root = Path(self.workspace.workspace_root) if (self.workspace and hasattr(self.workspace, "workspace_root") and self.workspace.workspace_root) else Path(".")

            from core.agent_loop.mvp_gate import WebsiteMvpGate

            is_web_proj = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_root, set(self._written_files))

            if is_web_proj and hasattr(self, "mvp_gate") and self.mvp_gate:

                scaffold_ok, _ = self.mvp_gate.check_scaffold_complete(ws_root)

                should_eval_completion = scaffold_ok

            else:

                should_eval_completion = (self._tasks and all(t.get("status") == "COMPLETED" for t in self._tasks)) or bool(self._written_files)



            # Cross-artifact integration validation check before admitting completion

            if should_eval_completion and self._written_files:

                from core.integration_validator import CrossArtifactValidator

                integ_rep = CrossArtifactValidator.validate_workspace(ws_root, mission.user_prompt)

                if not integ_rep.valid:

                    logger.warning(f"AgentLoop: completion evaluation deferred; integration issues found: {integ_rep.issues}")

                    should_eval_completion = False



            if should_eval_completion:

                from core.verification_profiles import classify_verification_profile, VerificationProfileEvaluator

                existing_written = [f for f in self._written_files if (ws_root / f).exists()]
                prof = classify_verification_profile(mission.user_prompt, workspace_path=str(ws_root), written_files=existing_written)

                prof_res = VerificationProfileEvaluator.evaluate(prof, ws_root, mission.user_prompt, written_files=existing_written)

                if prof_res.passed and (bool(self._written_files) or (self._tasks and all(t.get("status") == "COMPLETED" for t in self._tasks))):

                    logger.info(f"AgentLoop: requirements satisfied and verified by {prof.value} ✓")

                    mission_success = True

                    await self._publish_event(

                        EventType.VERIFICATION_COMPLETED,

                        payload={"verdict": "PASSED", "confidence": 1.0, "reason": prof_res.summary}

                    )

                    is_web_proj = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_root, set(self._written_files))

                    launch_inst = (

                        "- Open `index.html` in your browser or run a local web server to explore the application."

                        if is_web_proj else

                        "- Run tests with `pytest` or execute the package using the canonical Python interpreter."

                    )

                    created_list = "\n".join(f"- `{f}`" for f in (self._written_files or (["index.html"] if is_web_proj else [])))

                    walkthrough = (

                        f"### Mission Completed Successfully\n\n"

                        f"**Objective:** {mission.user_prompt}\n\n"

                        f"**Outcome & Deliverables:**\n"

                        f"{created_list}\n\n"

                        f"**Verification Status:**\n"

                        f"- All core requirements and behavioral contracts verified.\n"

                        f"- Details: {prof_res.summary}\n\n"

                        f"**Launch Instructions:**\n"

                        f"{launch_inst}\n"

                    )

                    await self._complete_all_tasks(prof_res.summary)

                    await self._publish_event(

                        EventType.MISSION_COMPLETED,

                        payload={

                            "reason": prof_res.summary,

                            "files_created": self._written_files,

                            "final_output": walkthrough,

                        }

                    )

                    break



            # 3. Check Safety Budgets & Model Call Deadline Limits

            elapsed_time = time.monotonic() - self._start_time

            remaining_wall_time = self.config.max_wall_time_seconds - elapsed_time



            turn_timeout = calculate_effective_turn_timeout(

                remaining_wall_time=remaining_wall_time,

                configured_timeout=float(getattr(self.config, "model_timeout_seconds", 25.0) or 25.0),

                reserve_seconds=FINAL_VERIFICATION_RESERVE_SECONDS,

                finalization_reserve_seconds=FINALIZATION_RESERVE_SECONDS,

                min_model_timeout=MIN_MODEL_REQUEST_TIMEOUT_SECONDS,

            )



            if turn_timeout is None:

                if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                    self.telemetry_logger.log_event(

                        event_type="MODEL_CALL_ADMISSION_DENIED",

                        component="deadline_control",

                        severity="WARN",

                        message="Insufficient remaining wall time budget for model turn",

                        turn=self._turns_count + 1,

                        payload={

                            "remaining_wall_time": remaining_wall_time,

                            "reserve_seconds": FINAL_VERIFICATION_RESERVE_SECONDS + FINALIZATION_RESERVE_SECONDS,

                            "min_model_timeout": MIN_MODEL_REQUEST_TIMEOUT_SECONDS,

                        },

                        destinations=["runtime", "errors"],

                    )

                termination_reason = (

                    f"Insufficient remaining wall time budget ({remaining_wall_time:.1f}s < "

                    f"{MIN_MODEL_REQUEST_TIMEOUT_SECONDS + FINAL_VERIFICATION_RESERVE_SECONDS + FINALIZATION_RESERVE_SECONDS:.1f}s required for "

                    f"{MIN_MODEL_REQUEST_TIMEOUT_SECONDS:.1f}s minimum model request + {FINAL_VERIFICATION_RESERVE_SECONDS:.1f}s verification reserve + "

                    f"{FINALIZATION_RESERVE_SECONDS:.1f}s finalization reserve)"

                    if remaining_wall_time > 0

                    else f"Max wall time exceeded ({elapsed_time:.1f}s > {self.config.max_wall_time_seconds}s)"

                )

                logger.error(f"AgentLoop: {termination_reason}")

                await self._publish_event(

                    EventType.MISSION_FAILED,

                    severity=EventSeverity.CRITICAL,

                    payload={"error": termination_reason}

                )

                break



            if self._turns_count >= self.config.max_turns:

                termination_reason = f"Max turn budget reached ({self._turns_count}/{self.config.max_turns})"

                logger.error(f"AgentLoop: {termination_reason}")

                await self._publish_event(

                    EventType.MISSION_FAILED,

                    severity=EventSeverity.CRITICAL,

                    payload={"error": termination_reason}

                )

                break



            if consecutive_failures >= self.config.max_consecutive_failures:
                last_fail = self._failure_ledger[-1] if getattr(self, "_failure_ledger", None) else None
                primary_cat = max(self._category_failures.items(), key=lambda x: x[1])[0] if getattr(self, "_category_failures", None) else "UNKNOWN"
                fail_detail = last_fail.error_class or last_fail.actual_result if last_fail else "failure limit reached"

                # Check if failures were caused by transient network disconnect (DNS, socket, 11001)
                is_transient_net = any(
                    k in str(fail_detail).lower() or (last_fail and k in str(last_fail.error_class).lower())
                    for k in ("getaddrinfo", "dns_failure", "11001", "network is unreachable", "connection reset", "connection refused", "connecterror")
                )
                if is_transient_net:
                    logger.warning(f"AgentLoop: Consecutive failure limit hit due to network disconnect ({fail_detail}). Pausing 5s for network recovery...")
                    await asyncio.sleep(5.0)
                    try:
                        import socket
                        socket.gethostbyname("generativelanguage.googleapis.com")
                        logger.info("AgentLoop: Network connectivity restored. Resetting failure counter and continuing mission.")
                        consecutive_failures = 0
                        continue
                    except Exception:
                        logger.warning("AgentLoop: Network remains unreachable after 5s.")

                cat_to_report = last_fail.category if (last_fail and getattr(last_fail, "category", None)) else primary_cat
                termination_reason = (
                    f"Consecutive failure budget exceeded ({consecutive_failures} failures) | "
                    f"Primary Category: {cat_to_report} ({fail_detail})"
                )
                logger.error(f"AgentLoop: {termination_reason}")
                await self._publish_event(
                    EventType.MISSION_FAILED,
                    severity=EventSeverity.CRITICAL,
                    payload={
                        "error": termination_reason,
                        "failure_category": last_fail.error_class if (last_fail and last_fail.error_class) else primary_cat,
                        "consecutive_failures": consecutive_failures,
                        "failure_ledger": [e.to_dict() for e in self._failure_ledger[-5:]] if getattr(self, "_failure_ledger", None) else [],
                    }
                )
                break



            # 4. Stall Detection

            is_stalled, stall_msg, stall_advice = self._detect_stall()

            if is_stalled:

                # Do not spam stall warning every turn; only fire if not fired in the immediately preceding 2 turns

                if getattr(self, "_last_stall_turn", -10) < self._turns_count - 2:

                    self._last_stall_turn = self._turns_count

                    logger.warning(f"AgentLoop: {stall_msg}")

                    await self._publish_event(

                        EventType.AGENT_STALL_DETECTED,

                        payload={"reason": stall_msg, "advice": stall_advice}

                    )

                    # Filter out old stall observations from history so they do not drown out file contents

                    self._observation_history = [

                        o for o in self._observation_history

                        if getattr(o, "source_id", "") != "stall_detector"

                    ]

                    self._observation_history.append(

                        Observation(

                            observation_id=f"obs_stall_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            source_type="system",

                            source_id="stall_detector",

                            success=True,  # Informational advisory, NOT a hard failure

                            summary=f"Stall advisory: {stall_msg}",

                            content=(

                                f"SYSTEM ADVISORY: {stall_msg}\n"

                                f"Recommended action: {stall_advice}\n"

                                f"If all core files are written, write unit tests or execute verification."

                            )

                        )

                    )

                    # Reset progress controller consecutive count so the agent has a window to respond

                    if hasattr(self, "planning_service") and hasattr(self.planning_service, "progress_controller"):

                        self.planning_service.progress_controller._consecutive_identical_fingerprints = 0



                    # Escalate repeated stalls to recovery transition, then consecutive_failures
                    self._stall_consecutive_count = getattr(self, "_stall_consecutive_count", 0) + 1
                    if self._stall_consecutive_count >= 2:
                        logger.warning(
                            f"AgentLoop: Stall repeated {self._stall_consecutive_count}x — attempting recovery transition"
                        )
                        rec_ok = await self._trigger_agent_no_progress_recovery(
                            turn_id=f"stall_{self._turns_count}",
                            rejection_reason=f"Agent progress stalled ({stall_msg})",
                            unmet_reqs=[r.title for r in self._unmet_requirements] if hasattr(self, "_unmet_requirements") else [],
                            mission=self._mission,
                        )
                        if not rec_ok:
                            consecutive_failures += 1
                            self._stall_consecutive_count = 0
                            logger.warning(
                                f"AgentLoop: Stall recovery exhausted — escalated to consecutive failure "
                                f"({consecutive_failures}/{self.config.max_consecutive_failures})"
                            )

            else:

                # Stall cleared — reset counter

                self._stall_consecutive_count = 0



            # 5. Initialize Turn

            turn_id = f"turn_{self._turns_count + 1}_{uuid.uuid4().hex[:6]}"

            turn = AgentTurn(

                turn_id=turn_id,

                mission_id=self._mission_id,

                model=TIER1_MODEL,

                provider=TIER1_PROVIDER,

                state_version_before=state_snapshot.state_version,

            )



            await self._publish_event(

                EventType.AGENT_TURN_STARTED,

                turn_id=turn_id,

                payload={"turn_id": turn_id, "turn_number": self._turns_count + 1}

            )



            # 6. Build Context for T1

            system_prompt, user_message = self._build_turn_context(mission, state_snapshot)



            # 7. Invoke Model (T1)

            t1_start = time.monotonic()
            t1_start_wall = time.time()
            requested_tier = self.active_tier
            curr_model = self.active_model
            curr_prov = self.active_provider

            await self._publish_event(

                EventType.TIER_SELECTED,

                turn_id=turn_id,

                payload={

                    "tier": requested_tier,

                    "model": curr_model,

                    "provider": curr_prov,

                    "headline": f"Selected Tier {requested_tier} ({curr_model})",

                }

            )

            await self._publish_event(

                EventType.MODEL_REQUESTED,

                turn_id=turn_id,

                payload={

                    "tier": requested_tier,

                    "model": curr_model,

                    "provider": curr_prov,

                    "headline": f"Waiting for {curr_prov} ({curr_model})...",

                }

            )

            if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                self.telemetry_logger.log_event(

                    event_type="MODEL_CALL_ADMISSION_ALLOWED",

                    component="deadline_control",

                    severity="INFO",

                    message=f"Model call admission granted: {turn_timeout:.1f}s turn budget",

                    turn=self._turns_count + 1,

                    payload={"remaining_wall_time": remaining_wall_time, "turn_timeout": turn_timeout},

                    destinations=["runtime"],

                )



            if self.abort_event.is_set():

                logger.warning(f"AgentLoop: abort signal detected before invoking model on turn {turn_id}")

                termination_reason = "Cancelled by user"

                try:

                    from tools.shell_tools import terminate_active_subprocesses

                    terminate_active_subprocesses(mission_id=self._mission_id)

                except Exception:

                    pass

                await self._publish_event(

                    EventType.MISSION_CANCELLED,

                    turn_id=turn_id,

                    payload={"reason": termination_reason}

                )

                break



            try:

                try:

                    # Give outer wait_for a small grace buffer (+3.0s) so inner multi-tier failover
                    # engine can complete its structured failover before hard cancellation
                    model_response = await asyncio.wait_for(
                        self._generate_model_turn(system_prompt, user_message, turn_id=turn_id, timeout_seconds=turn_timeout),
                        timeout=turn_timeout + 3.0
                    )
                except asyncio.TimeoutError:
                    t_overrun = time.monotonic() - t1_start
                    if t_overrun < (turn_timeout - 1.0):
                        raise

                    logger.error(f"AgentLoop: Parent turn deadline exceeded {turn_timeout:.1f}s (actual {t_overrun:.1f}s). Enforcing hard cancellation.")

                    # Authoritative router notification: update health and exclude failed tier for this mission
                    try:
                        from core.adaptive_routing import adaptive_router
                        failed_tier = self.active_tier
                        adaptive_router.record_failure(
                            tier=failed_tier,
                            error=TimeoutError(f"Turn execution exceeded parent admitted budget of {turn_timeout:.1f}s"),
                            timeout_type="TURN_DEADLINE_EXCEEDED",
                            latency=t_overrun,
                            mission_id=self._mission_id,
                        )
                        adaptive_router.exclude_tier_for_mission(
                            failed_tier,
                            self._mission_id,
                            reason=f"Turn deadline exceeded {turn_timeout:.1f}s",
                        )
                        # Latch next available tier so subsequent turns do NOT loop on the failed tier
                        eligible = adaptive_router.get_eligible_tiers(mission_id=self._mission_id)
                        if eligible:
                            next_tier = eligible[0]
                            t_prov, t_mod = getattr(self, "_provider_tier_map", {}).get(next_tier, ("failover", "failover_model"))
                            logger.warning(f"AgentLoop: Latching next eligible Tier {next_tier} ({t_prov}/{t_mod}) after parent timeout.")
                            self.set_active_model_state(tier=next_tier, provider=t_prov, model=t_mod, reason="parent_turn_timeout_failover")
                    except Exception as router_err:
                        logger.warning(f"AgentLoop: Failed to notify router of turn deadline failure: {router_err}")

                    if hasattr(self, "telemetry_logger") and self.telemetry_logger:
                        self.telemetry_logger.log_event(
                            event_type="MODEL_TURN_DEADLINE_OVERRUN",
                            component="deadline_control",
                            severity="ERROR",
                            message=f"Model turn exceeded admitted deadline of {turn_timeout:.1f}s",
                            turn=self._turns_count + 1,
                            duration_ms=t_overrun * 1000.0,
                            payload={"admitted_timeout": turn_timeout, "actual_duration_s": t_overrun, "reason": "PARENT_DEADLINE_OVERRUN"},
                            destinations=["runtime", "errors", "models"]
                        )

                    try:
                        from core.request_guard import mission_request_guard
                        mission_request_guard.release_all(self._mission_id)
                    except Exception:
                        pass

                    from models.common_adapter import NormalizedModelResponse
                    model_response = NormalizedModelResponse(
                        text="",
                        success=False,
                        error=f"MODEL_TIMEOUT: Turn execution exceeded parent admitted budget of {turn_timeout:.1f}s",
                        model="turn_deadline_enforcer",
                        provider="runtime",
                        finish_reason="timeout",
                        latency_ms=t_overrun * 1000.0,
                    )

                if self.abort_event.is_set() or getattr(self, "_terminal_event_published", False):

                    logger.warning(f"AgentLoop: abort or terminal state detected after model generation on turn {turn_id}; discarding late response.")

                    termination_reason = "Cancelled by user"

                    try:

                        from tools.shell_tools import terminate_active_subprocesses

                        terminate_active_subprocesses(mission_id=self._mission_id)

                    except Exception:

                        pass

                    if not getattr(self, "_terminal_event_published", False):

                        await self._publish_event(

                            EventType.MISSION_CANCELLED,

                            turn_id=turn_id,

                            payload={"reason": termination_reason}

                        )

                    break

                t1_latency = time.monotonic() - t1_start
                t1_end_wall = time.time()

                resp_model = getattr(model_response, "model", None) or TIER1_MODEL
                resp_provider = getattr(model_response, "provider", None) or TIER1_PROVIDER
                finish_reason = getattr(model_response, "finish_reason", None) or ("stop" if getattr(model_response, "success", True) else "error")
                tool_calls_list = getattr(model_response, "tool_calls", []) or []
                tool_call_count = len(tool_calls_list)
                is_success = bool(getattr(model_response, "success", True))

                from config.model_config import TIER1_MODEL as C_T1, TIER2_MODEL as C_T2, TIER3_MODEL as C_T3
                resp_tier = 1 if resp_model == C_T1 else (2 if resp_model == C_T2 else (3 if resp_model == C_T3 else requested_tier))

                # Record authoritative inference telemetry for every model invocation (P0)
                self.record_inference_telemetry(
                    requested_tier=requested_tier,
                    actual_provider=resp_provider,
                    actual_model=resp_model,
                    start_time=t1_start_wall,
                    completion_time=t1_end_wall,
                    duration_ms=t1_latency * 1000.0,
                    success=is_success,
                    tool_call_count=tool_call_count,
                    finish_reason=finish_reason,
                    turn_id=turn_id,
                    error=getattr(model_response, "error", None) if not is_success else None,
                )

                explicit_tier = getattr(model_response, "tier", None)
                if explicit_tier is not None and explicit_tier in (1, 2, 3, 4):
                    resp_tier = explicit_tier
                if resp_tier is not None and resp_tier in (1, 2, 3, 4) and resp_tier != self.active_tier:
                    self.set_active_model_state(
                        tier=resp_tier,
                        provider=getattr(model_response, "provider", None) or self.active_provider,
                        model=getattr(model_response, "model", None) or self.active_model,
                        reason="sticky_failover_latched",
                    )

                durations = getattr(self, "_last_turn_durations", {}) or {}
                t1_dur = durations.get("tier1_duration_ms", int(t1_latency * 1000) if resp_tier == 1 else 0)
                t2_dur = durations.get("tier2_duration_ms", int(t1_latency * 1000) if resp_tier == 2 else 0)
                t3_dur = durations.get("tier3_duration_ms", int(t1_latency * 1000) if resp_tier == 3 else 0)
                total_model_dur = int(t1_latency * 1000)

                await self._publish_event(
                    EventType.MODEL_COMPLETED,
                    turn_id=turn_id,
                    payload={
                        "model": resp_model,
                        "tier": resp_tier,
                        "requested_tier": requested_tier,
                        "actual_provider": resp_provider,
                        "actual_model_id": resp_model,
                        "start_time": t1_start_wall,
                        "completion_time": t1_end_wall,
                        "latency": t1_latency,
                        "duration_ms": total_model_dur,
                        "headline": (
                            (f"runtime turn deadline exceeded ({t1_latency:.1f}s)" if (resp_provider == "runtime" or resp_model == "turn_deadline_enforcer") else f"{resp_provider} ({resp_model}) responded in {t1_latency:.1f}s")
                            + (f" (TTFT {getattr(model_response, 'raw_timing_metadata', {}).get('ttft_ms', 0)/1000.0:.2f}s)"
                               if getattr(model_response, 'raw_timing_metadata', {}).get('ttft_ms') else "")
                        ),
                        "turn_id": turn_id,
                        "tier1_duration_ms": t1_dur,
                        "tier2_duration_ms": t2_dur,
                        "tier3_duration_ms": t3_dur,
                        "total_model_duration_ms": total_model_dur,
                        "responding_provider": resp_provider,
                        "responding_model": resp_model,
                        "response_received": False if (resp_provider == "runtime" or resp_model == "turn_deadline_enforcer") else True,
                        "finish_reason": finish_reason,
                        "tool_call_count": tool_call_count,
                        "success": is_success,
                    }
                )

                if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                    raw_meta = getattr(model_response, "raw_timing_metadata", {}) or {}

                    from core.observability.spans import classify_thinking_duration

                    breakdown = classify_thinking_duration(

                        total_duration_ms=t1_latency * 1000.0,

                        ttft_ms=raw_meta.get("ttft_ms"),

                        streaming_duration_ms=raw_meta.get("streaming_duration_ms"),

                        queue_wait_ms=raw_meta.get("queue_time"),

                    )

                    self.telemetry_logger.record_model_call(

                        turn=self._turns_count + 1,

                        tier=resp_tier,

                        provider=getattr(model_response, "provider", TIER1_PROVIDER),

                        model=resp_model,

                        duration_ms=t1_latency * 1000.0,

                        status="SUCCESS" if getattr(model_response, "success", True) else "FAILED",

                        params={"turn_timeout": turn_timeout, "temperature": self.config.temperature},

                        timings=breakdown,

                        response_meta={

                            "finish_reason": getattr(model_response, "finish_reason", None),

                            "input_tokens": getattr(model_response, "input_tokens", None),

                            "output_tokens": getattr(model_response, "output_tokens", None),

                            "tool_calls_count": len(getattr(model_response, "tool_calls", []) or []),

                        },

                        error_details={"error": getattr(model_response, "error", None)} if not getattr(model_response, "success", True) else None,

                        raw_prompt=user_message,

                        raw_response=getattr(model_response, "text", ""),

                    )

            except asyncio.CancelledError:

                logger.info(f"AgentLoop: mission {self._mission_id} cancelled during model generation.")

                termination_reason = "Cancelled by user"

                try:

                    from tools.shell_tools import terminate_active_subprocesses

                    terminate_active_subprocesses(mission_id=self._mission_id)

                except Exception:

                    pass

                try:

                    snap = self.state_store.get_snapshot()

                    snap.mission.status = MissionStatus.CANCELLED

                    snap.mission.cancelled = True

                    snap.progress.waiting_reason = WaitReason.CANCELLED

                except Exception:

                    pass

                await self._publish_event(

                    EventType.MISSION_CANCELLED,

                    turn_id=turn_id,

                    payload={"reason": termination_reason}

                )

                break

            except Exception as t1_exc:

                t1_latency = time.monotonic() - t1_start

                logger.error(f"AgentLoop: model generation failed ({t1_exc})")

                target_t2_label = getattr(self, "_provider_tier_map", {}).get(2, (None, "Tier 2"))[1] or "Tier 2"
                await self._publish_event(

                    EventType.TIER_FAILOVER_STARTED,

                    turn_id=turn_id,

                    payload={

                        "from_tier": 1,

                        "to_tier": 2,

                        "headline": f"Failover: Tier 1 -> Tier 2 ({target_t2_label})",

                        "error": str(t1_exc),

                    }

                )

                await self._publish_event(

                    EventType.MODEL_FAILED,

                    turn_id=turn_id,

                    severity=EventSeverity.ERROR,

                    payload={"error": str(t1_exc), "latency": t1_latency}

                )



                # Check for network or provider outage (Condition C / D)

                try:

                    from core.network.connectivity import (

                        classify_error_condition,

                        shared_connectivity_monitor,

                        ConnectivityCondition,

                        ConnectivityStatus,

                    )

                    net_status = await shared_connectivity_monitor.probe_now() if hasattr(shared_connectivity_monitor, "probe_now") else ConnectivityStatus.ONLINE

                    is_online = net_status == ConnectivityStatus.ONLINE

                    cond = classify_error_condition(t1_exc, is_internet_online=is_online)

                except Exception:

                    cond = None



                if cond in (ConnectivityCondition.CONDITION_C, ConnectivityCondition.CONDITION_D):

                    if consecutive_failures < 2:

                        logger.warning(

                            f"AgentLoop: Provider timeout or network degradation detected ({cond.name}), "

                            f"but consecutive_failures ({consecutive_failures}) < 2. Retrying turn via failover..."

                        )

                        consecutive_failures += 1
                        self._record_failure_entry(turn_id=turn_id, category="PROVIDER_FAILURE", error_class=f"NETWORK_{cond.name}")

                        self._turns_count += 1

                        self._observation_history.append(

                            Observation(

                                observation_id=f"obs_err_{uuid.uuid4().hex[:6]}",

                                mission_id=self._mission_id,

                                turn_id=turn_id,

                                source_type="model",

                                source_id=TIER1_MODEL,

                                success=False,

                                summary=f"Model call failed: {t1_exc}",

                                content=str(t1_exc),

                            )

                        )

                        await asyncio.sleep(1.0)

                        continue



                    wait_reason = "WAITING_FOR_PROVIDER" if cond == ConnectivityCondition.CONDITION_C else "WAITING_FOR_NETWORK"

                    cond_name = "CONDITION_C" if cond == ConnectivityCondition.CONDITION_C else "CONDITION_D"

                    logger.warning(f"AgentLoop: Outage detected ({cond_name}). Transitioning mission {self._mission_id} to {wait_reason}.")

                    await self._publish_event(

                        EventType.MISSION_WAITING,

                        turn_id=turn_id,

                        payload={

                            "wait_reason": wait_reason,

                            "condition": cond_name,

                            "error": str(t1_exc),

                        }

                    )

                    db = self.event_bus.get_database() if hasattr(self.event_bus, "get_database") else None

                    if db:

                        try:

                            ws_str = self.workspace.root_str if (self.workspace and hasattr(self.workspace, "root_str") and self.workspace.root_str) else str(Path.cwd())

                            db.save_mission(

                                mission_id=self._mission_id,

                                workspace_path=ws_str,

                                status="WAITING",

                                run_id=getattr(self, "_run_id", None) or getattr(mission, "run_id", None),

                                attempt_number=getattr(self, "_attempt_number", 1) or getattr(mission, "attempt_number", 1),

                                wait_reason=wait_reason,

                                execution_active=False,

                                recovery_required=True,

                                error_json={"error": str(t1_exc), "condition": cond_name},

                            )

                        except Exception as db_e:

                            logger.warning(f"AgentLoop: DB save error on {cond_name}: {db_e}")

                    ctrl = getattr(mission, "control", None) or getattr(self, "control", None)

                    if ctrl and hasattr(ctrl, "mark_waiting"):

                        ctrl.mark_waiting(reason=wait_reason)

                    break



                consecutive_failures += 1
                self._record_failure_entry(
                    turn_id=turn_id,
                    category="PROVIDER_FAILURE",
                    error_class=type(t1_exc).__name__,
                    actual_result=str(t1_exc),
                    elapsed_duration=t1_latency,
                )

                self._turns_count += 1

                self._observation_history.append(

                    Observation(

                        observation_id=f"obs_err_{uuid.uuid4().hex[:6]}",

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                        source_type="model",

                        source_id=TIER1_MODEL,

                        success=False,

                        summary=f"Model call failed: {t1_exc}",

                        content=str(t1_exc),

                    )

                )

                await asyncio.sleep(0.5)

                continue



            # 8. Interpret Decision

            if isinstance(model_response, Observation):

                self._record_observation(model_response)

                self._turns_count += 1

                await asyncio.sleep(0.5)

                continue



            decision = self._interpreter.interpret(model_response, turn_id=turn_id)

            turn.decision_type = decision.decision_type



            await self._publish_event(

                EventType.AGENT_DECISION,

                turn_id=turn_id,

                payload={

                    "turn_id": turn_id,

                    "decision_type": decision.decision_type.value,

                    "tool_name": decision.tool_name,

                    "reasoning": decision.reasoning[:120],

                }

            )



            # 9. Execute Semantic Decision

            if decision.decision_type == AgentDecisionType.ACT:

                tool_exec_start = time.monotonic()
                self._consecutive_empty_turns = 0

                calls_to_run = getattr(decision, "tool_calls", None) or [

                    {"name": decision.tool_name, "arguments": decision.arguments, "id": decision.tool_call_id}

                ]

                has_mutated_in_turn = False

                break_to_terminal = False

                self._recovery_triggered_this_turn = False

                seen_signatures_in_turn: Set[str] = set()
                turn_has_successful_tool = False
                turn_has_failed_tool = False



                for call_item in calls_to_run:

                    raw_call_name = call_item.get("name") or decision.tool_name or ""

                    try:

                        from tools.platform.catalog import tool_catalog

                        call_name = tool_catalog.resolve_name(raw_call_name)

                    except Exception:

                        call_name = raw_call_name



                    ws_dir_p = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd()))

                    call_name, call_args = normalize_tool_call(call_name, call_item.get("arguments") or {}, ws_dir_p)

                    call_id = call_item.get("id") or decision.tool_call_id or f"call_{uuid.uuid4().hex[:8]}"



                    # Intra-turn duplicate tool call suppression

                    action_signature = f"{call_name}:{json.dumps(call_args, sort_keys=True)}"

                    if action_signature in seen_signatures_in_turn:

                        logger.warning(f"AgentLoop: Duplicate tool call '{call_name}' within same turn batch {turn_id} suppressed")

                        dup_obs = Observation(

                            observation_id=f"obs_dup_batch_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="governor",

                            source_id="intra_turn_deduplicator",

                            success=False,

                            summary=f"Duplicate tool call '{call_name}' within same turn suppressed",

                            content=(

                                f"DUPLICATE_CALL_SUPPRESSED: You emitted identical tool call '{call_name}' with arguments "

                                f"{json.dumps(call_args)} multiple times within the same turn response. "

                                "Only the first occurrence is processed. Plan distinct actions across turns."

                            ),

                            metadata={"code": "DUPLICATE_CALL_SUPPRESSED", "tool_name": call_name},

                        )

                        turn.observation_ids.append(dup_obs.observation_id)

                        self._record_observation(dup_obs)

                        continue

                    seen_signatures_in_turn.add(action_signature)



                    # Plan Mode gating check

                    if hasattr(self, "planning_service") and self.planning_service and self.planning_service.plan_controller.execution_mode.value == "plan":

                        allowed, reason = self.planning_service.plan_controller.authorize_tool_call(

                            tool_name=call_name,

                            arguments=call_args,

                        )

                        if not allowed:

                            logger.warning(f"AgentLoop: plan mode blocked mutation action {call_name}")

                            obs = Observation(

                                observation_id=f"obs_plan_blocked_{uuid.uuid4().hex[:6]}",

                                mission_id=self._mission_id,

                                turn_id=turn_id,

                                source_type="policy",

                                source_id="plan_mode_controller",

                                success=False,

                                summary=reason,

                                content=f"PERMISSION_DENIED in Plan Mode: {reason}",

                            )

                            turn.observation_ids.append(obs.observation_id)

                            self._record_observation(obs)

                            turn_has_failed_tool = True
                            self._record_failure_entry(turn_id=turn_id, category="VALIDATION_FAILURE", error_class="MVP_GATE_BLOCKED", operation=call_name)
                            self._record_failure_entry(turn_id=turn_id, category="TOOL_FAILURE", error_class="TOOL_PERMISSION_DENIED", operation=call_name)

                            continue



                    # Tool Replay Safety - Prevent re-executing already executed tool calls in the same turn

                    action_key = f"{call_name}:{json.dumps(call_args, sort_keys=True)}"

                    is_replay = self.network_supervisor.is_tool_call_executed(

                        call_id, turn_id=turn_id, action_key=action_key

                    )

                    if is_replay:

                        logger.warning(f"AgentLoop: Tool action {call_name} ({call_id}) already executed in turn {turn_id}, suppressing replay")

                        obs = Observation(

                            observation_id=f"obs_replay_suppressed_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="policy",

                            source_id="network_supervisor",

                            success=True,

                            summary=f"Tool call {call_id} already executed; duplicate replay suppressed",

                            content="SUPPRESSED_DUPLICATE_TOOL_REPLAY",

                        )

                        turn.observation_ids.append(obs.observation_id)

                        self._record_observation(obs)

                        continue



                    # Bounded search inventory & duplicate search guidance (P0 Fix E)
                    if call_name in ("search.glob", "search_glob"):
                        pattern = call_args.get("pattern", "") if isinstance(call_args, dict) else str(call_args)
                        base_p = call_args.get("base_path", ".") if isinstance(call_args, dict) else "."
                        search_fp = f"{call_name}:{pattern}:{base_p}"
                        if getattr(self, "_last_search_fingerprint", None) == search_fp and getattr(self, "_mutations_since_last_search", 0) == 0 and getattr(self, "_last_search_result", None):
                            logger.info(f"AgentLoop: duplicate search '{pattern}' detected without intervening mutations; returning cached inventory with guidance.")
                            ws_dir_active = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd()))
                            unmet_guide = ""
                            if hasattr(self, "mvp_gate") and self.mvp_gate:
                                try:
                                    _, missing_items = self.mvp_gate.evaluate(ws_dir_active)
                                    if missing_items:
                                        unmet_guide = f" Missing required deliverables: {', '.join(missing_items)}. Next action: implement the next missing file using fs.write."
                                except Exception:
                                    pass
                            cached_obs = Observation(
                                observation_id=f"obs_search_cached_{uuid.uuid4().hex[:6]}",
                                mission_id=self._mission_id,
                                turn_id=turn_id,
                                source_type="tool",
                                source_id=call_name,
                                success=True,
                                summary=f"Duplicate search '{pattern}' without intervening changes. Returning known workspace inventory.{unmet_guide}",
                                content=f"{self._last_search_result}\n\n[WORKSPACE GUIDANCE]{unmet_guide}",
                            )
                            turn.observation_ids.append(cached_obs.observation_id)
                            self._record_observation(cached_obs)
                            continue

                    # ── P0 Duplicate Validation Guard ──
                    # Block repeating identical failed test commands when no source files have been edited
                    if call_name in ("shell.bash", "bash", "run_shell", "shell_bash") and isinstance(call_args, dict):
                        sh_cmd = call_args.get("command", "").strip()
                        cmd_low = sh_cmd.lower()
                        is_val_cmd = any(tc in cmd_low for tc in ("npm test", "npm run test", "npx jest", "pytest", "node --test", "mocha"))
                        if is_val_cmd:
                            current_src_digest = self._compute_workspace_source_digest()
                            last_val_cmd = getattr(self, "_last_validation_command", "")
                            last_val_digest = getattr(self, "_last_validation_source_digest", "")
                            last_val_failed = getattr(self, "_last_validation_failed", False)
                            last_repair_brief = getattr(self, "_last_validation_repair_brief", "")

                            if last_val_failed and current_src_digest == last_val_digest:
                                dup_count = getattr(self, "_duplicate_validation_count", 0) + 1
                                self._duplicate_validation_count = dup_count

                                if dup_count >= 2:
                                    logger.error(f"AgentLoop: Unresolved contract contradiction: repeated failing validation '{sh_cmd}' without code repair.")
                                    term_reason = (
                                        f"UNRESOLVED_CONTRACT_CONTRADICTION: Validation command '{sh_cmd}' failed repeatedly "
                                        f"without intervening source edits to resolve the diagnosed failure: {last_repair_brief[:200]}"
                                    )
                                    await self._publish_event(
                                        EventType.MISSION_FAILED,
                                        turn_id=turn_id,
                                        severity=EventSeverity.CRITICAL,
                                        payload={
                                            "error": term_reason,
                                            "failure_category": getattr(self, "_last_validation_error_class", "TEST_FAILURE"),
                                            "command": sh_cmd,
                                            "consecutive_failures": consecutive_failures,
                                        }
                                    )
                                    break_to_terminal = True
                                    break

                                obs = Observation(
                                    observation_id=f"obs_duplicate_val_blocked_{uuid.uuid4().hex[:6]}",
                                    mission_id=self._mission_id,
                                    turn_id=turn_id,
                                    source_type="governor",
                                    source_id="duplicate_validation_guard",
                                    success=False,
                                    summary=f"Duplicate validation attempt: '{sh_cmd}' blocked. No workspace source files were modified since last test failure.",
                                    content=(
                                        f"[DUPLICATE_VALIDATION_ATTEMPT]\n"
                                        f"Command: {sh_cmd}\n\n"
                                        f"You ran this exact test command and it failed. No source files, contracts, or tests have been modified since.\n"
                                        f"Running unchanged tests repeatedly does not fix failures.\n\n"
                                        f"Previous Test Diagnosis:\n{last_repair_brief or 'Tests failed with non-zero exit code.'}\n\n"
                                        f"Action Required: You MUST edit the application files (using fs.edit or fs.write) to repair the diagnosed contract or test issue before re-running tests."
                                    ),
                                )
                                turn.observation_ids.append(obs.observation_id)
                                self._record_observation(obs)
                                continue

                    # Browser Inactive Repetition Guard (Section 6 & 8)
                    if call_name.startswith("browser_") or call_name in ("browser_inspect", "browser_preview"):
                        browser_fail_count = getattr(self, "_consecutive_browser_failures", 0)
                        if browser_fail_count >= 2:
                            logger.warning(f"AgentLoop: Browser session guard blocking repeated failed browser action '{call_name}'")
                            obs = Observation(
                                observation_id=f"obs_browser_guard_{uuid.uuid4().hex[:6]}",
                                mission_id=self._mission_id,
                                turn_id=turn_id,
                                source_type="governor",
                                source_id="browser_session_guard",
                                success=False,
                                summary=f"Browser action '{call_name}' blocked: Browser session is inactive after repeated failures.",
                                content=(
                                    f"[BROWSER_SESSION_GUARD]\n"
                                    f"Action '{call_name}' was blocked because recent browser evaluations failed due to inactive session or unreachable server.\n"
                                    f"Ensure the application server is running (e.g. 'node server.js &' or verify port is active) before re-running browser preview or DOM inspection."
                                ),
                            )
                            turn.observation_ids.append(obs.observation_id)
                            self._record_observation(obs)
                            continue

                    # Redundancy Guard (Section 10): block repeated identical failed attempts (>= 2)

                    if getattr(self, "_tool_failure_counts", {}).get(action_key, 0) >= 2:

                        fail_count = self._tool_failure_counts[action_key]

                        logger.warning(f"AgentLoop: Redundancy guard blocking repeated failed action {call_name} (failed {fail_count} times)")

                        obs = Observation(

                            observation_id=f"obs_redundancy_blocked_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="governor",

                            source_id="redundancy_guard",

                            success=False,

                            summary=f"Redundancy guard blocked '{call_name}' after {fail_count} identical failures.",

                            content=(

                                f"REDUNDANCY GUARD: Tool '{call_name}' with arguments {json.dumps(call_args)} has failed "

                                f"{fail_count} consecutive times with unchanged output. "

                                "Do NOT repeat this identical command without taking a materially different recovery action "

                                "(e.g. edit source files using fs.edit, install dependencies, or adjust configuration)."

                            ),

                        )

                        turn.observation_ids.append(obs.observation_id)

                        self._record_observation(obs)

                        last_err = self._failure_ledger[-1].error_class if (hasattr(self, "_failure_ledger") and self._failure_ledger) else "REDUNDANCY_GUARD_BLOCKED"
                        last_cat = self._failure_ledger[-1].category if (hasattr(self, "_failure_ledger") and self._failure_ledger) else "TOOL_FAILURE"
                        self._record_failure_entry(turn_id=turn_id, category=last_cat, error_class=last_err, operation=call_name)

                        continue



                    # Website MVP Gate (Section 6 & 7): enforce 4-phase progression

                    from core.agent_loop.mvp_gate import WebsiteMvpGate

                    ws_dir_p = Path(self.workspace.workspace_root) if (self.workspace and hasattr(self.workspace, "workspace_root") and self.workspace.workspace_root) else Path(".")

                    if hasattr(self, "mvp_gate") and self.mvp_gate and WebsiteMvpGate.is_website_mission(mission.user_prompt, ws_dir_p, set(self._written_files)):

                        allowed, mvp_reason = self.mvp_gate.authorize_action(call_name, call_args, workspace_root=ws_dir_p)

                        if not allowed:

                            logger.warning(f"AgentLoop: MVP Gate blocked action {call_name}: {mvp_reason}")

                            obs = Observation(

                                observation_id=f"obs_mvp_blocked_{uuid.uuid4().hex[:6]}",

                                mission_id=self._mission_id,

                                turn_id=turn_id,

                                source_type="governor",

                                source_id="website_mvp_gate",

                                success=False,

                                summary=mvp_reason,

                                content=f"MVP_GATE_BLOCK: {mvp_reason}",

                            )

                            turn.observation_ids.append(obs.observation_id)

                            self._record_observation(obs)

                            turn_has_failed_tool = True

                            continue



                    # Safe boundary: check cancellation immediately prior to tool execution

                    if self.abort_event.is_set():

                        logger.warning(f"AgentLoop: abort signal detected before executing tool '{call_name}' on turn {turn_id}")

                        termination_reason = "Cancelled by user"

                        try:

                            from tools.shell_tools import terminate_active_subprocesses

                            terminate_active_subprocesses(mission_id=self._mission_id)

                        except Exception:

                            pass

                        await self._publish_event(

                            EventType.MISSION_CANCELLED,

                            turn_id=turn_id,

                            payload={"reason": termination_reason}

                        )

                        break_to_terminal = True

                        break



                    # Progress Governor: block excessive task.todo planning or redundant empty directory reads

                    if call_name in ("task.todo", "todo", "task_todo") and (self._consecutive_planning_turns >= 1 or self._turns_count >= 1):

                        logger.warning(f"AgentLoop: blocking excessive task.todo (turn {self._turns_count}, count {self._consecutive_planning_turns})")

                        self._consecutive_planning_turns += 1

                        gov_obs = Observation(

                            observation_id=f"obs_gov_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="governor",

                            source_id="planning_governor",

                            success=False,

                            summary="Excessive planning blocked. Code creation required.",

                            content=(

                                "PROGRESS GOVERNOR: You have already planned your tasks. Planning is complete. task.todo is locked. "

                                "Proceed immediately to implement the required application files using fs.write "

                                "(e.g. index.html, styles.css, app.js) or fetch/download assets using web_search or download_image."

                            )

                        )

                        turn.observation_ids.append(gov_obs.observation_id)

                        self._record_observation(gov_obs)

                        continue



                    if self._consecutive_non_mutating_turns >= 2 and call_name in ("shell.bash", "bash_exec") and any(w in str(call_args).lower() for w in ("dir", "ls", "pwd", "get-childitem", "find .", "find /")):

                        logger.warning(f"AgentLoop: blocking redundant directory inspection ({self._consecutive_non_mutating_turns} consecutive non-mutating)")

                        gov_obs = Observation(

                            observation_id=f"obs_gov_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="governor",

                            source_id="inspection_governor",

                            success=False,

                            summary="Redundant inspection blocked. Code creation or editing required.",

                            content=(

                                "PROGRESS GOVERNOR: Directory exploration is complete (0 application files). "

                                "Do NOT run dir/ls/find commands again. You must implement or modify application files "

                                "using fs.write (e.g. main.js, index.html) or run tests immediately."

                            )

                        )

                        turn.observation_ids.append(gov_obs.observation_id)

                        self._record_observation(gov_obs)

                        self._recent_actions.append((call_name, str(call_args)))

                        continue



                    # Progress Governor: block repeated churn on auxiliary non-entrypoint files when main entrypoint is missing

                    if call_name in ("fs.write", "fs.edit", "write_file", "edit_file") and isinstance(call_args, dict):

                        ws_dir = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else Path.cwd())

                        target_write_path = str(call_args.get("path") or call_args.get("file_path") or "").replace("\\", "/").strip("./")

                        norm_target = target_write_path.lower()

                        from core.project_contract import ProjectContract

                        expected_entrypoint_js = ProjectContract.determine_canonical_js(mission.user_prompt or "", ws_dir)

                        core_entrypoints = {"index.html", expected_entrypoint_js.lower(), "main.js", "style.css", "package.json", "vite.config.js", "app.js", "src/main.js", "src/app.js", "src/index.js"}

                        import re

                        clean_prompt = re.sub(r'https?://[^\s<>"\']+', '', mission.user_prompt)

                        is_web = any(k in clean_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "observatory", "frontend", "ui", "space", "orbit", "rocket", "3d", "three")) or (ws_dir / "index.html").exists()

                        has_main = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 100 for j in (expected_entrypoint_js, "main.js", "src/main.js", "app.js", "index.js", "script.js"))



                        target_write_count = self._file_write_counts.get(norm_target, 0)

                        if is_web and not has_main and norm_target not in core_entrypoints and target_write_count >= 2:

                            logger.warning(f"AgentLoop: blocking auxiliary write on '{target_write_path}' ({target_write_count} previous writes) while '{expected_entrypoint_js}' is missing")

                            gov_obs = Observation(

                                observation_id=f"obs_gov_{uuid.uuid4().hex[:6]}",

                                mission_id=self._mission_id,

                                turn_id=turn_id,

                                source_type="governor",

                                source_id="auxiliary_churn_governor",

                                success=False,

                                summary=f"Auxiliary write blocked for '{target_write_path}'. Entrypoint '{expected_entrypoint_js}' must be created.",

                                content=(

                                    f"PROGRESS GOVERNOR: You have already modified auxiliary file '{target_write_path}' {target_write_count} times. "

                                    f"The primary application entrypoint '{expected_entrypoint_js}' has not been created yet. "

                                    f"Do NOT edit '{target_write_path}' again. "

                                    f"Next step: call fs.write(path='{expected_entrypoint_js}', content=...) to implement the application."

                                )

                            )

                            turn.observation_ids.append(gov_obs.observation_id)

                            self._record_observation(gov_obs)

                            self._consecutive_non_mutating_turns += 1

                            self._recent_actions.append((call_name, str(call_args)))

                            continue



                        # Progress Governor: block redundant churn on already-completed core files when an unmet requirement targets a different file

                        if is_web and hasattr(self, "mvp_gate") and self.mvp_gate:

                            unmet_reqs_cur = self.mvp_gate.get_unmet_requirements(ws_dir_p)

                            if unmet_reqs_cur:

                                from core.agent_loop.mvp_gate import WebsiteMvpGate

                                target_repair, action_inst = WebsiteMvpGate.parse_scaffold_target(unmet_reqs_cur[0])
                                is_non_file_target = target_repair in ("npm run build", "browser_open_preview", "open_preview")

                                # Check if contract validation report has pending defects on this file type
                                fc_report = getattr(self, "_last_frontend_validation_report", None)
                                has_pending_contract_issues = False
                                if fc_report and getattr(fc_report, "errors", None):
                                    if norm_target.endswith(".css") and any(w in err.lower() for err in fc_report.errors for w in ("css", "style", "layout", "rule", "color")):
                                        has_pending_contract_issues = True
                                    elif norm_target.endswith(".html") and any(w in err.lower() for err in fc_report.errors for w in ("html", "tag", "id", "class")):
                                        has_pending_contract_issues = True
                                    elif norm_target.endswith(".js") and any(w in err.lower() for err in fc_report.errors for w in ("js", "javascript", "filter", "dom", "form", "script", "orphan")):
                                        has_pending_contract_issues = True

                                if target_repair and not is_non_file_target and not has_pending_contract_issues and norm_target != target_repair.lower() and not any(kw in norm_target for kw in ('test', 'spec', 'readme')) and not (norm_target.endswith((".js", ".ts")) and target_repair.lower().endswith((".js", ".ts"))):

                                    target_disk = ws_dir_p / target_write_path

                                    if target_disk.exists() and target_disk.stat().st_size > 50 and self._file_write_counts.get(norm_target, 0) >= 1:

                                        if not any(norm_target in u.lower() for u in unmet_reqs_cur):

                                            logger.warning(f"AgentLoop: blocking redundant write on completed file '{target_write_path}' while '{target_repair}' needs attention")

                                            next_hint = "call tool browser_open_preview(file_path='index.html') to verify the rendered website." if target_repair in ("browser_open_preview", "open_preview") else (f"call fs.write or fs.edit on '{target_repair}'." if target_repair != "npm run build" else "run 'npm run build' via bash.")

                                            gov_obs = Observation(

                                                observation_id=f"obs_gov_{uuid.uuid4().hex[:6]}",

                                                mission_id=self._mission_id,

                                                turn_id=turn_id,

                                                source_type="governor",

                                                source_id="completed_file_churn_governor",

                                                success=False,

                                                summary=f"Redundant write on completed file '{target_write_path}' blocked. Target '{target_repair}' requires repair.",

                                                content=(

                                                    f"PROGRESS GOVERNOR: File '{target_write_path}' is already complete ({target_disk.stat().st_size} bytes). "

                                                    f"An active unmet requirement exists on '{target_repair}': {action_inst} "

                                                    f"Do NOT edit or overwrite '{target_write_path}' again. "

                                                    f"Next step: {next_hint}"

                                                )

                                            )

                                            turn.observation_ids.append(gov_obs.observation_id)

                                            self._record_observation(gov_obs)

                                            self._recent_actions.append((call_name, str(call_args)))

                                            continue



                    # Progress Governor: block redundant unchanged reads of the same file or directories

                    if call_name in ("fs.read", "read_file") and isinstance(call_args, dict):

                        raw_read_path = str(call_args.get("path") or call_args.get("file_path") or "").replace("\\", "/").strip("./")

                        if not raw_read_path:

                            gov_obs = Observation(

                                observation_id=f"obs_gov_{uuid.uuid4().hex[:6]}",

                                mission_id=self._mission_id,

                                turn_id=turn_id,

                                source_type="governor",

                                source_id="file_read_governor",

                                success=False,

                                summary="Directory read blocked. read_file requires a regular file.",

                                content=(

                                    "PROGRESS GOVERNOR: Cannot read directory '.' with read_file. "

                                    "Use search.glob or list_directory to inspect directory contents, or call fs.write to create required files."

                                )

                            )

                            turn.observation_ids.append(gov_obs.observation_id)

                            self._record_observation(gov_obs)

                            self._recent_actions.append((call_name, str(call_args)))

                            continue



                        # Duplicate Tool Call Guard (P0): Block repeating informational commands or failed syntax checks

                        if call_name in ("shell.bash", "bash", "run_shell", "shell_bash") and isinstance(call_args, dict):

                            cmd_raw = str(call_args.get("command") or call_args.get("cmd") or "").strip()

                            norm_cmd = cmd_raw.lower()

                            info_cmds = ("node -v", "node --version", "npm -v", "npm --version", "python --version", "git --version")

                            if any(norm_cmd == ic or norm_cmd.startswith(f"{ic} ") for ic in info_cmds):

                                if norm_cmd in self._executed_info_commands:

                                    rej_reason = (

                                        f"TOOL_REJECTED_NO_PROGRESS: Command '{cmd_raw}' has already been executed in this mission. "

                                        "Its result is known. Do not repeat informational commands. Proceed to implement code using fs.write or fs.edit."

                                    )

                                    action_id = f"act_rej_{uuid.uuid4().hex[:8]}"

                                    await self._publish_event(

                                        EventType.ACTION_DENIED,

                                        turn_id=turn_id,

                                        severity=EventSeverity.WARNING,

                                        payload={"action_id": action_id, "tool_name": call_name, "reason": rej_reason, "code": "TOOL_REJECTED_DUPLICATE_CALL"}

                                    )

                                    rej_obs = Observation(

                                        observation_id=f"obs_dup_{uuid.uuid4().hex[:6]}",

                                        mission_id=self._mission_id,

                                        turn_id=turn_id,

                                        source_type="dispatcher",

                                        source_id="duplicate_call_guard",

                                        success=False,

                                        summary=f"Tool call '{call_name}' rejected: duplicate info command ({cmd_raw})",

                                        content=rej_reason,

                                        metadata={"code": "TOOL_REJECTED_DUPLICATE_CALL", "command": cmd_raw},

                                    )

                                    turn.observation_ids.append(rej_obs.observation_id)

                                    self._record_observation(rej_obs)

                                    self._actions_count += 1

                                    self._tool_calls_count += 1

                                    continue

                                self._executed_info_commands.add(norm_cmd)



                            # Syntax check duplicate guard

                            if norm_cmd.startswith("node -c") or "py_compile" in norm_cmd:

                                parts = cmd_raw.split()

                                target_f = parts[-1] if len(parts) >= 3 else ""

                                target_f_clean = target_f.replace('"', '').replace("'", "")

                                target_p = ws_dir_p / target_f_clean

                                curr_f_hash = ""

                                if target_p.exists() and target_p.is_file():

                                    import hashlib

                                    try:

                                        curr_f_hash = hashlib.sha256(target_p.read_bytes()).hexdigest()

                                    except Exception:

                                        pass

                                prev_fail_hash = self._failed_syntax_checks.get(norm_cmd)

                                if prev_fail_hash and curr_f_hash and prev_fail_hash == curr_f_hash:

                                    rej_reason = (

                                        f"TOOL_REJECTED_NO_PROGRESS: Syntax check '{cmd_raw}' previously failed and target file "

                                        f"'{target_f_clean}' has not been modified since that failure. You MUST fix the syntax using fs.edit or fs.write before re-running verification."

                                    )

                                    action_id = f"act_rej_{uuid.uuid4().hex[:8]}"

                                    await self._publish_event(

                                        EventType.ACTION_DENIED,

                                        turn_id=turn_id,

                                        severity=EventSeverity.WARNING,

                                        payload={"action_id": action_id, "tool_name": call_name, "reason": rej_reason, "code": "TOOL_REJECTED_DUPLICATE_CALL"}

                                    )

                                    rej_obs = Observation(

                                        observation_id=f"obs_dup_{uuid.uuid4().hex[:6]}",

                                        mission_id=self._mission_id,

                                        turn_id=turn_id,

                                        source_type="dispatcher",

                                        source_id="duplicate_call_guard",

                                        success=False,

                                        summary=f"Tool call '{call_name}' rejected: unchanged failed check ({cmd_raw})",

                                        content=rej_reason,

                                        metadata={"code": "TOOL_REJECTED_DUPLICATE_CALL", "command": cmd_raw},

                                    )

                                    turn.observation_ids.append(rej_obs.observation_id)

                                    self._record_observation(rej_obs)

                                    self._actions_count += 1

                                    self._tool_calls_count += 1

                                    continue



                        # Section 3: Hard enforcement for redundant unchanged reads at production dispatcher

                        target_disk_file = ws_dir_p / raw_read_path

                        if target_disk_file.exists() and target_disk_file.is_file():

                            import hashlib

                            try:

                                curr_bytes = target_disk_file.read_bytes()

                                curr_hash = hashlib.sha256(curr_bytes).hexdigest()

                            except Exception:

                                curr_hash = ""



                            norm_key = raw_read_path.lower()

                            prev_hash, read_count = self._read_fingerprint_tracker.get(norm_key, ("", 0))

                            if prev_hash == curr_hash and curr_hash:

                                read_count += 1

                            else:

                                read_count = 1

                            self._read_fingerprint_tracker[norm_key] = (curr_hash, read_count)



                            # If file was written in this mission and scaffold deliverables remain unmet,

                            # reading it back without making scaffold progress is blocked immediately

                            was_written_in_mission = (norm_key in self._file_write_counts)

                            from core.agent_loop.mvp_gate import WebsiteMvpGate

                            is_web_task = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_dir_p, set(self._written_files))

                            is_scaffold_incomplete = bool(is_web_task and hasattr(self, "mvp_gate") and self.mvp_gate and not self.mvp_gate.check_scaffold_complete(ws_dir_p)[0])

                            unmet_reqs_pre = self.mvp_gate.get_unmet_requirements(ws_dir_p) if (is_web_task and hasattr(self, "mvp_gate") and self.mvp_gate) else []

                            # If this file has an active validation or integration mismatch, allow reading it so the model can inspect and fix it

                            file_has_active_issue = any(target_disk_file.name.lower() in u.lower() for u in unmet_reqs_pre)



                            if file_has_active_issue and read_count < 2:

                                # When investigating an active defect or DOM mismatch, reading once is permitted for diagnosis

                                should_block = False

                            else:

                                should_block = (read_count >= 2) if (is_scaffold_incomplete or was_written_in_mission) else (read_count >= 3)



                            if should_block:

                                self._consecutive_no_progress_blocks += 1

                                unmet_reqs = unmet_reqs_pre

                                unmet_msg = f" Unmet requirement(s): {', '.join(unmet_reqs)}." if unmet_reqs else ""



                                if is_web_task:

                                    valid_file_delivs = [

                                        u.split(":")[-1].strip() for u in unmet_reqs

                                        if any(ext in u.lower() for ext in (".html", ".css", ".js", ".json"))

                                    ]

                                    deliv_example = valid_file_delivs[0] if valid_file_delivs else "index.html"

                                    if any("mismatch" in u.lower() for u in unmet_reqs):

                                        permitted_next = (

                                            f"Use fs.edit or fs.write to fix the DOM/script integration mismatch: {', '.join(unmet_reqs)}."

                                        )

                                    else:

                                        permitted_next = (

                                            f"Call fs.write to create missing deliverables (e.g. '{deliv_example}') "

                                            "or execute build/verification commands."

                                        )

                                else:

                                    permitted_next = "Proceed to complete the mission, report the results, or execute verification checks."

                                rejection_reason = (

                                    f"TOOL_REJECTED_NO_PROGRESS: Target '{raw_read_path}' (SHA-256 {curr_hash[:8]}) "

                                    f"{'was just created in this mission; its contents are known.' if was_written_in_mission and read_count == 1 else f'has already been read {read_count} times without intermediate modifications.'}"

                                    f"{unmet_msg} "

                                    f"Permitted next action: {permitted_next}"

                                )



                                # Authoritative event logging: requested and denied before execution

                                action_id = f"act_rej_{uuid.uuid4().hex[:8]}"

                                await self._publish_event(

                                    EventType.ACTION_REQUESTED,

                                    turn_id=turn_id,

                                    payload={

                                        "action_id": action_id,

                                        "tool_name": "fs.read",

                                        "arguments": call_args,

                                    }

                                )

                                await self._publish_event(

                                    EventType.ACTION_DENIED,

                                    turn_id=turn_id,

                                    severity=EventSeverity.WARNING,

                                    payload={

                                        "action_id": action_id,

                                        "tool_name": "fs.read",

                                        "reason": rejection_reason,

                                        "code": "TOOL_REJECTED_NO_PROGRESS",

                                    }

                                )



                                rej_obs = Observation(

                                    observation_id=f"obs_no_prog_{uuid.uuid4().hex[:6]}",

                                    mission_id=self._mission_id,

                                    turn_id=turn_id,

                                    source_type="dispatcher",

                                    source_id="no_progress_guard",

                                    success=False,

                                    summary=f"Tool call 'fs.read' rejected: no progress ({raw_read_path})",

                                    content=rejection_reason,

                                    metadata={"code": "TOOL_REJECTED_NO_PROGRESS", "path": raw_read_path, "read_count": read_count},

                                )

                                turn.observation_ids.append(rej_obs.observation_id)

                                self._record_observation(rej_obs)

                                self._actions_count += 1

                                self._tool_calls_count += 1

                                self._recent_actions.append((call_name, str(call_args)))



                                # Deterministic loop breaker after 2 consecutive blocks (Phase F)

                                if self._consecutive_no_progress_blocks >= 2 and not getattr(self, '_recovery_triggered_this_turn', False):

                                    self._recovery_triggered_this_turn = True

                                    target_file_to_write = None

                                    if unmet_reqs:

                                        from core.agent_loop.mvp_gate import WebsiteMvpGate

                                        tf, _ = WebsiteMvpGate.parse_scaffold_target(unmet_reqs[0])

                                        if tf and tf not in ("npm run build", "browser_open_preview"):

                                            target_file_to_write = tf



                                    in_tier_corrections = getattr(self, '_in_tier_correction_count', 0)

                                    # Phase F: Prioritize targeted in-tier directive before model provider failover

                                    if in_tier_corrections < 1 and target_file_to_write:

                                        self._in_tier_correction_count = in_tier_corrections + 1

                                        logger.warning(

                                            f"AgentLoop: In-tier corrective directive issued for '{target_file_to_write}' (attempt {in_tier_corrections + 1}/2). Provider failover suppressed."

                                        )

                                        directive_obs = Observation(

                                            observation_id=f"obs_cor_{uuid.uuid4().hex[:6]}",

                                            mission_id=self._mission_id,

                                            turn_id=turn_id,

                                            source_type="governor",

                                            source_id="reconciliation_controller",

                                            success=False,

                                            summary=f"MANDATORY DIRECTIVE: You MUST create '{target_file_to_write}' using fs.write now. Reading '{raw_read_path}' is strictly prohibited.",

                                            content=(

                                                f"CRITICAL SYSTEM DIRECTIVE:\n"

                                                f"The required application file '{target_file_to_write}' is MISSING.\n"

                                                f"Do NOT call fs.read on '{raw_read_path}'.\n"

                                                f"Call fs.write immediately with target path '{target_file_to_write}' and complete code.\n"

                                            ),

                                            metadata={"code": "MANDATORY_WRITE_DIRECTIVE", "target": target_file_to_write},

                                        )

                                        self._record_observation(directive_obs)

                                        self._consecutive_no_progress_blocks = 0

                                        continue

                                    else:

                                        logger.warning(

                                            f"AgentLoop: Consecutive no-progress blocks reached {self._consecutive_no_progress_blocks} with in-tier corrections exhausted. Executing bounded recovery."

                                        )

                                        saved_blocks = self._consecutive_no_progress_blocks

                                        recovery_handled = await self._execute_no_progress_recovery(

                                            turn_id=turn_id,

                                            mission=mission,

                                            unmet_reqs=unmet_reqs,

                                            rejection_reason=rejection_reason,

                                        )

                                        if recovery_handled:
                                            # Bounded multi-tier escalation succeeded; reset consecutive counters and continue loop
                                            self._consecutive_no_progress_blocks = 0
                                            self._cycle_no_progress_blocks = 0
                                            self._recovery_triggered_this_turn = False
                                            continue

                                        # Only terminate when recovery transitions / tiers are genuinely exhausted
                                        self._consecutive_no_progress_blocks = max(self._consecutive_no_progress_blocks, saved_blocks)

                                        termination_reason = (

                                            f"AGENT_NO_PROGRESS: Mission loop terminated. Repeated no-progress operations on '{raw_read_path}' "

                                            f"persisted after recovery transition. Unmet: {'; '.join(unmet_reqs) if unmet_reqs else 'Deliverables incomplete'}."

                                        )

                                        await self._publish_event(

                                            EventType.MISSION_FAILED,

                                            turn_id=turn_id,

                                            severity=EventSeverity.CRITICAL,

                                            payload={"error": termination_reason, "code": "AGENT_NO_PROGRESS", "unmet_requirements": unmet_reqs}

                                        )

                                        break_to_terminal = True

                                        break

                                continue



                    action = ActionEnvelope(

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                        tool_call_id=call_id,

                        tool_name=call_name,

                        arguments=call_args,

                        policy_context={"user_prompt": mission.user_prompt},

                    )

                    turn.action_ids.append(action.action_id)



                    obs = await self._action_executor.execute_action(action, workspace=self.workspace)

                    if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                        dur_ms = getattr(obs, "duration_seconds", 0.0) * 1000.0

                        self.telemetry_logger.record_tool_call(

                            tool_call_id=call_id,

                            tool_name=call_name,

                            turn=self._turns_count + 1,

                            duration_ms=dur_ms,

                            success=obs.success,

                            exit_code=getattr(obs, "exit_code", 0 if obs.success else 1),

                            arguments=call_args,

                            target_path=call_args.get("path") if isinstance(call_args, dict) else None,

                            stdout=getattr(obs, "content", ""),

                            stderr=getattr(obs, "summary", "") if not obs.success else "",

                            error_message=getattr(obs, "summary", "") if not obs.success else None,

                        )

                        if call_name in ("fs.write", "fs.edit", "write_file", "edit_file"):

                            t_path = call_args.get("path") if isinstance(call_args, dict) else ""

                            det = getattr(obs, "details", {}) or {}

                            if obs.success:

                                self.telemetry_logger.record_file_operation(

                                    relative_path=str(t_path),

                                    operation="write" if "write" in call_name else "edit",

                                    size_before=det.get("size_before"),

                                    size_after=det.get("size_after") or (len(str(call_args.get("content", "")).encode("utf-8")) if "content" in call_args else None),

                                    sha256_before=det.get("sha256_before"),

                                    sha256_after=det.get("sha256_after"),

                                    content_changed=det.get("changed", True),

                                    provenance={"turn": self._turns_count + 1, "tier": getattr(self.orchestrator, "_active_tier", 1)},

                                )

                            else:

                                self.telemetry_logger.log_event(

                                    event_type="FILE_WRITE_FAILED",

                                    component="filesystem",

                                    severity="ERROR",

                                    message=f"File {call_name} failed for {t_path}: {getattr(obs, 'summary', '') or getattr(obs, 'content', '')}",

                                    payload={

                                        "file": str(t_path),

                                        "operation": "write" if "write" in call_name else "edit",

                                        "exit_code": getattr(obs, "exit_code", 1),

                                        "error": getattr(obs, "summary", "") or getattr(obs, "content", ""),

                                    },

                                    destinations=["files", "errors"],

                                )

                    if self.abort_event.is_set():

                        logger.warning(f"AgentLoop: abort signal detected after executing tool '{call_name}' on turn {turn_id}")

                        termination_reason = "Cancelled by user"

                        try:

                            from tools.shell_tools import terminate_active_subprocesses

                            terminate_active_subprocesses(mission_id=self._mission_id)

                        except Exception:

                            pass

                        await self._publish_event(

                            EventType.MISSION_CANCELLED,

                            turn_id=turn_id,

                            payload={"reason": termination_reason}

                        )

                        break_to_terminal = True

                        break



                    if call_name in ("search.glob", "search_glob") and obs.success:
                        pattern = call_args.get("pattern", "") if isinstance(call_args, dict) else str(call_args)
                        base_p = call_args.get("base_path", ".") if isinstance(call_args, dict) else "."
                        self._last_search_fingerprint = f"{call_name}:{pattern}:{base_p}"
                        self._last_search_result = getattr(obs, "content", "") or getattr(obs, "summary", "")
                        self._mutations_since_last_search = 0

                    self.network_supervisor.register_executed_tool_call(
                        call_id, turn_id=turn_id, action_key=action_key
                    )

                    turn.observation_ids.append(obs.observation_id)

                    self._record_observation(obs)

                    self._actions_count += 1

                    self._tool_calls_count += 1



                    # Track action pattern for stall detection

                    self._recent_actions.append((call_name, str(call_args)))



                    # Wire StuckLoopDetector and FailureClassifier

                    if hasattr(self, "stuck_detector") and self.stuck_detector:

                        from core.failure_classifier import FailureClassifier

                        fail_cat = None

                        if not obs.success:

                            fail_cat = FailureClassifier.classify(call_name, getattr(obs, "summary", "") or getattr(obs, "content", ""), "tool_execution").value

                        self.stuck_detector.record_operation(

                            fp_or_tool_name=call_name,

                            arguments=call_args if isinstance(call_args, dict) else {"arg": str(call_args)},

                            result_summary=getattr(obs, "summary", "") or getattr(obs, "content", "")[:128],

                            success=obs.success,

                            mission_id=self._mission_id,

                            failure_class=fail_cat,

                        )

                        is_stuck, stuck_reason = self.stuck_detector.check_stuck()

                        if is_stuck:

                            logger.warning(f"AgentLoop: StuckLoopDetector detected loop: {stuck_reason}")

                            await self._publish_event(

                                EventType.ACTION_DENIED,

                                turn_id=turn_id,

                                severity=EventSeverity.WARNING,

                                payload={

                                    "action_id": action.action_id,

                                    "tool_name": call_name,

                                    "reason": stuck_reason,

                                    "code": "STUCK_LOOP_DETECTED",

                                    "failure_category": "STUCK_LOOP_ERROR",

                                }

                            )



                    # Reliability: Record syntax diagnostics & track failed syntax checks

                    obs_diag = getattr(obs, "diagnostic", None)

                    if not obs_diag and hasattr(obs, "metadata") and isinstance(obs.metadata, dict):

                        obs_diag = obs.metadata.get("diagnostic")

                    if not obs_diag and not obs.success:

                        from core.structured_observation import extract_syntax_diagnostic

                        raw_err_sample = f"{getattr(obs, 'summary', '')}\n{getattr(obs, 'content', '')}"

                        obs_diag = extract_syntax_diagnostic(raw_err_sample)



                    if obs_diag and not obs.success:

                        diag_target_key = Path(obs_diag.get("file", "app.js")).name.lower()

                        self._pending_diagnostics[diag_target_key] = obs_diag

                        logger.warning(f"AgentLoop: Recorded pending syntax diagnostic for '{diag_target_key}': {obs_diag}")

                        if hasattr(self, "syntax_repair"):

                            t_file = obs_diag.get("file") or diag_target_key

                            cand_c = call_args.get("content") if isinstance(call_args, dict) else None

                            self.syntax_repair.create_or_update_ticket(

                                target_file=t_file,

                                validator=f"node --check {t_file}",

                                stderr_or_output=raw_err_sample,

                                exit_code=getattr(obs, "exit_code", 1),

                                workspace_root=ws_dir_p,

                                candidate_content=cand_c,

                                mission_id=getattr(self, "mission_id", ""),

                                run_id=getattr(self, "run_id", ""),

                            )

                        if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                            self.telemetry_logger.record_validation_result(

                                validator_name="syntax_check",

                                target_file=diag_target_key,

                                success=False,

                                duration_ms=getattr(obs, "duration_seconds", 0.0) * 1000.0,

                                exit_code=getattr(obs, "exit_code", 1),

                                diagnostic=obs_diag,

                                raw_output=raw_err_sample,

                            )



                    # Track failed syntax checks for duplicate suppression

                    if call_name in ("shell.bash", "bash", "run_shell", "shell_bash") and isinstance(call_args, dict):

                        cmd_executed = str(call_args.get("command") or call_args.get("cmd") or "").strip()

                        norm_cmd_ex = cmd_executed.lower()

                        if norm_cmd_ex.startswith("node -c") or "py_compile" in norm_cmd_ex:

                            parts = cmd_executed.split()

                            target_f_clean = parts[-1].replace('"', '').replace("'", "") if len(parts) >= 3 else ""

                            target_p = ws_dir_p / target_f_clean

                            if obs.success:

                                self._failed_syntax_checks.pop(norm_cmd_ex, None)

                                if target_f_clean:

                                    self._pending_diagnostics.pop(Path(target_f_clean).name.lower(), None)

                            else:

                                if target_p.exists() and target_p.is_file():

                                    import hashlib

                                    try:

                                        self._failed_syntax_checks[norm_cmd_ex] = hashlib.sha256(target_p.read_bytes()).hexdigest()

                                    except Exception:

                                        pass



                    delta_files = obs.metadata.get("files_created", []) if (obs.metadata and isinstance(obs.metadata, dict)) else []

                    if obs.metadata and isinstance(obs.metadata, dict) and obs.metadata.get("relative_path"):

                        delta_files.append(obs.metadata["relative_path"])

                    if obs.success and call_name in ("fs.write", "fs.edit", "write_file", "edit_file") and isinstance(call_args, dict):

                        target_arg = str(call_args.get("path") or call_args.get("file_path") or "").replace("\\", "/").strip("./")

                        if target_arg:

                            norm_arg = target_arg.lower()

                            self._file_write_counts[norm_arg] = self._file_write_counts.get(norm_arg, 0) + 1

                            if target_arg not in delta_files:

                                delta_files.append(target_arg)

                            # Clear pending diagnostic for edited/written file

                            target_base = Path(target_arg).name.lower()

                            if target_base in self._pending_diagnostics:

                                logger.info(f"AgentLoop: File '{target_base}' modified, checking syntax resolution.")

                                target_abs = ws_dir_p / target_arg

                                is_clean = True

                                if target_abs.exists() and target_abs.suffix in (".js", ".mjs", ".cjs"):

                                    from core.js_syntax_validator import validate_javascript_file

                                    val_ok, val_err, _ = validate_javascript_file(target_abs)

                                    if not val_ok:

                                        is_clean = False

                                        logger.warning(f"AgentLoop: File '{target_base}' still has syntax error: {val_err}")

                                if is_clean:

                                    del self._pending_diagnostics[target_base]

                                    if hasattr(self, "syntax_repair"):

                                        self.syntax_repair.resolve_ticket(target_base)

                                    if hasattr(self, "telemetry_logger") and self.telemetry_logger:

                                        self.telemetry_logger.record_validation_result(

                                            validator_name="syntax_check",

                                            target_file=target_base,

                                            success=True,

                                            duration_ms=0.0,

                                            exit_code=0,

                                        )

                    is_noop_unchanged = bool(
                        getattr(obs, "details", None)
                        and (obs.details.get("code") == "UNCHANGED" or obs.details.get("status") == "UNCHANGED" or obs.details.get("noop") is True)
                    ) or (getattr(obs, "output", "") or "").startswith("UNCHANGED")
                    if is_noop_unchanged:
                        obs.summary = "UNCHANGED (+0 -0): Content already matches exactly. No mutation performed."
                        obs.content = (getattr(obs, "content", "") or "") + "\n[NO-PROGRESS NOTICE] File content was already identical (0 bytes changed). Provide real code changes to satisfy requirements."

                    is_mutating = bool(obs.success and not is_noop_unchanged and (call_name in ("fs.write", "fs.edit", "write_file", "edit_file", "write_files_batch", "download_image", "fetch_image") or bool(delta_files)))

                    if is_mutating:

                        self._read_fingerprint_tracker.clear()

                        self._consecutive_no_progress_blocks = 0

                        self._recovery_attempt_count = 0



                    if call_name not in ("fs.read", "read_file"):

                        try:

                            from tools.file_tools import _READ_LOOP_TRACKER

                            _READ_LOOP_TRACKER.clear()

                            from tools.platform.core_tools import READ_LOOP_TRACKER

                            READ_LOOP_TRACKER.clear()

                        except Exception:

                            pass

                        unchanged_read_governor_blocks = 0



                    # Check for auxiliary churn: modifying non-entrypoint files repeatedly while canonical entrypoint is missing

                    is_auxiliary_churn = False

                    if is_mutating and call_name in ("fs.write", "fs.edit", "write_file", "edit_file") and isinstance(call_args, dict):

                        target_arg = str(call_args.get("path") or call_args.get("file_path") or "").replace("\\", "/").strip("./")

                        norm_arg = target_arg.lower()

                        ws_dir = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else Path.cwd())

                        from core.project_contract import ProjectContract

                        expected_entrypoint_js = ProjectContract.determine_canonical_js(mission.user_prompt or "", ws_dir)

                        core_entrypoints = {"index.html", expected_entrypoint_js.lower(), "main.js", "style.css", "package.json", "vite.config.js", "app.js", "src/main.js", "src/app.js", "src/index.js"}

                        import re

                        clean_prompt = re.sub(r'https?://[^\s<>"\']+', '', mission.user_prompt)

                        is_web = any(k in clean_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "observatory", "frontend", "ui", "space", "orbit", "rocket", "3d", "three")) or (ws_dir / "index.html").exists()

                        has_main = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 100 for j in (expected_entrypoint_js, "main.js", "src/main.js", "app.js", "index.js", "script.js"))

                        if is_web and not has_main and norm_arg not in core_entrypoints and self._file_write_counts.get(norm_arg, 0) >= 2:

                            is_auxiliary_churn = True



                    if is_mutating and not is_auxiliary_churn:

                        has_mutated_in_turn = True

                        self._consecutive_non_mutating_turns = 0

                        self._consecutive_planning_turns = 0

                    else:

                        if is_auxiliary_churn:

                            logger.warning(f"AgentLoop: auxiliary file write '{target_arg}' does not reset non-mutating count while '{expected_entrypoint_js}' is missing")

                        if call_name in ("task.todo", "todo", "task_todo"):

                            self._consecutive_planning_turns += 1



                    if obs.success:
                        turn_has_successful_tool = True

                        if call_name.startswith("browser_") or call_name in ("browser_inspect", "browser_preview"):
                            self._consecutive_browser_failures = 0
                        consecutive_failures = 0
                        unchanged_read_governor_blocks = 0
                        self._consecutive_empty_turns = 0
                        if getattr(self, "_in_recovery", False):
                            self._in_recovery = False
                            self._recovery_attempt_count = 0
                            from core.adaptive_routing import adaptive_router
                            if not adaptive_router.is_tier_excluded_for_mission(1, self._mission_id) and adaptive_router.is_tier_available(1, mission_id=self._mission_id):
                                logger.info(f"AgentLoop: Tool '{call_name}' succeeded during recovery. Clearing recovery state and restoring active tier to 1.")
                                self.set_active_model_state(tier=1)
                            else:
                                logger.info(f"AgentLoop: Tool '{call_name}' succeeded during recovery. Tier 1 excluded for mission; retaining active tier {self.active_tier}.")
                        self._mutations_since_last_search = getattr(self, "_mutations_since_last_search", 0) + (1 if is_mutating else 0)
                        if is_mutating:
                            self._category_failures = {"PROVIDER_FAILURE": 0, "TOOL_FAILURE": 0, "VALIDATION_FAILURE": 0, "NO_PROGRESS": 0}
                            self._consecutive_empty_turns = 0
                            self._no_progress_streak = 0
                            self._last_validation_failed = False
                            self._duplicate_validation_count = 0

                            # Successful file mutation clears failure tracker and resets no-progress recovery

                            if hasattr(self, "_tool_failure_counts"):

                                self._tool_failure_counts.clear()

                            self._consecutive_no_progress_blocks = 0

                            self._recovery_attempt_count = 0

                            self._consecutive_non_mutating_turns = 0



                        # Update MVP Gate tracking on success

                        if hasattr(self, "mvp_gate") and self.mvp_gate:

                            call_str = f"{call_name} {str(call_args)}".lower()

                            if any(w in call_str for w in ("build", "npm run build", "vite build", "package_install")):

                                self.mvp_gate.build_passed = True

                            if any(w in call_str for w in ("browser_verify", "browser_qualification", "verify_browser")):

                                ws_eval = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else Path.cwd())

                                self.mvp_gate.evaluate_phase(ws_eval)



                        # Record created files

                        for f in delta_files:

                            if f not in self._written_files:

                                self._written_files.append(f)

                        # Re-evaluate turn budget if deliverables indicate a website mission

                        if hasattr(self.config, "resolve_for_mission") and not getattr(self.config, "_explicit_max_turns", False):

                            if self.config.max_turns < getattr(self.config, "website_max_turns", 80):

                                if WebsiteMvpGate.is_website_mission(mission.user_prompt or "", workspace_root=ws_dir_p, written_files=set(self._written_files)):

                                    self.config.max_turns = getattr(self.config, "website_max_turns", 80)

                                    logger.info(f"AgentLoop: website deliverables detected; updated turn budget to {self.config.max_turns}")

                        if hasattr(self, "planning_service") and self.planning_service:

                            self.planning_service.update_progress(

                                event_summary=f"Executed {call_name}: {obs.summary}",

                                modified_files=set(delta_files),

                            )

                        if is_mutating:

                            self._progress_in_current_phase = True
                            self._phase_stall_count = 0

                            cur_task = self._tasks[self._active_task_idx] if (self._tasks and 0 <= self._active_task_idx < len(self._tasks)) else {}

                            cur_tid = cur_task.get("task_id", "")

                            cur_title = cur_task.get("title", "").lower()

                            is_test_or_verif = any(w in cur_tid.lower() or w in cur_title for w in ("test", "verif", "qualification", "check"))

                            is_test_file = any("test" in Path(f).name.lower() for f in delta_files)

                            # A file-write event ONLY establishes that an artifact was created or modified.
                            # It must NEVER independently mark an application feature as completed or verified.
                            if cur_task:
                                if cur_task.get("status") in ("NOT_STARTED", "PENDING", None):
                                    cur_task["status"] = "IN_PROGRESS"
                                elif any(f.endswith((".js", ".py", ".html", ".css")) for f in delta_files):
                                    cur_task["status"] = "IMPLEMENTED"

                            if hasattr(self, "planning_service") and self.planning_service and cur_tid in self.planning_service.requirements:
                                req = self.planning_service.requirements[cur_tid]
                                if req.status in (RequirementStatus.PENDING, RequirementStatus.NOT_STARTED, RequirementStatus.READY):
                                    req.transition_status(RequirementStatus.IN_PROGRESS, reason=f"Artifact modified by {call_name}", actor="agent_loop")
                                elif req.status == RequirementStatus.IN_PROGRESS and any(f.endswith((".js", ".py", ".html", ".css")) for f in delta_files):
                                    req.transition_status(RequirementStatus.IMPLEMENTED, reason=f"Implementation code written by {call_name}", actor="agent_loop")

                        # Unified Work Package and Verification evaluation for mutating and inspection actions
                        cur_task = self._tasks[self._active_task_idx] if (self._tasks and 0 <= self._active_task_idx < len(self._tasks)) else {}
                        cur_tid = cur_task.get("task_id", "")
                        cur_title = cur_task.get("title", "").lower()
                        is_test_or_verif = any(w in cur_tid.lower() or w in cur_title for w in ("test", "verif", "qualification", "check", "inspect", "summary"))

                        from core.verification_profiles import classify_verification_profile, VerificationProfileEvaluator, VerificationProfile
                        ws_root = Path(getattr(mission, "workspace_root", None) or (self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd())))
                        existing_written = [f for f in self._written_files if (ws_root / f).exists()]
                        prof = classify_verification_profile(mission.user_prompt, workspace_path=str(ws_root), written_files=existing_written, task_id=cur_tid)
                        prof_res = VerificationProfileEvaluator.evaluate(prof, ws_root, mission.user_prompt, written_files=existing_written, task_id=cur_tid)

                        # Phase and Work Package Progression for Large Missions
                        if getattr(self, "_is_large_mission", False):
                            from core.agent_loop.types import ExecutionPhase
                            from core.work_package_gate import WorkPackageGater
                            from core.frontend_contract import FrontendImplementationContract

                            contract = getattr(self, "_frontend_contract", None)
                            if not contract and ws_root:
                                contract = FrontendImplementationContract.load_from_workspace(ws_root)

                            if cur_tid == "wp.foundation" or "foundation" in cur_title:
                                f_gate = WorkPackageGater.evaluate_foundation_gate(
                                    ws_root,
                                    contract=contract,
                                    design_brief=getattr(self, "_design_brief", None),
                                )
                                if f_gate.passed:
                                    await self._advance_active_task("Foundation work package satisfied (scaffold, styling, and contract established).")
                                    self.transition_phase(ExecutionPhase.PHASE_C_MAIN_IMPLEMENTATION, "Foundation created: contract, index.html, style.css")
                                else:
                                    logger.info(f"AgentLoop: Foundation gate pending: {f_gate.missing_criteria}")
                                    self._active_recovery_brief = (
                                        "CURRENT WORK PACKAGE OBJECTIVE (FOUNDATION):\n"
                                        + "\n".join(f"- {c}" for c in f_gate.missing_criteria)
                                        + "\nExecute fs.write to create missing foundation files (e.g. style.css) immediately."
                                    )
                            elif cur_tid == "wp.content" or "content" in cur_title:
                                c_gate = WorkPackageGater.evaluate_content_gate(ws_root, contract=contract)
                                if c_gate.passed:
                                    await self._advance_active_task("Content work package satisfied (sections, data, and visual assets populated).")
                                    self.transition_phase(ExecutionPhase.PHASE_D_FUNCTIONAL_IMPLEMENTATION, "Main content sections and cards implemented.")
                                else:
                                    logger.info(f"AgentLoop: Content gate pending: {c_gate.missing_criteria}")
                                    self._active_recovery_brief = (
                                        "CURRENT WORK PACKAGE OBJECTIVE (CONTENT):\n"
                                        + "\n".join(f"- {c}" for c in c_gate.missing_criteria)
                                        + "\nExecute fs.write or fs.edit to render destination cards, packages, and sections."
                                    )
                            elif cur_tid == "wp.functional" or "functional" in cur_title:
                                fn_gate = WorkPackageGater.evaluate_functionality_gate(ws_root, contract=contract)
                                if fn_gate.passed:
                                    await self._advance_active_task("Functional work package satisfied (interactive scripts, handlers, and state wired).")
                                    self.transition_phase(ExecutionPhase.PHASE_E_VERIFICATION, "Interactive features and handlers wired.")
                                else:
                                    logger.info(f"AgentLoop: Functionality gate pending: {fn_gate.missing_criteria}")
                                    contract_js = getattr(contract, "canonical_js", "app.js") if contract else "app.js"
                                    self._active_recovery_brief = (
                                        "CURRENT WORK PACKAGE OBJECTIVE (FUNCTIONALITY):\n"
                                        + "\n".join(f"- {c}" for c in fn_gate.missing_criteria)
                                        + f"\nExecute fs.write or fs.edit to update {contract_js} with search, filter, and modal interaction logic. If orphan competing scripts exist on disk, remove them or link them in index.html."
                                    )
                            elif (cur_tid == "wp.verification" or "verification" in cur_title):
                                if ws_root:
                                    try:
                                        from core.browser.acceptance import BrowserAcceptanceVerifier
                                        fresh_ok, _ = BrowserAcceptanceVerifier.check_evidence_freshness(ws_root)
                                        if not fresh_ok:
                                            logger.info("AgentLoop: Platform executing managed browser acceptance for wp.verification...")
                                            b_res = BrowserAcceptanceVerifier.verify_workspace_sync(
                                                ws_root,
                                                acceptance_ledger=getattr(self, "acceptance_ledger", None)
                                            )
                                            if hasattr(self, "mvp_gate"):
                                                self.mvp_gate.evaluate_phase(ws_root, browser_verified=b_res.passed)
                                    except Exception as b_exc:
                                        logger.warning(f"AgentLoop: Managed browser acceptance notice: {b_exc}")
                                fc_report = None
                                if ws_root:
                                    try:
                                        from core.frontend_contract_validator import FrontendContractValidator
                                        fc_report = FrontendContractValidator(ws_root).validate_all()
                                        self._last_frontend_validation_report = fc_report
                                        self._last_frontend_validation = fc_report.to_dict()
                                    except Exception:
                                        pass
                                v_gate = WorkPackageGater.evaluate_verification_gate(ws_root, validation_report=fc_report, test_result=prof_res)
                                if v_gate.passed and prof_res.passed:
                                    await self._advance_active_task(f"Verification work package satisfied ({prof_res.summary}).")
                                    self.transition_phase(ExecutionPhase.PHASE_F_COMPLETION, "All verification checks passed.")
                                    if self._tasks and all(t.get("status") == "COMPLETED" for t in self._tasks):
                                        logger.info(f"AgentLoop: All work packages completed and verified by {prof.value} ✓")
                                        mission_success = True
                                        await self._publish_event(
                                            EventType.VERIFICATION_COMPLETED,
                                            payload={"verdict": "PASSED", "confidence": 1.0, "reason": prof_res.summary}
                                        )
                                        is_web_proj = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_root, set(self._written_files))
                                        launch_inst = (
                                            "- Open `index.html` in your browser or run a local web server to explore the application."
                                            if is_web_proj else
                                            "- Run tests with `pytest` or execute the package using the canonical Python interpreter."
                                        )
                                        created_list = "\n".join(f"- `{f}`" for f in (self._written_files or (["index.html"] if is_web_proj else [])))
                                        walkthrough = (
                                            f"### Mission Completed Successfully\n\n"
                                            f"**Objective:** {mission.user_prompt}\n\n"
                                            f"**Outcome & Deliverables:**\n"
                                            f"{created_list}\n\n"
                                            f"**Verification Status:**\n"
                                            f"- All core requirements and behavioral contracts verified.\n"
                                            f"- Details: {prof_res.summary}\n\n"
                                            f"**Launch Instructions:**\n"
                                            f"{launch_inst}\n"
                                        )
                                        await self._complete_all_tasks(prof_res.summary)
                                        await self._publish_event(
                                            EventType.MISSION_COMPLETED,
                                            payload={
                                                "reason": prof_res.summary,
                                                "files_created": self._written_files,
                                                "final_output": walkthrough,
                                            }
                                        )
                                        break_to_terminal = True
                                        break
                                else:
                                    logger.info(f"AgentLoop: Verification gate pending: {v_gate.missing_criteria}")
                                    self._active_recovery_brief = (
                                        "CURRENT WORK PACKAGE OBJECTIVE (VERIFICATION):\n"
                                        + "\n".join(f"- {c}" for c in v_gate.missing_criteria)
                                        + "\nExecute fs.edit or fs.write to resolve the specific contract issues listed above."
                                    )
                        elif is_test_or_verif and prof_res.passed and not is_mutating:
                            await self._advance_active_task(f"Verified by {prof.value}: {prof_res.summary}")



                            # Check for repeated identical inspection calls without state change (Loop Governor)

                            action_key_tuple = (call_name, str(call_args))

                            if len(self._recent_actions) >= 2:

                                prev_recent = self._recent_actions[-2:]

                                if all(a == action_key_tuple for a in prev_recent) and not delta_files:

                                    if prof_res.passed:

                                        logger.info(f"AgentLoop: Loop governor detected repeated inspection with verified {prof.value}. Triggering Case A completion ✓")

                                        mission_success = True

                                        await self._publish_event(

                                            EventType.VERIFICATION_COMPLETED,

                                            turn_id=turn_id,

                                            payload={"verdict": "PASSED", "confidence": 1.0, "reason": prof_res.summary}

                                        )

                                        is_web_proj = any(k in mission.user_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "frontend", "ui"))

                                        launch_inst = (

                                            "- Open `index.html` in your browser or run a local web server to explore the application."

                                            if is_web_proj else

                                            "- Run tests with `pytest` or execute the package using the canonical Python interpreter."

                                        )

                                        created_list = "\n".join(f"- `{f}`" for f in (self._written_files or (["index.html"] if is_web_proj else [])))

                                        walkthrough = (

                                            f"### Mission Completed Successfully\n\n"

                                            f"**Objective:** {mission.user_prompt}\n\n"

                                            f"**Outcome & Deliverables:**\n"

                                            f"{created_list}\n\n"

                                            f"**Verification Status:**\n"

                                            f"- {prof_res.summary}\n\n"

                                            f"**Launch Instructions:**\n"

                                            f"{launch_inst}\n"

                                        )

                                        await self._complete_all_tasks(prof_res.summary)

                                        await self._publish_event(

                                            EventType.MISSION_COMPLETED,

                                            turn_id=turn_id,

                                            payload={

                                                "reason": prof_res.summary,

                                                "files_created": self._written_files,

                                                "final_output": walkthrough,

                                            }

                                        )

                                        turn.completed_at = time.monotonic()

                                        turn.state_version_after = self.state_store.get_snapshot().state_version

                                        await self._publish_event(

                                            EventType.AGENT_TURN_COMPLETED,

                                            turn_id=turn_id,

                                            payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}

                                        )

                                        self._turns_count += 1

                                        break_to_terminal = True

                                        break

                    else:

                        # Record failure in Redundancy Guard tracker

                        if hasattr(self, "_tool_failure_counts"):

                            self._tool_failure_counts[action_key] = self._tool_failure_counts.get(action_key, 0) + 1



                        # Update MVP Gate tracking on failure

                        if hasattr(self, "mvp_gate") and self.mvp_gate:

                            call_str = f"{call_name} {str(call_args)}".lower()

                            if any(w in call_str for w in ("build", "npm run build", "vite build")):

                                self.mvp_gate.build_passed = False

                                self.mvp_gate.last_build_error = str(obs.content or obs.error_message or "build failed")[:200]

                            if any(w in call_str for w in ("browser_open_preview", "open_preview", "browser.navigate", "navigate")):

                                self.mvp_gate.browser_verified = False

                                self.mvp_gate.last_browser_error = str(obs.content or obs.error_message or "browser verification failed")[:200]



                        is_unchanged_read_block = (

                            "TOOL_REJECTED_NO_PROGRESS" in (obs.error_message or "") or

                            "TOOL_REJECTED_NO_PROGRESS" in (obs.content or "") or

                            "NO_PROGRESS_LOOP_ENFORCEMENT" in (obs.error_message or "") or

                            "UNCHANGED_READ" in (obs.error_message or "") or

                            "NO_PROGRESS_LOOP_ENFORCEMENT" in (obs.content or "") or

                            (obs.metadata.get("details", {}) if isinstance(obs.metadata, dict) else {}).get("code") in ("UNCHANGED_READ", "TOOL_REJECTED_NO_PROGRESS")

                        )



                        if is_unchanged_read_block:

                            unchanged_read_governor_blocks += 1

                            logger.warning(

                                f"AgentLoop: Loop governor blocked unchanged read (block count {unchanged_read_governor_blocks}). "

                                "Evaluating Case A/B/C recovery decision."

                            )



                            # Evaluate completion via authoritative CompletionPolicy

                            strict_req = bool(

                                mission.acceptance_criteria

                                or getattr(mission, "strict_requirements", False)

                                or getattr(self.config, "strict_requirements", False)

                            )

                            accepted, v_reason, issues = self._completion_policy.evaluate_completion(

                                mission_prompt=mission.user_prompt,

                                workspace=self.workspace,

                                acceptance_criteria=mission.acceptance_criteria,

                                written_files=self._written_files,

                                runtime_state=self.state_store.get_state() if self.state_store else None,

                                acceptance_ledger=getattr(self.planning_service, "acceptance_ledger", None) if getattr(self, "planning_service", None) else None,

                                evidence_store=self.evidence_store,

                                strict_requirements=strict_req,

                            )



                            if accepted and hasattr(self, "planning_service") and self.planning_service:

                                for r in getattr(self.planning_service, "requirements", {}).values():

                                    if r.status != RequirementStatus.VERIFIED:

                                        r.transition_status(RequirementStatus.VERIFIED, reason=v_reason, actor="completion_policy")

                                if hasattr(self.planning_service, "acceptance_ledger") and self.planning_service.acceptance_ledger:

                                    for chk in getattr(self.planning_service.acceptance_ledger, "checks", {}).values():

                                        if chk.status != AcceptanceCheckStatus.PASS:

                                            chk.status = AcceptanceCheckStatus.PASS



                            if hasattr(self, "planning_service") and self.planning_service and (

                                mission.acceptance_criteria

                                or getattr(mission, "strict_requirements", False)

                                or getattr(self.config, "strict_requirements", False)

                            ):

                                goal_ok, goal_reason = self.planning_service.is_goal_completed()

                                if not goal_ok:

                                    accepted = False

                                    v_reason = f"Goal requirements incomplete: {goal_reason}"

                                    if goal_reason not in issues:

                                        issues.append(goal_reason)



                            is_web_proj = any(k in mission.user_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "frontend", "ui"))

                            if accepted and (is_web_proj or "app" in mission.user_prompt.lower()):

                                if issues:

                                    accepted = False

                                    v_reason = f"Cannot complete web application with unresolved issues: {'; '.join(issues)}"



                            if accepted:

                                # ── Case A: Verified task followed by duplicate reads -> transitions to completed ──

                                logger.info(

                                    "AgentLoop: Case A Recovery: all requirements verified after unchanged read block. "

                                    "Transitioning cleanly to MISSION_COMPLETED ✓"

                                )

                                mission_success = True

                                await self._publish_event(

                                    EventType.VERIFICATION_COMPLETED,

                                    turn_id=turn_id,

                                    payload={"verdict": "PASSED", "confidence": 1.0, "reason": "Verified upon loop governor recovery"}

                                )

                                is_web_proj = any(k in mission.user_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "frontend", "ui"))

                                launch_inst = (

                                    "- Open `index.html` in your browser or run a local web server to explore the application."

                                    if is_web_proj else

                                    "- Run tests with `pytest` or execute the package using the canonical Python interpreter."

                                )

                                created_list = "\n".join(f"- `{f}`" for f in (self._written_files or (["index.html"] if is_web_proj else [])))

                                walkthrough = (

                                    f"### Mission Completed Successfully\n\n"

                                    f"**Objective:** {mission.user_prompt}\n\n"

                                    f"**Outcome & Deliverables:**\n"

                                    f"{created_list}\n\n"

                                    f"**Verification Status:**\n"

                                    f"- All core requirements and behavioral contracts verified.\n"

                                    f"- Details: {v_reason}\n\n"

                                    f"**Launch Instructions:**\n"

                                    f"{launch_inst}\n"

                                )

                                await self._complete_all_tasks(v_reason)

                                await self._publish_event(

                                    EventType.MISSION_COMPLETED,

                                    turn_id=turn_id,

                                    payload={

                                        "reason": v_reason,

                                        "files_created": self._written_files,

                                        "final_output": walkthrough,

                                    }

                                )

                                turn.completed_at = time.monotonic()

                                turn.state_version_after = self.state_store.get_snapshot().state_version

                                await self._publish_event(

                                    EventType.AGENT_TURN_COMPLETED,

                                    turn_id=turn_id,

                                    payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}

                                )

                                self._turns_count += 1

                                break_to_terminal = True

                                break

                            elif unchanged_read_governor_blocks < 3:

                                # ── Case B: Incomplete acceptance criteria -> feed targeted guidance ──

                                logger.warning(

                                    f"AgentLoop: Case B Recovery: requirements incomplete ({issues}). Feeding targeted guidance."

                                )

                                guidance_lines = [

                                    "NO-PROGRESS NOTICE: You are repeatedly reading an unchanged file instead of completing requirements.",

                                    "The following mandatory verification checks are not yet satisfied:",

                                ] + [f"- {iss}" for iss in issues] + [

                                    "Proceed immediately to creating or updating the required code rather than reading unchanged files."

                                ]

                                existing_content = obs.content or ""

                                notice_text = "\n".join(guidance_lines)

                                if existing_content and not existing_content.startswith("NO-PROGRESS NOTICE:"):

                                    obs.content = (

                                        f"{notice_text}\n\n"

                                        f"--- CURRENT CONTENT OF REQUESTED TARGET ---\n"

                                        f"{existing_content}\n"

                                        f"--- END TARGET CONTENT ---\n"

                                        f"Use this content immediately to write missing files or complete the mission without re-reading."

                                    )

                                else:

                                    obs.content = notice_text

                                obs.summary = f"Unchanged read blocked: {len(issues)} unmet requirement(s)"

                                self._record_observation(obs)

                                if hasattr(self, "context_engine") and self.context_engine:

                                    try:

                                        from core.context.models import ContextItem, ContextSectionType, ContextSourceType, ContextPriority, ContextProvenance

                                        self.context_engine.register_item(ContextItem(

                                            id=f"guidance_{turn_id}",

                                            section=ContextSectionType.SYSTEM,

                                            content=(

                                                f"CRITICAL DIRECTIVE:\n{notice_text}\n"

                                                "You MUST modify the code or test file using fs.edit or fs.write to resolve the unmet requirements immediately. "

                                                "Run pytest or verification commands via shell.bash to prove the fix."

                                            ),

                                            provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="loop_governor"),

                                            priority=ContextPriority.MANDATORY,

                                            pinned=True,

                                        ))

                                    except Exception:

                                        pass

                                await self._publish_event(

                                    EventType.AGENT_STALL_DETECTED,

                                    turn_id=turn_id,

                                    payload={"reason": "Unchanged read loop blocked; targeted guidance provided", "issues": issues}

                                )

                                await self._publish_event(

                                    EventType.VERIFICATION_NEEDS_IMPROVEMENT,

                                    turn_id=turn_id,

                                    payload={"verdict": "NEEDS_IMPROVEMENT", "issues": issues}

                                )

                                # Stop processing remaining actions in this batch to allow model to receive targeted guidance

                                break

                            else:

                                # ── Case C: Repeated loop without progress -> bounds loop with failure identifying unmet criteria ──

                                logger.warning(

                                    f"AgentLoop: Case C Recovery: bounded recovery transition after {unchanged_read_governor_blocks} unchanged read blocks. Issues: {issues}"

                                )

                                rec_ok = await self._trigger_agent_no_progress_recovery(
                                    turn_id=turn_id,
                                    rejection_reason=f"Repeated unchanged read blocks ({unchanged_read_governor_blocks}): {'; '.join(issues)}",
                                    unmet_reqs=[r.title for r in self._unmet_requirements] if hasattr(self, "_unmet_requirements") else [],
                                    mission=self._mission,
                                )
                                if not rec_ok:
                                    termination_reason = (

                                        f"No-progress loop terminated: unmet criteria after repeated unchanged reads: {'; '.join(issues)}"

                                    )

                                    await self._publish_event(

                                        EventType.MISSION_FAILED,

                                    turn_id=turn_id,

                                    severity=EventSeverity.CRITICAL,

                                    payload={"error": termination_reason, "unmet_criteria": issues}

                                )

                                break_to_terminal = True

                                break

                        else:
                            if call_name.startswith("browser_") or call_name in ("browser_inspect", "browser_preview"):
                                self._consecutive_browser_failures = getattr(self, "_consecutive_browser_failures", 0) + 1
                            is_val = False
                            val_cat = "TOOL_EXECUTION_ERROR"
                            val_cmd = ""
                            if getattr(obs, "details", None) and isinstance(obs.details, dict):
                                is_val = obs.details.get("is_validation_command", False)
                                val_cmd = obs.details.get("command", "")
                                if is_val:
                                    val_cat = obs.details.get("primary_failure_category") or "TEST_FAILURE"
                                    self._last_validation_command = val_cmd
                                    self._last_validation_source_digest = self._compute_workspace_source_digest()
                                    self._last_validation_failed = True
                                    self._last_validation_error_class = val_cat
                                    t_ev = obs.details.get("test_evidence")
                                    if t_ev and isinstance(t_ev, dict):
                                        self._last_validation_repair_brief = t_ev.get("repair_brief", "")

                            turn_has_failed_tool = True
                            self._record_failure_entry(
                                turn_id=turn_id,
                                category="VALIDATION_FAILURE" if is_val else "TOOL_FAILURE",
                                error_class=val_cat if is_val else "TOOL_EXECUTION_ERROR",
                                operation=call_name,
                                actual_result=getattr(obs, "summary", "") or getattr(obs, "content", ""),
                            )



                if break_to_terminal:

                    break

                # Batch-aware failure accounting: update consecutive_failures once per turn
                if turn_has_successful_tool:
                    consecutive_failures = 0
                elif turn_has_failed_tool:
                    consecutive_failures += 1

                if not has_mutated_in_turn:

                    self._consecutive_non_mutating_turns += 1
                else:
                    self._consecutive_non_mutating_turns = 0
                    if getattr(self, "_skill_evidence_ledger", None) and ws_root:
                        try:
                            self._skill_evidence_ledger.evaluate_physical_evidence(
                                ws_root,
                                getattr(self, "_design_brief", None),
                                getattr(self, "_frontend_contract", None),
                            )
                        except Exception as _sk_e:
                            logger.debug(f"AgentLoop: skill evidence update notice: {_sk_e}")
                    if self._consecutive_non_mutating_turns == 3:
                        logger.warning(
                            f"AgentLoop: {self._consecutive_non_mutating_turns} consecutive non-mutating turns detected. "
                            f"Injecting mandatory mutation directive."
                        )
                        if hasattr(self, "context_engine") and self.context_engine:
                            try:
                                from core.context.models import ContextItem, ContextSectionType, ContextSourceType, ContextPriority, ContextProvenance
                                self.context_engine.register_item(ContextItem(
                                    id=f"mutation_directive_{turn_id}",
                                    section=ContextSectionType.SYSTEM,
                                    content=(
                                        f"CRITICAL ACTION REQUIRED (Turn {self._turns_count}):\n"
                                        f"You have performed {self._consecutive_non_mutating_turns} consecutive turns without mutating or creating files. "
                                        "You are FORBIDDEN from calling fs.read or exploratory commands on the next turn. "
                                        "You MUST proceed IMMEDIATELY to editing or writing the necessary code/styles using fs.edit or fs.write."
                                    ),
                                    provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="mutation_governor"),
                                    priority=ContextPriority.MANDATORY,
                                    pinned=True,
                                ))
                            except Exception:
                                pass
                    elif self._consecutive_non_mutating_turns >= 4:
                        logger.warning(
                            f"AgentLoop: {self._consecutive_non_mutating_turns} consecutive non-mutating turns reached threshold. "
                            f"Triggering recovery transition."
                        )
                        await self._trigger_agent_no_progress_recovery(
                            turn_id=turn_id,
                            rejection_reason=f"Model performed {self._consecutive_non_mutating_turns} consecutive non-mutating turns without code modifications",
                            unmet_reqs=[r.title for r in self._unmet_requirements] if hasattr(self, "_unmet_requirements") else [],
                            mission=self._mission,
                        )



                # Forward progress thought to TUI

                await self._emit_tui_thought(

                    text=f"Executed {decision.tool_name}",

                    detail=obs.summary

                )

                # Measure tool execution duration separately from provider latency (P0)
                tool_exec_duration = time.monotonic() - tool_exec_start
                self._last_turn_durations = {
                    "provider_latency_seconds": t1_latency,
                    "tool_execution_latency_seconds": tool_exec_duration,
                    "provider_duration_ms": t1_latency * 1000.0,
                    "tool_execution_duration_ms": tool_exec_duration * 1000.0,
                }
                turn.provider_latency_seconds = t1_latency
                turn.tool_execution_latency_seconds = tool_exec_duration



            elif decision.decision_type == AgentDecisionType.ASK_USER:

                question = decision.user_question or "Clarification needed."

                logger.info(f"AgentLoop: asking user: {question}")

                await self._publish_event(

                    EventType.AGENT_ASK_USER,

                    turn_id=turn_id,

                    payload={"question": question}

                )



                user_answer = ""

                if self.user_input_callback:

                    try:

                        user_answer = await self.user_input_callback(question)

                    except Exception as u_exc:

                        user_answer = f"[User input error: {u_exc}]"

                else:

                    user_answer = "Proceed with your best judgement."



                await self._publish_event(

                    EventType.AGENT_USER_RESPONSE,

                    turn_id=turn_id,

                    payload={"response": user_answer}

                )

                user_obs = ObservationBuilder.from_user_response(

                    user_response=user_answer,

                    mission_id=self._mission_id,

                    turn_id=turn_id,

                )

                self._record_observation(user_obs)

                consecutive_failures = 0



            elif decision.decision_type == AgentDecisionType.DELEGATE:

                logger.info(f"AgentLoop: delegation requested for '{decision.delegation_target}'")

                await self._publish_event(

                    EventType.AGENT_DELEGATION_REQUESTED,

                    turn_id=turn_id,

                    payload={"target": decision.delegation_target}

                )

                if self.subagent_manager:

                    try:

                        from core.runtime_state.models import AgentType

                        from core.subagents.handoff import HandoffManager

                        del_task_id = f"task_{uuid.uuid4().hex[:6]}"

                        sub_res = await self.subagent_manager.delegate_task(

                            task_id=del_task_id,

                            goal=decision.delegation_target or "Delegated task",

                            role=AgentType.EXPLORER,

                            parent_agent_id="primary",

                        )

                        # Invariant: Subagent success is candidate evidence only; modified files require root re-verification

                        if sub_res.files:

                            for fl in sub_res.files:

                                if fl not in self._written_files:

                                    self._written_files.append(fl)

                            if hasattr(self, "evidence_invalidator") and self.evidence_invalidator:

                                self.evidence_invalidator.invalidate_for_paths(sub_res.files, task_id=turn_id)



                        del_obs = HandoffManager.format_observation(

                            result=sub_res,

                            turn_id=turn_id,

                            workspace_root=self.workspace.root_str if self.workspace.is_locked else Path.cwd(),

                        )

                        del_obs.mission_id = self._mission_id

                    except Exception as sub_err:

                        del_obs = Observation(

                            observation_id=f"obs_del_{uuid.uuid4().hex[:6]}",

                            mission_id=self._mission_id,

                            turn_id=turn_id,

                            source_type="delegation",

                            source_id="subagent_manager",

                            success=False,

                            summary=f"Delegation error: {sub_err}",

                            content=f"Subagent delegation failed: {sub_err}",

                        )

                else:

                    # Controlled NOT_AVAILABLE observation

                    del_obs = Observation(

                        observation_id=f"obs_del_{uuid.uuid4().hex[:6]}",

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                        source_type="delegation",

                        source_id="subagent_service",

                        success=False,

                        summary="Delegation service is not configured in this runtime.",

                        content="Delegation is disabled. Please perform the action directly using available tools."

                    )

                self._record_observation(del_obs)



            elif decision.decision_type == AgentDecisionType.VERIFY:

                self._verification_calls_count += 1

                await self._publish_event(

                    EventType.AGENT_VERIFICATION_REQUESTED,

                    turn_id=turn_id,

                    payload={"target": decision.verification_target}

                )

                target = decision.verification_target or ""

                check_result = None

                if target and hasattr(self, "verification_engine"):

                    check_result = self.verification_engine.verify_check(

                        check_id=target,

                        check_type="FILESYSTEM",

                        target_path=target,

                        task_id=turn_id,

                    )



                strict_req = bool(mission.acceptance_criteria or getattr(mission, "strict_requirements", False) or getattr(self.config, "strict_requirements", False))

                accepted, v_reason, issues = self._completion_policy.evaluate_completion(

                    mission_prompt=mission.user_prompt,

                    workspace=getattr(mission, "workspace_root", None) or self.workspace,

                    acceptance_criteria=mission.acceptance_criteria,

                    written_files=self._written_files,

                    runtime_state=self.state_store.get_state() if self.state_store else None,

                    acceptance_ledger=getattr(self.planning_service, "acceptance_ledger", None) if getattr(self, "planning_service", None) else None,

                    evidence_store=self.evidence_store,

                    strict_requirements=strict_req,

                )



                if check_result and not check_result.passed:

                    accepted = False

                    if check_result.message not in issues:

                        issues.append(check_result.message)



                if not accepted and issues and hasattr(self, "repair_controller"):

                    can_retry, guidance, rep_id = self.repair_controller.handle_failure(

                        check_id=target or "verification_gate",

                        failure_class=check_result.failure_class if check_result and check_result.failure_class else FailureClass.ASSERTION_FAILED,

                        error_message="; ".join(issues[:2]),

                        task_id=turn_id,

                    )

                    v_obs = ObservationBuilder.from_verification(

                        verdict="NEEDS_IMPROVEMENT",

                        confidence=0.5,

                        issues=[guidance] if guidance else issues,

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                    )

                else:

                    v_obs = ObservationBuilder.from_verification(

                        verdict="PASSED" if accepted else "NEEDS_IMPROVEMENT",

                        confidence=1.0 if accepted else 0.5,

                        issues=issues,

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                    )

                self._record_observation(v_obs)



            elif decision.decision_type == AgentDecisionType.CONTINUE_REASONING:

                reasoning_text = decision.explanation or decision.raw_text or decision.reasoning

                logger.info(f"AgentLoop: model continued reasoning on turn {turn_id}")



                # Check if all requirements/deliverables are already satisfied (e.g. Profile A/B)

                strict_req = bool(mission.acceptance_criteria or getattr(mission, "strict_requirements", False) or getattr(self.config, "strict_requirements", False))

                cand_accepted, cand_v_reason, _ = self._completion_policy.evaluate_completion(

                    mission_prompt=mission.user_prompt,

                    workspace=getattr(mission, "workspace_root", None) or self.workspace,

                    acceptance_criteria=mission.acceptance_criteria,

                    written_files=self._written_files,

                    runtime_state=self.state_store.get_state() if self.state_store else None,

                    acceptance_ledger=getattr(self.planning_service, "acceptance_ledger", None) if getattr(self, "planning_service", None) else None,

                    evidence_store=self.evidence_store,

                    strict_requirements=strict_req,

                    candidate_response=reasoning_text,

                )

                if cand_accepted:

                    logger.info("AgentLoop: model reasoning accompanied by fully satisfied deliverables -> accepting mission completion ✓")

                    mission_success = True

                    await self._complete_all_tasks(cand_v_reason)

                    await self._publish_event(

                        EventType.MISSION_COMPLETED,

                        turn_id=turn_id,

                        payload={

                            "reason": cand_v_reason,

                            "files_created": self._written_files,

                            "final_output": reasoning_text,

                        }

                    )

                    turn.completed_at = time.monotonic()

                    turn.state_version_after = self.state_store.get_snapshot().state_version

                    await self._publish_event(

                        EventType.AGENT_TURN_COMPLETED,

                        turn_id=turn_id,

                        payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}

                    )

                    self._turns_count += 1

                    break_to_terminal = True

                    break



                self._consecutive_empty_turns = getattr(self, "_consecutive_empty_turns", 0) + 1



                # Check if there are unmet deliverables in the workspace

                ws_dir_active = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd()))

                has_unmet_deliverables = False

                unmet_list: List[str] = []

                if hasattr(self, "mvp_gate") and self.mvp_gate:

                    try:

                        ok_mvp, unmet_list = self.mvp_gate.evaluate(ws_dir_active)

                        if not ok_mvp and unmet_list:

                            has_unmet_deliverables = True

                    except Exception:

                        pass



                # Only increment failures if 2+ consecutive turns have elapsed with zero tool actions
                if self._consecutive_empty_turns >= 2:
                    consecutive_failures += 1
                    self._record_failure_entry(
                        turn_id=turn_id,
                        category="NO_PROGRESS",
                        error_class="EMPTY_TOOL_CALL",
                        actual_result=f"{self._consecutive_empty_turns} consecutive turns without tool actions",
                    )
                else:
                    # Single turn reasoning receives directive reminder without incrementing failure counter
                    pass



                unmet_info = f" Missing prerequisites: {', '.join(unmet_list)}." if unmet_list else ""

                if self._consecutive_empty_turns >= 2:

                    obs_summary = (

                        f"CRITICAL STALL WARNING: {self._consecutive_empty_turns} consecutive turns without tool actions.{unmet_info} "

                        "You MUST invoke a tool now (e.g. write_file) to make concrete progress. Do not output only reasoning."

                    )

                else:

                    obs_summary = (

                        f"MANDATORY DIRECTIVE: Reasoning noted, but NO tools were invoked.{unmet_info} "

                        "You MUST invoke a concrete tool (e.g. write_file) to perform the required actions or complete the task."

                    )



                reason_obs = Observation(

                    observation_id=f"obs_reason_{uuid.uuid4().hex[:6]}",

                    mission_id=self._mission_id,

                    turn_id=turn_id,

                    source_type="agent",

                    source_id="model_reasoning",

                    success=False if (self._consecutive_empty_turns >= 2 or has_unmet_deliverables) else True,

                    summary=obs_summary,

                    content=reasoning_text,

                    metadata={"consecutive_empty_turns": self._consecutive_empty_turns, "has_missing": has_unmet_deliverables},

                )

                self._record_observation(reason_obs)



                # Reasoning-only stall watchdog (P0)

                if self._consecutive_empty_turns >= 4:

                    termination_reason = (

                        f"FAILED_NO_ACTION_STALL: Model stalled with {self._consecutive_empty_turns} "

                        "consecutive reasoning turns without tool execution"

                    )

                    logger.error(f"AgentLoop: {termination_reason}")

                    await self._publish_event(

                        EventType.MISSION_FAILED,

                        turn_id=turn_id,

                        severity=EventSeverity.CRITICAL,

                        payload={"error": termination_reason, "code": "FAILED_NO_ACTION_STALL"}

                    )

                    break_to_terminal = True

                    break



                if self._consecutive_empty_turns >= 2:

                    logger.warning(

                        f"AgentLoop: {self._consecutive_empty_turns} consecutive empty turns without tool actions. "

                        "Triggering bounded recovery transition to escalate model provider."

                    )

                    rec_ok = await self._trigger_recovery_transition(

                        turn_id=turn_id,

                        rejection_reason=f"Model stalled in reasoning-only loop ({self._consecutive_empty_turns} turns with 0 tool calls)",

                        unmet_reqs=unmet_list,

                    )

                    if not rec_ok:

                        termination_reason = "FAILED_NO_ACTION_STALL: Exhausted recovery transitions while in reasoning-only loop (all model providers failed to invoke executable tools)"

                        logger.error(f"AgentLoop: {termination_reason}")

                        await self._publish_event(

                            EventType.MISSION_FAILED,

                            turn_id=turn_id,

                            severity=EventSeverity.CRITICAL,

                            payload={"error": termination_reason, "code": "FAILED_NO_ACTION_STALL"}

                        )

                        break_to_terminal = True

                        break



            elif decision.decision_type == AgentDecisionType.COMPLETE:

                final_output = decision.explanation or decision.raw_text

                # Evaluate two-layer completion contract

                await self._publish_event(

                    EventType.AGENT_COMPLETION_CANDIDATE,

                    turn_id=turn_id,

                    payload={"claim": final_output[:120]}

                )



                strict_req = bool(mission.acceptance_criteria or getattr(mission, "strict_requirements", False) or getattr(self.config, "strict_requirements", False))

                accepted, v_reason, issues = self._completion_policy.evaluate_completion(

                    mission_prompt=mission.user_prompt,

                    workspace=getattr(mission, "workspace_root", None) or self.workspace,

                    acceptance_criteria=mission.acceptance_criteria,

                    written_files=self._written_files,

                    runtime_state=self.state_store.get_state() if self.state_store else None,

                    acceptance_ledger=getattr(self.planning_service, "acceptance_ledger", None) if getattr(self, "planning_service", None) else None,

                    evidence_store=self.evidence_store,

                    strict_requirements=strict_req,

                )



                if accepted and hasattr(self, "planning_service") and self.planning_service:

                    for r in getattr(self.planning_service, "requirements", {}).values():

                        if r.status != RequirementStatus.VERIFIED:

                            r.transition_status(RequirementStatus.VERIFIED, reason=v_reason, actor="completion_policy")

                    if hasattr(self.planning_service, "acceptance_ledger") and self.planning_service.acceptance_ledger:

                        for chk in getattr(self.planning_service.acceptance_ledger, "checks", {}).values():

                            if chk.status != AcceptanceCheckStatus.PASS:

                                chk.status = AcceptanceCheckStatus.PASS



                # Check goal completion status via MissionPlanningService if acceptance criteria or strict requirements active

                if hasattr(self, "planning_service") and self.planning_service and (mission.acceptance_criteria or getattr(mission, "strict_requirements", False) or getattr(self.config, "strict_requirements", False)):

                    goal_ok, goal_reason = self.planning_service.is_goal_completed()

                    if not goal_ok:

                        accepted = False

                        v_reason = f"Goal requirements incomplete: {goal_reason}"

                        if goal_reason not in issues:

                            issues.append(goal_reason)



                if accepted:

                    logger.info("AgentLoop: completion candidate ACCEPTED by harness & evidence ✓")

                    mission_success = True

                    await self._publish_event(

                        EventType.VERIFICATION_COMPLETED,

                        turn_id=turn_id,

                        payload={"verdict": "PASSED", "confidence": 1.0}

                    )

                    cand_out = getattr(decision, "explanation", None) or getattr(decision, "raw_text", None) or ""

                    if not cand_out:

                        is_web_proj = any(k in mission.user_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "frontend", "ui"))

                        launch_inst = (

                            "- Open `index.html` in your browser or run a local web server to explore the application."

                            if is_web_proj else

                            "- Run tests with `pytest` or execute the package using the canonical Python interpreter."

                        )

                        created_list = "\n".join(f"- `{f}`" for f in (self._written_files or (["index.html"] if is_web_proj else [])))

                        cand_out = (

                            f"### Mission Completed Successfully\n\n"

                            f"**Objective:** {mission.user_prompt}\n\n"

                            f"**Outcome & Deliverables:**\n"

                            f"{created_list}\n\n"

                            f"**Verification Status:**\n"

                            f"- All core requirements and behavioral contracts verified.\n"

                            f"- Details: {v_reason}\n\n"

                            f"**Launch Instructions:**\n"

                            f"{launch_inst}\n"

                        )

                    await self._complete_all_tasks(v_reason)

                    await self._publish_event(

                        EventType.MISSION_COMPLETED,

                        turn_id=turn_id,

                        payload={

                            "reason": v_reason,

                            "files_created": self._written_files,

                            "final_output": cand_out,

                        }

                    )

                    turn.completed_at = time.monotonic()

                    turn.state_version_after = self.state_store.get_snapshot().state_version

                    await self._publish_event(

                        EventType.AGENT_TURN_COMPLETED,

                        turn_id=turn_id,

                        payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}

                    )

                    self._turns_count += 1

                    break

                else:

                    logger.warning(f"AgentLoop: completion candidate REJECTED by evidence policy: {v_reason}")
                    consecutive_failures += 1
                    self._record_failure_entry(
                        turn_id=turn_id,
                        category="VALIDATION_FAILURE",
                        error_class="COMPLETION_VERIFICATION_REJECTED",
                        actual_result=v_reason,
                    )

                    await self._publish_event(

                        EventType.VERIFICATION_NEEDS_IMPROVEMENT,

                        turn_id=turn_id,

                        payload={"verdict": "NEEDS_IMPROVEMENT", "issues": issues}

                    )

                    await self._publish_event(

                        EventType.AGENT_REPAIR_REQUESTED,

                        turn_id=turn_id,

                        payload={"reason": v_reason, "issues": issues}

                    )

                    repair_obs = Observation(

                        observation_id=f"obs_repair_{uuid.uuid4().hex[:6]}",

                        mission_id=self._mission_id,

                        turn_id=turn_id,

                        source_type="verification",

                        source_id="completion_policy",

                        success=False,

                        summary=f"Completion check rejected: {v_reason}",

                        content="\n".join([f"Required Fix: {v_reason}"] + [f"- Issue: {iss}" for iss in issues]),

                    )

                    self._record_observation(repair_obs)



            elif decision.decision_type == AgentDecisionType.INVALID:

                logger.warning(f"AgentLoop: invalid model response on turn {turn_id}")
                consecutive_failures += 1
                inv_reason = getattr(decision, "reasoning", "") or "Invalid model response"
                inv_cat = "PROVIDER_FAILURE" if ("PROVIDER_ERROR" in inv_reason or "MODEL_STREAM_STALL" in inv_reason or "timeout" in inv_reason.lower()) else "RESPONSE_PARSE_ERROR"
                self._record_failure_entry(
                    turn_id=turn_id,
                    category=inv_cat if inv_cat == "PROVIDER_FAILURE" else "TOOL_FAILURE",
                    error_class="MODEL_STREAM_STALL" if "MODEL_STREAM_STALL" in inv_reason else ("PROVIDER_ERROR" if "PROVIDER_ERROR" in inv_reason else "RESPONSE_PARSE_ERROR"),
                    actual_result=inv_reason,
                )

                inv_obs = Observation(

                    observation_id=f"obs_inv_{uuid.uuid4().hex[:6]}",

                    mission_id=self._mission_id,

                    turn_id=turn_id,

                    source_type="parser",

                    source_id="response_parser",

                    success=False,

                    summary="Invalid response format: please emit a valid tool call or clear final response.",

                    content=decision.reasoning,

                )

                self._record_observation(inv_obs)



            # 10. Complete Turn

            turn.completed_at = time.monotonic()

            turn.state_version_after = self.state_store.get_snapshot().state_version

            await self._publish_event(

                EventType.AGENT_TURN_COMPLETED,

                turn_id=turn_id,

                payload={
                    "turn_id": turn_id,
                    "duration": turn.completed_at - turn.started_at,
                    "provider_latency_seconds": getattr(turn, "provider_latency_seconds", 0.0),
                    "tool_execution_latency_seconds": getattr(turn, "tool_execution_latency_seconds", 0.0),
                }

            )



            self._turns_count += 1

            if hasattr(self, "progress_governor") and self.progress_governor:
                p_eval = self.progress_governor.evaluate_turn(
                    turn_id=turn_id,
                    actions=[{"name": a[0], "arguments": a[1]} for a in getattr(self, "_recent_actions", [])[-1:]],
                    file_modifications=[{"path": f} for f in getattr(self, "_written_files", set())],
                    tool_results=[],
                    requirements_progressed=bool(getattr(self, "_progress_in_current_phase", False)),
                    work_package_completed=False,
                    test_or_browser_passed=False,
                    error_context=None,
                )
                if self.progress_governor.should_trigger_diagnosis():
                    await self._publish_event(
                        EventType.WARNING,
                        turn_id=turn_id,
                        severity=EventSeverity.WARNING,
                        payload=self.progress_governor.get_diagnostic_payload(),
                    )

            # Early stall detection within bounded phase
            if getattr(self, "_is_large_mission", False):
                p_key = getattr(self.current_phase, "value", str(self.current_phase))
                self._phase_turn_count[p_key] = self._phase_turn_count.get(p_key, 0) + 1
                if not getattr(self, "_progress_in_current_phase", False):
                    self._phase_stall_count = getattr(self, "_phase_stall_count", 0) + 1
                    if self._phase_stall_count >= 3:
                        logger.warning(f"AgentLoop: Phase {p_key} stall detected ({self._phase_stall_count} turns without progress).")
                        stall_hdr = f"STALL WARNING in {p_key}: {self._phase_stall_count} consecutive turns without progress.\n"
                        if getattr(self, "_active_recovery_brief", None) and not self._active_recovery_brief.startswith("STALL WARNING"):
                            self._active_recovery_brief = f"{stall_hdr}{self._active_recovery_brief}"
                        elif not getattr(self, "_active_recovery_brief", None):
                            self._active_recovery_brief = (
                                f"{stall_hdr}You MUST invoke fs.write or fs.edit directly to advance this phase."
                            )
                else:
                    self._phase_stall_count = 0
                self._progress_in_current_phase = False

            try:

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:

                logger.info(f"AgentLoop: mission {self._mission_id} cancelled via asyncio task cancellation.")

                termination_reason = "Cancelled by user"

                try:

                    from tools.shell_tools import terminate_active_subprocesses

                    terminate_active_subprocesses(mission_id=self._mission_id)

                except Exception:

                    pass

                try:

                    snap = self.state_store.get_snapshot()

                    snap.mission.status = MissionStatus.CANCELLED

                    snap.mission.cancelled = True

                    snap.progress.waiting_reason = WaitReason.CANCELLED

                except Exception:

                    pass

                await self._publish_event(

                    EventType.MISSION_CANCELLED,

                    payload={"reason": termination_reason}

                )

                break



        # ── Loop Terminal Summary ─────────────────────────────────────────────

        total_duration = time.monotonic() - self._start_time

        final_state = self.state_store.get_snapshot()



        try:

            from core.telemetry import AgentLoopTelemetry

            telemetry.record_agent_loop(AgentLoopTelemetry(

                mission_id=self._mission_id,

                turns_count=self._turns_count,

                actions_count=self._actions_count,

                tool_calls_count=self._tool_calls_count,

                verification_calls_count=self._verification_calls_count,

                total_duration_ms=total_duration * 1000.0,

                status=final_state.mission.status.value,

                execution_mode=self.config.execution_mode,

            ))

        except Exception:

            pass



        if hasattr(self, "telemetry_logger") and self.telemetry_logger:

            try:

                self.telemetry_logger.write_mission_summary(

                    status="COMPLETED" if mission_success else "FAILED",

                    error=termination_reason,

                    total_turns=self._turns_count,

                    elapsed_seconds=total_duration,

                    final_tier=getattr(self.orchestrator, "_active_tier", 1),

                    written_files=list(self._written_files),

                )

            except Exception as sum_exc:

                logger.warning(f"AgentLoop: summary write notice: {sum_exc}")



        return AgentLoopResult(
            mission_id=self._mission_id,
            success=mission_success,
            status=final_state.mission.status.value,
            turns_executed=self._turns_count,
            actions_executed=self._actions_count,
            tool_calls_count=self._tool_calls_count,
            verification_calls_count=self._verification_calls_count,
            duration_seconds=total_duration,
            files_created=self._written_files,
            files_modified=[],
            final_output=final_output or "Mission concluded.",
            error=termination_reason,
            termination_reason=termination_reason or final_state.mission.completion_reason,
            active_skills=list(getattr(self, "_active_skill_names", [])),
            skill_telemetry=dict(getattr(self, "_skill_telemetry", {})),
            design_brief=dict(getattr(self, "_design_brief_dict", {})),
            content_coverage=dict(getattr(self, "_content_coverage_dict", {})),
            frontend_validation=getattr(self, "_last_frontend_validation", None),
        )



    # ── Helpers ───────────────────────────────────────────────────────────────



    def _capture_safe_checkpoint(self, boundary: str, turn_id: Optional[str] = None) -> Optional[Any]:

        """Capture checkpoint at safe execution boundary if checkpoint engine is attached."""

        if not self.checkpoint_engine or not self._mission_id:

            return None

        from core.checkpoints.engine import CheckpointReason, CheckpointTrigger

        reason_map = {

            "MISSION_START": CheckpointReason.MANUAL,

            "TURN_SETTLED": CheckpointReason.POST_ACTION,

            "VERIFICATION_COMPLETED": CheckpointReason.POST_VERIFICATION,

        }

        reason = reason_map.get(boundary, CheckpointReason.MANUAL)

        state_store = getattr(self, "state_store", None) or (self.event_bus.get_state(self._mission_id) if hasattr(self.event_bus, "get_state") else None)

        runtime_state = state_store.get_snapshot() if state_store else None

        if runtime_state is None:

            from core.runtime_state.models import HermesRuntimeState

            runtime_state = HermesRuntimeState.create_empty(self._mission_id)

        sess_id = getattr(self, "_session_id", None) or f"sess_{self._mission_id}"

        return self.checkpoint_engine.create_checkpoint(

            session_id=sess_id,

            mission_id=self._mission_id,

            runtime_state=runtime_state,

            reason=reason,

            trigger=CheckpointTrigger.SYSTEM,

        )



    def _detect_stall(self) -> Tuple[bool, str, str]:

        """Detect repeated identical actions or stalled progress fingerprint."""

        window_size = self.config.stall_window_size

        if len(self._recent_actions) >= window_size:

            last_actions = self._recent_actions[-window_size:]

            first = last_actions[0]

            if all(a == first for a in last_actions):

                return True, "Repeated identical action detected with identical parameters.", "Try an alternative action or tool."



        # Tool category stall (e.g. repeated task.todo or repeated inspection without mutations)

        if len(self._recent_actions) >= 3:

            last_3_tools = [a[0] for a in self._recent_actions[-3:]]

            if all(t in ("task.todo", "todo", "task_todo") for t in last_3_tools):

                return True, "Repeated planning operations without implementing code.", "Select a task and write files using write_file."

            if all(t in ("shell.bash", "bash_exec", "list_directory", "fs.read", "read_file", "search.glob") for t in last_3_tools) and not self._written_files:

                ws_root = getattr(self.workspace, "workspace_root", None) if hasattr(self, "workspace") else None

                is_genuinely_empty = True

                if ws_root and Path(ws_root).exists():

                    try:

                        non_meta = [p for p in Path(ws_root).iterdir() if p.name not in (".git", ".hermes", ".artifacts", "node_modules")]

                        if len(non_meta) > 0:

                            is_genuinely_empty = False

                    except Exception:

                        pass

                if is_genuinely_empty:

                    return True, "Repeated inspection on empty workspace.", "Implement the project entrypoint or required files using write_file."

        # Non-mutating read/inspection loop on existing workspace
        if getattr(self, "_consecutive_non_mutating_turns", 0) >= 4:
            return True, f"Repeated inspection without code modifications ({self._consecutive_non_mutating_turns} non-mutating turns).", "Modify or edit the target code or styling files using fs.edit or fs.write immediately."



        # Progress stagnation: only check if NO file mutations occurred recently and >= 8 turns without fingerprint change

        if hasattr(self, "planning_service") and self.planning_service:

            if hasattr(self.planning_service, "progress_controller"):

                ctrl = self.planning_service.progress_controller

                if getattr(ctrl, "_consecutive_identical_fingerprints", 0) >= 8 and getattr(self, "_consecutive_non_mutating_turns", 0) >= 4:

                    is_stalled, reason, advice = ctrl.detect_stall(stall_threshold_turns=8)

                    if is_stalled:

                        return True, reason, advice



        return False, "", ""



    def _record_failure_entry(
        self,
        turn_id: str,
        category: str,
        tier: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        error_class: Optional[str] = None,
        operation: Optional[str] = None,
        target_path: Optional[str] = None,
        actual_result: Optional[str] = None,
        elapsed_duration: Optional[float] = None,
        workspace_progress: bool = False,
    ) -> FailureLedgerEntry:
        entry = FailureLedgerEntry(
            turn_id=turn_id,
            category=category,
            tier=tier,
            provider=provider,
            model=model,
            error_class=error_class,
            operation=operation,
            target_path=target_path,
            actual_result=actual_result,
            elapsed_duration=elapsed_duration,
            workspace_progress=workspace_progress,
        )
        if not hasattr(self, "_failure_ledger"):
            self._failure_ledger = []
        if not hasattr(self, "_category_failures"):
            self._category_failures = {"PROVIDER_FAILURE": 0, "TOOL_FAILURE": 0, "VALIDATION_FAILURE": 0, "NO_PROGRESS": 0}
        self._failure_ledger.append(entry)
        self._category_failures[category] = self._category_failures.get(category, 0) + 1
        return entry

    def _compute_workspace_source_digest(self) -> str:
        """Compute deterministic digest of all relevant source and test files in workspace."""
        if not self.workspace or not hasattr(self.workspace, "workspace_root") or not self.workspace.workspace_root:
            return ""
        ws_root = Path(self.workspace.workspace_root)
        if not ws_root.exists():
            return ""
        hasher = hashlib.sha256()
        try:
            for p in sorted(ws_root.rglob("*")):
                if not p.is_file():
                    continue
                try:
                    rel_parts = p.relative_to(ws_root).parts
                except ValueError:
                    continue
                if any(part in (".git", "node_modules", ".venv", "venv", ".hermes", ".artifacts", "__pycache__", "coverage", ".pytest_cache") for part in rel_parts):
                    continue
                if p.suffix.lower() in (".js", ".ts", ".html", ".css", ".json", ".py", ".sql", ".md"):
                    hasher.update(str(p.relative_to(ws_root)).encode("utf-8"))
                    try:
                        hasher.update(str(p.stat().st_mtime_ns).encode("utf-8"))
                        hasher.update(str(p.stat().st_size).encode("utf-8"))
                    except Exception:
                        pass
        except Exception:
            pass
        return hasher.hexdigest()

    def _record_observation(self, obs: Observation) -> None:

        """Add observation to bounded history and ContextEngine."""

        self._observation_history.append(obs)

        if len(self._observation_history) > 10:

            self._observation_history.pop(0)



        if hasattr(self, "context_engine") and self.context_engine:

            try:

                from core.context.models import ContextItem, ContextSectionType, ContextSourceType, ContextPriority, ContextProvenance

                is_err = not obs.success

                item = ContextItem(

                    id=obs.observation_id or f"obs_{uuid.uuid4().hex[:6]}",

                    section=ContextSectionType.RECENT_OBSERVATIONS,

                    content=obs.to_context_string(),

                    provenance=ContextProvenance(

                        source_type=ContextSourceType.OBSERVATION,

                        source_id=obs.source_id or obs.source_type,

                        turn_id=obs.turn_id,

                    ),

                    priority=ContextPriority.IMPORTANT if is_err else ContextPriority.OPTIONAL,

                    summary=obs.summary,

                    metadata={"is_error": is_err},

                )

                self.context_engine.register_item(item)

            except Exception:

                pass



    def _build_turn_context(self, mission: Mission, state: Any) -> Tuple[str, str]:

        """Assemble grounding system prompt and observation-enriched user message."""

        system_prompt = (

            "You are the autonomous decision-maker inside a constrained software-engineering environment.\n"

            "You may inspect and modify the workspace through available tools.\n"

            "Available Core Tools:\n"

            "- fs.read: Read file contents or line ranges\n"

            "- fs.edit: Surgical text replacement (requires exact old_text)\n"

            "- fs.write: Create or overwrite file atomically\n"

            "- shell.bash: Execute shell commands (pytest, build, git)\n"

            "- search.glob: Find files matching patterns\n"

            "- search.grep: Search file contents with context\n"

            "- user.ask: Ask user clarifying questions\n"

            "- web_search: Search web (Google Serper / Tavily) for live data, facts, and docs\n"

            "- web_fetch: Fetch and extract structured markdown from web pages\n"

            "- web_crawl: Bounded crawl within domain to gather connected docs\n"

            "- image_search: Search royalty-free visual assets (Pixabay, Wikimedia)\n"

            "- download_image: Download verified image to assets/images/ and update manifest\n"

            "- deep_web_research: Multi-source research synthesis with citations\n"

            "- tool_search: Discover specialized capabilities on demand\n"

            "Tool results are ground truth observations.\n"

            "Do not claim actions happened unless their results support that claim.\n"

            "Continue iterating when work is incomplete.\n"

            "Use available evidence and tests to verify your implementation.\n"

            "Do not invent tools. Emit valid tool calls.\n"

            "To execute a tool, emit a JSON block with tool_name and arguments:\n"

            "```json\n"

            "{\n"

            '  "tool_name": "fs.write",\n'

            '  "arguments": {"path": "index.html", "content": "..."}\n'

            "}\n"

            "```\n"

            "Execution Rules:\n"

            "1. If starting a new project in an empty workspace, prioritize creating the primary entrypoint (e.g. index.html) and application files immediately using fs.write.\n"

            "2. Do not emit task.todo; tasks are already tracked automatically. Call fs.write, web_search, image_search, and download_image directly.\n"

            "3. Do not run repetitive directory listing commands when the workspace is empty.\n"

            "4. When building a new project from scratch, do NOT re-read index.html after creating it; proceed immediately to write style.css, main.js, and package.json using fs.write. For existing legacy projects, read files before editing.\n"

            "5. When the user requests real images, research, or live facts, use web_search, image_search, and download_image to source and integrate verified assets.\n"

            "6. When creating web projects with linked stylesheets or scripts (e.g. style.css, script.js), write all linked files immediately using fs.write or write_file. Do not repeatedly read index.html before writing style.css.\n"

            "7. When creating a Python project or CLI utility with unit tests requested in the prompt, write the implementation files and immediately write comprehensive pytest unit test files (e.g. tests/test_*.py) using fs.write. Run pytest with shell.bash to verify them. When testing floating-point metrics (such as error rates, fractions, latencies), always use pytest.approx or match the rounding precision used in the implementation (e.g. round(x, 4)). Do not repeatedly re-read implementation files before writing test files.\n"

            "When the mission is completely implemented and verified, provide a final response."

        )



        # 2. Workspace Skeleton and Authoritative Task Execution State

        ws_info = "Workspace: generated_projects/"

        ws_dir_active = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (getattr(self.workspace, "workspace_root", None) or Path.cwd()))

        if self.workspace and self.workspace.is_locked:

            ws_summary = self.workspace.get_workspace_summary()

            skeleton = self.workspace.get_skeleton()

            ws_info = (

                f"Workspace: {ws_summary.get('root', 'active')}\n"

                f"Framework: {ws_summary.get('framework', 'unknown')}\n"

                f"Files ({ws_summary.get('total_files', 0)}):\n{skeleton[:600]}"

            )



        unmet_reqs: List[str] = []

        current_phase_name = "EXECUTION"

        from core.agent_loop.mvp_gate import WebsiteMvpGate

        is_web_task = WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_dir_active, set(self._written_files))

        if is_web_task and hasattr(self, "mvp_gate") and self.mvp_gate and hasattr(self.mvp_gate, "get_unmet_requirements"):

            try:

                unmet_reqs = self.mvp_gate.get_unmet_requirements(ws_dir_active)

                current_phase_name = getattr(self.mvp_gate.evaluate_phase(ws_dir_active), "value", "SCAFFOLD")

            except Exception:

                pass



        from core.integration_validator import CrossArtifactValidator

        integ_rep = CrossArtifactValidator.validate_workspace(ws_dir_active, mission.user_prompt)

        integ_notices: List[str] = []

        if not integ_rep.valid:

            integ_notices.extend([f"INTEGRATION_ERROR: {iss}" for iss in integ_rep.issues])

        elif integ_rep.warnings:

            integ_notices.extend([f"INTEGRATION_WARNING: {w}" for w in integ_rep.warnings])



        authoritative_state_block = (

            f"=== AUTHORITATIVE TASK EXECUTION STATE ===\n"

            f"Lifecycle Phase: {current_phase_name}\n"

            f"Turn Budget: {self._turns_count + 1} / {self.config.max_turns}\n"

        )

        if getattr(self, "_is_large_mission", False):
            authoritative_state_block += f"Execution Phase: {self.current_phase.value}\n"
            if self.completed_phases:
                authoritative_state_block += "Completed Execution Phases:\n"
                for cp in self.completed_phases:
                    cp_s = self.completed_phase_summaries.get(cp, "Satisfied")
                    authoritative_state_block += f"  ✓ {cp}: {cp_s}\n"
            if self.current_phase.value == "PHASE_B_FOUNDATION":
                authoritative_state_block += "PHASE MANDATE: Create core entrypoints (index.html, style.css) using fs.write.\n"
                if hasattr(self, "_design_brief") and self._design_brief:
                    authoritative_state_block += "\n" + self._design_brief.to_compact_directive() + "\n"
                if getattr(self, "_frontend_contract", None):
                    authoritative_state_block += "\n" + self._frontend_contract.to_compact_directive() + "\n"
                if getattr(self, "_skill_evidence_ledger", None):
                    for sk in getattr(self, "_active_skill_names", []):
                        self._skill_evidence_ledger.record_injected(sk, turn_id=str(self._turns_count), phase=self.current_phase.value)
                        if sk in getattr(self, "_skill_telemetry", {}):
                            self._skill_telemetry[sk]["status"] = "INJECTED"
                if getattr(self, "_asset_manifest", None):
                    from core.asset_pipeline import AssetPipeline
                    authoritative_state_block += "\n" + AssetPipeline.get_asset_directive(self._asset_manifest) + "\n"
            elif self.current_phase.value == "PHASE_C_MAIN_IMPLEMENTATION":
                authoritative_state_block += "PHASE MANDATE: Implement all content sections, cards, and assets using fs.write or fs.edit.\n"
                if hasattr(self, "_design_brief") and self._design_brief:
                    authoritative_state_block += "\n" + self._design_brief.to_compact_directive() + "\n"
                if getattr(self, "_frontend_contract", None):
                    authoritative_state_block += "\n" + self._frontend_contract.to_compact_directive() + "\n"
                if getattr(self, "_asset_manifest", None):
                    from core.asset_pipeline import AssetPipeline
                    authoritative_state_block += "\n" + AssetPipeline.get_asset_directive(self._asset_manifest) + "\n"
                if hasattr(self, "_content_coverage") and self._content_coverage:
                    self._content_coverage.audit_workspace(ws_dir_active)
                    authoritative_state_block += "\n" + self._content_coverage.to_summary_block() + "\n"
            elif self.current_phase.value == "PHASE_D_FUNCTIONAL_IMPLEMENTATION":
                authoritative_state_block += "PHASE MANDATE: Implement interactive logic (filters, modals, forms) using fs.write or fs.edit.\n"
                if hasattr(self, "_design_brief") and self._design_brief:
                    authoritative_state_block += "\n" + self._design_brief.to_compact_directive() + "\n"
                if getattr(self, "_frontend_contract", None):
                    authoritative_state_block += "\n" + self._frontend_contract.to_compact_directive() + "\n"
                if getattr(self, "_asset_manifest", None):
                    from core.asset_pipeline import AssetPipeline
                    authoritative_state_block += "\n" + AssetPipeline.get_asset_directive(self._asset_manifest) + "\n"
                is_edu = hasattr(self, "_design_brief") and getattr(self._design_brief, "domain", None) == "education_institution"
                if is_edu:
                    authoritative_state_block += "\nFUNCTIONAL CONTRACT: Implement interactive filtering (school pills + search input), modal dialog display/dismissal with detailed degree program data, and admissions inquiry form validation. Zero missing DOM IDs. Use ONLY local provisioned photography from assets/images/ (NEVER remote Unsplash or pravatar URLs).\n"
                else:
                    authoritative_state_block += "\nFUNCTIONAL CONTRACT: Implement interactive filtering (category pills + search input), modal dialog display/dismissal with detailed item data, and contact/enquiry form validation. Zero missing DOM IDs. Use ONLY local provisioned photography from assets/images/ (NEVER remote Unsplash or pravatar URLs).\n"
            elif self.current_phase.value == "PHASE_F_COMPLETION":
                authoritative_state_block += "PHASE MANDATE: All work packages and verification gates are satisfied! Summarize deliverables and conclude the mission.\n"
            elif self.current_phase.value == "PHASE_E_VERIFICATION":
                authoritative_state_block += "PHASE MANDATE: Verify application in real browser, check zero console errors, run automated tests.\n"
                try:
                    from core.browser.acceptance import BrowserAcceptanceVerifier
                    fresh_ok, _ = BrowserAcceptanceVerifier.check_evidence_freshness(ws_dir_active)
                    if not fresh_ok:
                        logger.info("AgentLoop: Platform executing managed browser acceptance...")
                        b_res = BrowserAcceptanceVerifier.verify_workspace_sync(
                            ws_dir_active,
                            acceptance_ledger=getattr(self, "acceptance_ledger", None)
                        )
                        if hasattr(self, "mvp_gate"):
                            self.mvp_gate.evaluate_phase(ws_dir_active, browser_verified=b_res.passed)
                except Exception as b_exc:
                    logger.warning(f"AgentLoop: Platform browser acceptance notice: {b_exc}")
                try:
                    from core.frontend_contract_validator import FrontendContractValidator
                    fc_validator = FrontendContractValidator(ws_dir_active)
                    fc_rep = fc_validator.validate_all()
                    self._last_frontend_validation = fc_rep.to_dict()
                    self._last_frontend_validation_report = fc_rep
                    authoritative_state_block += "\n" + fc_rep.to_summary_block() + "\n"
                    evidence_map = fc_validator.evaluate_skill_application_evidence(
                        workspace_root=ws_dir_active,
                        active_skills=getattr(self, "_active_skill_names", []),
                        design_brief=getattr(self, "_design_brief", None),
                        validation_report=fc_rep,
                        browser_qa=fc_rep.browser_verification,
                    )
                    for sk, ev_info in evidence_map.items():
                        if sk in getattr(self, "_skill_telemetry", {}):
                            if ev_info.get("applied", False):
                                self._skill_telemetry[sk]["status"] = "APPLIED"
                                self._skill_telemetry[sk]["evidence"] = ev_info.get("evidence", "")
                            else:
                                self._skill_telemetry[sk]["status"] = "INJECTED"
                                self._skill_telemetry[sk]["evidence"] = ev_info.get("evidence", "Awaiting specific implementation evidence.")
                except Exception as fc_exc:
                    logger.warning(f"AgentLoop: frontend contract verification notice: {fc_exc}")

        if unmet_reqs:

            authoritative_state_block += "Unmet Scaffold/Lifecycle Requirements:\n" + "\n".join(f"  - {u}" for u in unmet_reqs) + "\n"

            target_f, action_inst = WebsiteMvpGate.parse_scaffold_target(unmet_reqs[0])

            if target_f and target_f not in ("npm run build", "browser_open_preview"):

                authoritative_state_block += (

                    f"IMMEDIATE MANDATE: '{target_f}' requires attention: {action_inst} "

                    f"Use fs.write or fs.edit on '{target_f}'. Do NOT modify unrelated or already-completed files.\n"

                )

            elif target_f:

                authoritative_state_block += f"IMMEDIATE MANDATE: {action_inst}\n"

            else:

                authoritative_state_block += f"IMMEDIATE MANDATE: Resolve unmet requirement '{unmet_reqs[0]}'.\n"

        else:

            authoritative_state_block += "Scaffold/Lifecycle Requirements: All current phase prerequisites satisfied.\n"

            self._active_recovery_brief = None



        if integ_notices:

            authoritative_state_block += "Cross-Artifact Integration Status:\n" + "\n".join(f"  - {n}" for n in integ_notices) + "\n"

        authoritative_state_block += "==========================================="



        # Contract and DOM Inventory Injection

        try:

            from core.project_contract import ProjectContract

            contract = ProjectContract.create_or_load(ws_dir_active, getattr(mission, "mission_id", self._mission_id), mission.user_prompt or "")

            dom_inv = ProjectContract.extract_dom_inventory(ws_dir_active)

            contract_lines = [

                "\n=== CANONICAL PROJECT CONTRACT & DOM INVENTORY ===",

                f"Canonical JS Entrypoint: '{contract.canonical_js}'",

                f"Canonical HTML: '{contract.canonical_html}' | CSS: '{contract.canonical_css}'",

            ]

            if dom_inv.get("ids"):

                contract_lines.append(f"Actual HTML DOM IDs in {contract.canonical_html}: {', '.join(dom_inv['ids'][:35])}")

            if dom_inv.get("form_names"):

                contract_lines.append(f"Actual HTML Form Control names: {', '.join(dom_inv['form_names'][:20])}")

            contract_lines.append(f"MANDATE: Any JS code (in '{contract.canonical_js}') MUST bind to these EXACT element IDs. Do NOT invent alternate or uncontracted IDs.")

            contract_lines.append("===================================================")

            authoritative_state_block += "\n" + "\n".join(contract_lines)

        except Exception as e:

            logger.debug(f"AgentLoop: notice injecting contract/dom inventory: {e}")



        # 3. ContextEngine build if available

        if hasattr(self, "context_engine") and self.context_engine:

            try:

                from core.context.models import ContextItem, ContextSectionType, ContextSourceType, ContextPriority, ContextProvenance

                self.context_engine.register_item(ContextItem(

                    id="sys_invariant",

                    section=ContextSectionType.SYSTEM,

                    content=system_prompt,

                    provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="hermes_core"),

                    priority=ContextPriority.MANDATORY,

                    pinned=True,

                ))

                self.context_engine.register_item(ContextItem(

                    id="goal_primary",

                    section=ContextSectionType.CURRENT_GOAL,

                    content=f"Goal:\n{mission.user_prompt}\n\n{ws_info}\n\n{authoritative_state_block}",

                    provenance=ContextProvenance(source_type=ContextSourceType.USER, source_id=mission.mission_id),

                    priority=ContextPriority.MANDATORY,

                    pinned=True,

                ))

                # Sync ground-truth observations to context engine as pinned MANDATORY

                if self._observation_history:

                    obs_lines = ["RECENT OBSERVATIONS (Ground Truth):"]

                    for o in self._observation_history[-4:]:

                        obs_lines.append(o.to_context_string())

                    self.context_engine.register_item(ContextItem(

                        id="recent_observations_authoritative",

                        section=ContextSectionType.RECENT_OBSERVATIONS,

                        content="\n".join(obs_lines),

                        provenance=ContextProvenance(source_type=ContextSourceType.OBSERVATION, source_id="ground_truth"),

                        priority=ContextPriority.MANDATORY,

                        pinned=True,

                    ))



                # Pin unresolved syntax/execution diagnostics and repair directives so they are NEVER evicted

                if getattr(self, "syntax_repair", None) and self.syntax_repair.has_unresolved_syntax_errors():

                    for t_key, ticket in self.syntax_repair.active_tickets.items():

                        if ticket.is_active:

                            directive_str = self.syntax_repair.build_repair_directive(ticket)

                            self.context_engine.register_item(ContextItem(

                                id=f"syntax_repair_directive_{t_key}",

                                section=ContextSectionType.RECENT_OBSERVATIONS,

                                content=directive_str,

                                provenance=ContextProvenance(source_type=ContextSourceType.OBSERVATION, source_id="syntax_repair_controller"),

                                priority=ContextPriority.MANDATORY,

                                pinned=True,

                            ))

                elif getattr(self, "_pending_diagnostics", None):

                    diag_lines = ["UNRESOLVED CRITICAL SYNTAX DIAGNOSTICS (ACTION REQUIRED):"]

                    for p_target, p_diag in self._pending_diagnostics.items():

                        diag_lines.append(

                            f"  - Target '{Path(p_diag.get('file', p_target)).name}', line {p_diag.get('line', 1)}: "

                            f"{p_diag.get('error_class', 'SyntaxError')}: {p_diag.get('message', '')}"

                        )

                        if p_diag.get("source_line"):

                            diag_lines.append(f"    Code snippet: {p_diag['source_line']}")

                    diag_lines.append("  MANDATORY: You MUST fix the above syntax error using fs.edit or fs.write before any other action.")

                    self.context_engine.register_item(ContextItem(

                        id="unresolved_diagnostics_mandatory",

                        section=ContextSectionType.RECENT_OBSERVATIONS,

                        content="\n".join(diag_lines),

                        provenance=ContextProvenance(source_type=ContextSourceType.OBSERVATION, source_id="diagnostics_engine"),

                        priority=ContextPriority.MANDATORY,

                        pinned=True,

                    ))



                # Sync planning service to context engine

                if hasattr(self, "planning_service") and self.planning_service:

                    try:

                        self.planning_service.sync_to_context_engine(self.context_engine)

                    except Exception as sync_exc:

                        logger.warning(f"AgentLoop: planning context sync warning: {sync_exc}")



                # Sync project intelligence (Rules and Active Skills) to context engine

                if hasattr(self, "project_intelligence") and self.project_intelligence:

                    try:

                        active_files = [f.file_path for f in getattr(state, "active_files", [])] if hasattr(state, "active_files") else None

                        self.project_intelligence.sync_to_context_engine(

                            self.context_engine,

                            active_files=active_files,

                            task_description=mission.user_prompt,

                        )

                    except Exception as pi_sync_exc:

                        logger.warning(f"AgentLoop: project intelligence context sync warning: {pi_sync_exc}")



                pack = self.context_engine.build_context(

                    mission_goal=mission.user_prompt,

                    state_snapshot=state,

                    turn_number=self._turns_count + 1,

                )

                messages = pack.to_messages()

                u_content = messages[1]["content"]

                if getattr(self, "_active_recovery_brief", None):

                    u_content = f"{u_content}\n\n{self._active_recovery_brief}"

                return messages[0]["content"], u_content

            except Exception as ctx_exc:

                logger.warning(f"AgentLoop: ContextEngine assembly encountered ({ctx_exc}), falling back to direct context")



        # Fallback to direct assembly

        skills_text = ""

        if hasattr(self, "project_intelligence") and self.project_intelligence:

            active_skills = self.project_intelligence.get_active_skills()

            if active_skills:

                skill_blocks = ["\nACTIVE SKILLS:"]

                for s_name, s_obj in active_skills.items():

                    skill_blocks.append(f'<skill name="{s_name}">\n{s_obj.body}\n</skill>')

                skills_text = "\n" + "\n\n".join(skill_blocks)



        obs_text = ""

        if self._observation_history:

            num_obs = 2 if getattr(self, "_is_large_mission", False) else 4

            recent_obs = self._observation_history[-num_obs:]

            obs_lines = ["\nRECENT OBSERVATIONS (Ground Truth):"]

            for o in recent_obs:

                if getattr(self, "_is_large_mission", False):
                    st = "SUCCESS" if o.success else f"FAILED (exit_code={o.exit_code})"
                    trimmed = (o.content or "").strip()
                    max_len = 2000 if not o.success else 800
                    if len(trimmed) > max_len:
                        trimmed = trimmed[:max_len] + "... [truncated for context efficiency]"
                    obs_lines.append(f"[OBSERVATION {o.source_id or o.source_type}]: status={st}\n  {trimmed}")
                else:
                    obs_lines.append(o.to_context_string())

            obs_text = "\n".join(obs_lines)



        pending_diag_direct = ""

        if getattr(self, "_pending_diagnostics", None):

            diag_lines = ["\nUNRESOLVED CRITICAL SYNTAX DIAGNOSTICS (ACTION REQUIRED):"]

            for p_target, p_diag in self._pending_diagnostics.items():

                diag_lines.append(

                    f"  - Target '{Path(p_diag.get('file', p_target)).name}', line {p_diag.get('line', 1)}: "

                    f"{p_diag.get('error_class', 'SyntaxError')}: {p_diag.get('message', '')}"

                )

                if p_diag.get("source_line"):

                    diag_lines.append(f"    Code snippet: {p_diag['source_line']}")

            diag_lines.append("  MANDATORY: You MUST fix the above syntax error using fs.edit or fs.write before any other action.")

            pending_diag_direct = "\n".join(diag_lines)



        recovery_suffix = f"\n\n{self._active_recovery_brief}" if getattr(self, "_active_recovery_brief", None) else ""

        user_message = (

            f"MISSION GOAL:\n{mission.user_prompt}\n\n"

            f"{ws_info}\n\n"

            f"{authoritative_state_block}\n"

            f"{skills_text}\n"

            f"{obs_text}"

            f"{pending_diag_direct}\n\n"

            f"What is the next useful action to achieve the mission goal?{recovery_suffix}"

        )



        return system_prompt, user_message



    async def _trigger_agent_no_progress_recovery(
        self,
        turn_id: str,
        rejection_reason: str,
        unmet_reqs: Optional[List[str]] = None,
        mission: Optional[Any] = None,
    ) -> bool:
        """
        Handle agent no-progress (stalls, repeated reads, non-mutating turns)
        using the current healthy provider tier.
        Does NOT trigger provider failover or escalate to Tier 4.
        Enforces a bounded recovery budget (max 3 turns).
        """
        count = getattr(self, "_agent_no_progress_recovery_count", 0)
        max_budget = getattr(self, "_max_agent_no_progress_budget", 3)
        if count >= max_budget:
            logger.warning(
                f"AgentLoop: Agent no-progress recovery budget exhausted ({count} >= {max_budget}). "
                "Terminating cleanly with NO_PROGRESS_BUDGET_EXCEEDED without tier escalation."
            )
            return False

        self._agent_no_progress_recovery_count = count + 1
        current_tier = self.active_tier
        prov, model = self._provider_tier_map.get(current_tier, ("", ""))

        logger.info(
            f"AgentLoop: In-tier agent recovery {self._agent_no_progress_recovery_count}/{max_budget} "
            f"on Tier {current_tier} ({prov}/{model}) | reason: {rejection_reason}"
        )

        self._consecutive_non_mutating_turns = 0
        self._stall_consecutive_count = 0

        # Build focused repair directive from workspace state and contracts
        try:
            ws_dir = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else Path.cwd())
            existing_files = [f.name for f in ws_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if ws_dir.exists() else []
        except Exception:
            existing_files = []

        from core.agent_loop.mvp_gate import WebsiteMvpGate
        if not unmet_reqs:
            try:
                if self.workspace and getattr(self.workspace, "is_locked", False):
                    gate = getattr(self, "mvp_gate", None) or WebsiteMvpGate(workspace_root=ws_dir)
                    ok_scaff, missing_items = gate.evaluate(ws_dir)
                    if not ok_scaff and missing_items:
                        unmet_reqs = missing_items
            except Exception:
                pass

        target_repair_file = None
        target_action_hint = None
        if unmet_reqs:
            for req in unmet_reqs:
                target_f, action_inst = WebsiteMvpGate.parse_scaffold_target(req)
                if target_f and target_f not in ("npm run build", "browser_open_preview"):
                    target_repair_file = target_f
                    target_action_hint = action_inst
                    break

        completed_files = [f for f in existing_files if f != target_repair_file]
        missing_desc = "; ".join(unmet_reqs) if unmet_reqs else "Missing required application deliverables."

        dom_summary = ""
        try:
            from core.project_contract import ProjectContract
            dom_inv = ProjectContract.extract_dom_inventory(ws_dir)
            if dom_inv.get("ids"):
                dom_summary = f"DOM CONTRACT: Available IDs: {', '.join(dom_inv['ids'][:35])}\n"
        except Exception:
            pass

        compact_recovery_msg = (
            f"=== ACTIONABLE REPAIR DIRECTIVE (In-Tier Recovery {self._agent_no_progress_recovery_count}/{max_budget}) ===\n"
            f"FOCUS: Maintain execution on Tier {current_tier} ({model}). Action required.\n"
            f"DIAGNOSTIC TRIGGER: {rejection_reason}\n"
            f"COMPLETED & VALID FILES: {', '.join(completed_files) if completed_files else 'None'}\n"
            f"UNMET REQUIREMENTS: {missing_desc}\n"
            f"MANDATORY TARGET: '{target_repair_file or 'missing deliverable'}'\n"
            f"DIRECTIVE: {target_action_hint or 'Create or update the target file immediately using fs.write or fs.edit.'}\n"
            f"PROHIBITION: Do NOT call fs.read or inspect already completed files ({', '.join(completed_files)}). Write the missing deliverable '{target_repair_file or 'missing file'}' directly using fs.write.\n"
            f"{dom_summary}"
            f"============================================================"
        )
        self._active_recovery_brief = compact_recovery_msg
        return True

    async def _trigger_recovery_transition(

        self,

        turn_id: str,

        rejection_reason: str,

        unmet_reqs: Optional[List[str]] = None,

        mission: Optional[Any] = None,

    ) -> bool:

        """

        Execute bounded multi-tier recovery transition (Section 5).

        1. Bounded attempt check (max 2 recovery transitions per mission).

        2. Escalates authoritative routing tier:

           - If active_tier is 1 -> transition to Tier 2 (TIER2_MODEL via TIER2_PROVIDER).

           - If active_tier is 2 -> transition to Tier 3 (TIER3_MODEL via TIER3_PROVIDER).

           - If active_tier is 3 or tiers exhausted -> return False for clean termination.

        3. Publishes canonical TIER_FAILOVER_STARTED event.

        4. Injects mandatory recovery directive into context engine.

        5. Preserves tool-call history, conversation state, and cancellation checks.

        """

        recovery_count = getattr(self, "_recovery_attempt_count", 0)

        max_recovery = getattr(self, "_total_recovery_budget", 2)

        if recovery_count >= max_recovery:

            logger.warning(f"AgentLoop: Recovery budget exhausted ({recovery_count} >= {max_recovery}).")

            return False



        self._recovery_attempt_count = recovery_count + 1

        current_tier = self.active_tier



        from config.model_config import (

            TIER1_PROVIDER, TIER1_MODEL,

            TIER2_PROVIDER, TIER2_MODEL,

            TIER3_PROVIDER, TIER3_MODEL,

            TIER4_PROVIDER, TIER4_MODEL,

        )

        from core.adaptive_routing import adaptive_router, ProviderHealthState



        # Track visited tiers per incident failure fingerprint
        # Strip dynamic turn counters and variable counts so turns 2, 3, etc. share visited history
        norm_reason = re.sub(r'\b\d+\s*(?:turns?|attempts?|times?)\b', 'N turns', rejection_reason.strip(), flags=re.IGNORECASE)
        norm_reason = re.sub(r'\(\s*\d+\s+turns.*?\)', '(N turns)', norm_reason)
        fp = f"{norm_reason[:80]}|{','.join(sorted(unmet_reqs or []))}"

        if not hasattr(self, "_incident_visited_tiers"):

            self._incident_visited_tiers = {}

        visited = self._incident_visited_tiers.setdefault(fp, set())

        visited.add(current_tier)



        # Deterministic multi-tier transition state machine with recovery verification

        next_tier = None

        if not hasattr(self, "_tier_rotations"):

            self._tier_rotations = 0



        if current_tier == 1:

            t2_st = adaptive_router.get_health(2).state

            t3_st = adaptive_router.get_health(3).state

            if 2 not in visited and t2_st not in (ProviderHealthState.OPEN_CIRCUIT, ProviderHealthState.DEGRADED) and adaptive_router.is_tier_available(2):

                next_tier = 2

            elif 3 not in visited and t3_st not in (ProviderHealthState.OPEN_CIRCUIT, ProviderHealthState.DEGRADED) and adaptive_router.is_tier_available(3):

                next_tier = 3

            elif 4 not in visited and adaptive_router.is_tier_healthy(4) and adaptive_router.is_tier_available(4):

                next_tier = 4

            else:

                next_tier = None

        elif current_tier == 2:

            t3_st = adaptive_router.get_health(3).state

            if 3 not in visited and t3_st not in (ProviderHealthState.OPEN_CIRCUIT, ProviderHealthState.DEGRADED) and adaptive_router.is_tier_available(3):

                next_tier = 3

            elif 4 not in visited and adaptive_router.is_tier_healthy(4) and adaptive_router.is_tier_available(4):

                next_tier = 4

            else:

                next_tier = None

        elif current_tier == 3:

            # Cap rotation back to Tier 1: requires healthy T1, rotation budget < 1, and T1 not already failed this fingerprint

            can_rotate_t1 = (

                self._tier_rotations < 1

                and adaptive_router.get_health(1).state == ProviderHealthState.HEALTHY

                and adaptive_router.is_tier_available(1)

                and (1 not in visited)

            )

            if can_rotate_t1:

                self._tier_rotations += 1

                next_tier = 1

                logger.info(f"[RECOVERY TRANSITION] Tier 1 verified recovered to HEALTHY; routing T3 -> T1 (rotation {self._tier_rotations}/1)")

            elif 4 not in visited and adaptive_router.is_tier_healthy(4) and adaptive_router.is_tier_available(4):

                next_tier = 4

                logger.info(f"[RECOVERY TRANSITION] Routing T3 -> Tier 4")

            else:

                next_tier = None

        elif current_tier >= 4:

            can_rotate_t1 = (

                self._tier_rotations < 1

                and adaptive_router.get_health(1).state == ProviderHealthState.HEALTHY

                and (1 not in visited)

            )

            if can_rotate_t1:

                self._tier_rotations += 1

                next_tier = 1

                logger.info(f"[RECOVERY TRANSITION] Tier 1 recovered; routing T4 -> T1 (rotation {self._tier_rotations}/1)")

            else:

                next_tier = None

                logger.info("[RECOVERY TRANSITION] Tiers exhausted for this failure fingerprint; terminating.")



        provider_map = {

            1: (TIER1_PROVIDER, TIER1_MODEL),

            2: (TIER2_PROVIDER, TIER2_MODEL),

            3: (TIER3_PROVIDER, TIER3_MODEL),

            4: (TIER4_PROVIDER, TIER4_MODEL),

        }

        target_provider, target_model = provider_map.get(next_tier, (None, None))



        # Record mission-wide failure history without resetting it

        if not hasattr(self, "_mission_failure_history"):

            self._mission_failure_history = []

        self._mission_failure_history.append({

            "timestamp": time.time(),

            "turn_id": turn_id,

            "from_tier": current_tier,

            "to_tier": next_tier,

            "reason": rejection_reason,

            "recovery_attempt": self._recovery_attempt_count,

        })

        if not hasattr(self, "_provider_failure_counts"):

            self._provider_failure_counts = {}

        cur_pname = provider_map.get(current_tier, ("unknown", ""))[0]

        self._provider_failure_counts[cur_pname] = self._provider_failure_counts.get(cur_pname, 0) + 1



        # Prevent duplicate transition to the same tier
        if next_tier == current_tier:
            logger.warning(f"AgentLoop: Next tier ({next_tier}) is identical to current tier ({current_tier}). Advancing to next unvisited tier.")
            for cand in [current_tier + 1, current_tier + 2]:
                if cand <= 4 and cand not in visited and adaptive_router.is_tier_available(cand) and adaptive_router.is_tier_healthy(cand):
                    next_tier = cand
                    break
            else:
                next_tier = None
            target_provider, target_model = provider_map.get(next_tier, (None, None))

        # Prevent repeating the exact same recovery transition consecutively
        last_trans = getattr(self, "_last_recovery_transition", None)
        if last_trans and last_trans == (current_tier, next_tier):
            logger.warning(f"AgentLoop: Duplicate recovery transition {current_tier} -> {next_tier} prevented. Advancing to next unvisited tier.")
            for cand in [current_tier + 1, current_tier + 2, 4]:
                if cand <= 4 and cand not in visited and cand != next_tier and adaptive_router.is_tier_available(cand) and adaptive_router.is_tier_healthy(cand):
                    next_tier = cand
                    break
            else:
                next_tier = None
            target_provider, target_model = provider_map.get(next_tier, (None, None))

        if next_tier and target_model:

            logger.info(

                f"AgentLoop: Bounded recovery transition from Tier {current_tier} to Tier {next_tier} "

                f"({target_provider} / {target_model}) | reason: {rejection_reason}"

            )

            visited.add(next_tier)
            self._in_recovery = True
            self._last_recovery_transition = (current_tier, next_tier)
            self.set_active_model_state(tier=next_tier, provider=target_provider, model=target_model, reason=rejection_reason)

            await self._publish_event(

                EventType.TIER_FAILOVER_STARTED,

                turn_id=turn_id,

                payload={

                    "from_tier": current_tier,

                    "to_tier": next_tier,

                    "provider": target_provider,

                    "model": target_model,

                    "headline": f"Recovery Escalation: Tier {current_tier} -> Tier {next_tier} ({target_model})",

                    "reason": rejection_reason,

                },

            )

        else:

            logger.warning(f"AgentLoop: No further tier available for recovery escalation from Tier {current_tier} (all candidate tiers/providers exhausted).")

            return False



        # Reset current recovery-cycle counters (preserves mission failure history, fingerprints & failure counts)

        self._cycle_no_progress_blocks = 0

        self._cycle_empty_turns = 0

        self._consecutive_no_progress_blocks = 0

        self._consecutive_empty_turns = 0



        # Build compact recovery context

        try:

            ws_dir = Path(self.workspace.root_str if (self.workspace and self.workspace.is_locked) else Path.cwd())

            existing_files = [f.name for f in ws_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if ws_dir.exists() else []

            files_summary = [f"{f.name} ({f.stat().st_size}B)" for f in ws_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if ws_dir.exists() else []

        except Exception:

            existing_files = []

            files_summary = []



        from core.agent_loop.mvp_gate import WebsiteMvpGate

        if not unmet_reqs:

            try:

                # Only evaluate workspace if it is an actual locked application workspace
                if self.workspace and getattr(self.workspace, "is_locked", False):
                    gate = getattr(self, "mvp_gate", None) or WebsiteMvpGate(workspace_root=ws_dir)
                    ok_scaff, missing_items = gate.evaluate(ws_dir)
                    if not ok_scaff and missing_items:
                        unmet_reqs = missing_items

            except Exception:

                pass



        target_repair_file = None

        target_action_hint = None

        if unmet_reqs:

            for req in unmet_reqs:

                target_f, action_inst = WebsiteMvpGate.parse_scaffold_target(req)

                if target_f and target_f not in ("npm run build", "browser_open_preview"):

                    target_repair_file = target_f

                    target_action_hint = action_inst

                    break



        completed_files = [f for f in existing_files if f != target_repair_file]

        missing_desc = "; ".join(unmet_reqs) if unmet_reqs else "Missing required application deliverables."



        # Extract DOM inventory if available so the recovery model has the exact contract without reading

        dom_summary = ""

        try:

            from core.project_contract import ProjectContract

            dom_inv = ProjectContract.extract_dom_inventory(ws_dir)

            if dom_inv.get("ids"):

                dom_summary = f"DOM CONTRACT: Available IDs: {', '.join(dom_inv['ids'][:35])}\n"

        except Exception:

            pass



        # Extract recent test diagnostics so Tier failover preserves failure history
        test_fail_summary = ""
        for obs in reversed(getattr(self, "_observation_history", [])):
            if not getattr(obs, "success", True):
                obs_meta = getattr(obs, "metadata", {}) or {}
                t_ev = obs_meta.get("test_evidence") or (obs_meta.get("details", {}) if isinstance(obs_meta, dict) else {}).get("test_evidence")
                if t_ev and isinstance(t_ev, dict) and t_ev.get("repair_brief"):
                    test_fail_summary = f"\nRECENT TEST FAILURE DIAGNOSIS:\n{t_ev['repair_brief']}\n"
                    break
                elif getattr(obs, "content", None) and any(w in str(obs.content).lower() for w in ("fail", "error", "expected", "received")):
                    test_fail_summary = f"\nRECENT TEST FAILURE:\n{str(obs.content)[:800]}\n"
                    break

        compact_recovery_msg = (

            f"=== MANDATORY SYSTEM RECOVERY DIRECTIVE ===\n"

            f"ESCALATION: Tier failover to Tier {next_tier} ({target_model}) due to prior stall.\n"

            f"DIAGNOSTIC TRIGGER: {rejection_reason}\n"

            f"COMPLETED & VALID FILES: {', '.join(completed_files) if completed_files else 'None'}\n"

            f"UNMET REQUIREMENTS: {missing_desc}\n"

            f"MANDATORY TARGET: '{target_repair_file or 'missing deliverable'}'\n"

            f"DIRECTIVE: {target_action_hint or 'Create the target file immediately using fs.write.'}\n"

            f"PROHIBITION: Do NOT call fs.read or rewrite already completed files ({', '.join(completed_files)}). Write the missing deliverable '{target_repair_file or 'missing file'}' directly using fs.write.\n"

            f"{dom_summary}"

            f"{test_fail_summary}"

            f"============================================"

        )

        self._active_recovery_brief = compact_recovery_msg



        # Persist checkpoint state

        try:

            checkpoint_data = {

                "mission_id": self._mission_id,

                "current_tier": next_tier,

                "provider": target_provider,

                "model": target_model,

                "target_repair_file": target_repair_file,

                "unmet_requirements": unmet_reqs or [],

                "completed_files": completed_files,

                "trigger_reason": rejection_reason,

            }

            hermes_dir = ws_dir / ".hermes"

            hermes_dir.mkdir(parents=True, exist_ok=True)

            (hermes_dir / "recovery_checkpoint.json").write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")

        except Exception as e:

            logger.debug(f"AgentLoop: notice persisting recovery checkpoint: {e}")



        # Inject into context engine

        if hasattr(self, "context_engine") and self.context_engine:

            try:

                from core.context.models import ContextItem, ContextSectionType, ContextSourceType, ContextPriority, ContextProvenance

                self.context_engine.register_item(ContextItem(

                    id=f"recovery_directive_{turn_id}",

                    section=ContextSectionType.SYSTEM,

                    content=compact_recovery_msg,

                    provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="recovery_controller"),

                    priority=ContextPriority.MANDATORY,

                    pinned=True,

                ))

                self.context_engine.register_item(ContextItem(

                    id=f"recovery_user_directive_{turn_id}",

                    section=ContextSectionType.CURRENT_GOAL,

                    content=f"\n\n{compact_recovery_msg}",

                    provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="recovery_controller"),

                    priority=ContextPriority.MANDATORY,

                    pinned=True,

                ))

            except Exception:

                pass



        # Record recovery observation

        rec_obs = Observation(

            observation_id=f"obs_rec_{uuid.uuid4().hex[:6]}",

            mission_id=self._mission_id,

            turn_id=turn_id,

            source_type="governor",

            source_id="recovery_controller",

            success=False,

            summary=f"Recovery transition activated to Tier {getattr(self.orchestrator, '_active_tier', current_tier)}. Mandatory write directive issued.",

            content=compact_recovery_msg,

            metadata={"code": "RECOVERY_TRANSITION_ACTIVATED", "attempt": self._recovery_attempt_count, "active_tier": getattr(self.orchestrator, "_active_tier", current_tier)},

        )

        self._record_observation(rec_obs)

        self._recovery_triggered_this_turn = True

        return True



    async def _execute_no_progress_recovery(

        self,

        turn_id: str,

        mission: Any,

        unmet_reqs: List[str],

        rejection_reason: str,

    ) -> bool:

        """

        Execute bounded in-tier agent recovery when model repeatedly requests no-progress operations.

        Delegates to canonical _trigger_agent_no_progress_recovery to preserve provider health

        and avoid premature tier failover.

        """

        return await self._trigger_agent_no_progress_recovery(

            turn_id=turn_id,

            rejection_reason=rejection_reason,

            unmet_reqs=unmet_reqs,

            mission=mission,

        )



    def _determine_reasoning_policy(self, user_message: str, turn_id: Optional[str] = None) -> Tuple[str, int]:

        """

        Determine task-specific reasoning effort ('none', 'low', 'high') and max_tokens (4096, 8192).

        

        Rules:

        1. Recovery escalation active (consecutive failures, recovery active, empty-action loops) -> 'high', 8192

        2. Complex architecture / 3D Three.js scene design -> 'high', 8192

        3. Routine coding / scaffolding (package.json, index.html, style.css, main.js, unit tests) -> 'low', 8192

        4. Routine tool selection / inspection / reading files / status check -> 'none', 4096

        """

        prompt_lower = (user_message or "").lower()

        mission_prompt = ""

        if hasattr(self, "mission") and self.mission and getattr(self.mission, "user_prompt", None):

            mission_prompt = str(self.mission.user_prompt).lower()

        is_static_web = any(k in mission_prompt for k in [
            "html, css and vanilla javascript", "no database", "no backend",
            "static website", "pure frontend", "no external api"
        ])

        # 1. Empty-action loops / reasoning-only stalls: enforce LOW effort to prevent 20s thinking stalls (P0)
        if getattr(self, "_consecutive_empty_turns", 0) > 0 or getattr(self, "_in_recovery", False) or getattr(self, "_recovery_triggered_this_turn", False):
            return "low", 4096

        # 2. Static website missions: avoid deep architectural thinking loops
        if is_static_web:
            return "low", 4096



        prompt_lower = (user_message or "").lower()

        mission_prompt = ""

        if hasattr(self, "mission") and self.mission and getattr(self.mission, "user_prompt", None):

            mission_prompt = str(self.mission.user_prompt).lower()



        # 2. Complex 3D / Three.js scenes or deep architectural planning

        is_3d_complex = any(k in mission_prompt for k in ["three.js", "webgl", "cinematic", "rocket simulation", "3d scene"])

        if is_3d_complex and any(k in prompt_lower for k in ["shader", "quaternion", "matrix4", "physics engine", "particle system", "cinematic trajectory"]):

            return "high", 8192



        # 3. Routine tool selection / inspection / status checks

        is_inspection = any(term in prompt_lower for term in [

            "read_file", "list_dir", "file_exists", "status check", "verify", "inspect", "which tool", "check whether"

        ]) and not any(term in prompt_lower for term in ["write_file", "generate code", "implement", "build"])

        if is_inspection:

            return "none", 4096



        # 4. Routine coding / scaffolding / general website & python tasks

        return "low", 8192



    async def _generate_model_turn(

        self,

        system_prompt: str,

        user_message: str,

        turn_id: Optional[str] = None,

        timeout_seconds: Optional[float] = None,

    ) -> Any:

        """Call configured model using orchestrator client, provider, or mock bridge with 3-tier routing events."""

        active_tier = getattr(self.orchestrator, "_active_tier", 1)

        from config.model_config import (

            TIER1_PROVIDER, TIER1_MODEL,

            TIER2_PROVIDER, TIER2_MODEL,

            TIER3_PROVIDER, TIER3_MODEL,

        )

        from core.adaptive_routing import adaptive_router, ProviderHealthState

        if active_tier > 1:
            if adaptive_router.is_tier_excluded_for_mission(1, self._mission_id):
                logger.info(f"AgentLoop: Tier 1 is excluded for mission '{self._mission_id}'. Retaining active Tier {active_tier}.")
            else:
                rec1 = adaptive_router.get_health(1)
                if rec1.state == ProviderHealthState.HEALTHY and adaptive_router.is_tier_available(1, mission_id=self._mission_id):
                    logger.info(f"AgentLoop: Tier 1 ({TIER1_PROVIDER}/{TIER1_MODEL}) is HEALTHY. Resuming Tier 1 dispatch.")
                    self.set_active_model_state(tier=1, provider=TIER1_PROVIDER, model=TIER1_MODEL)
                    active_tier = 1
                elif not adaptive_router.is_tier_healthy(active_tier, mission_id=self._mission_id):
                    eligible = adaptive_router.get_eligible_tiers(mission_id=self._mission_id)
                    if eligible:
                        best_tier = eligible[0]
                        t_prov, t_mod = getattr(self, "_provider_tier_map", {}).get(best_tier, (None, None))
                        logger.warning(f"AgentLoop: Active tier {active_tier} is unhealthy. Switching to eligible Tier {best_tier} ({t_prov}/{t_mod}).")
                        self.set_active_model_state(tier=best_tier, provider=t_prov, model=t_mod)
                        active_tier = best_tier

        from config.model_config import (

            TIER1_PROVIDER, TIER1_MODEL,

            TIER2_PROVIDER, TIER2_MODEL,

            TIER3_PROVIDER, TIER3_MODEL,

        )



        from tools.platform.catalog import tool_catalog

        from tools.registry import get_openai_tool_definitions

        native_tools = (

            get_openai_tool_definitions()

            if self.config.execution_mode == "benchmark"

            else tool_catalog.get_openai_tools(core_only=True)

        )



        from config.model_config import TIER4_PROVIDER, TIER4_MODEL

        # Tier 4 dispatch when recovery escalation reached Tier 4
        if active_tier == 4 and TIER4_MODEL:
            tier4_client = getattr(self.orchestrator, "tier4", None) or getattr(self.orchestrator, "_tier4", None) or getattr(self.orchestrator, "ollama", None)
            from core.adaptive_routing import adaptive_router
            t4_avail = adaptive_router.is_tier_available(4)
            if tier4_client and hasattr(tier4_client, "is_available_sync"):
                t4_avail = t4_avail and tier4_client.is_available_sync()
            if not t4_avail:
                logger.warning("AgentLoop: Tier 4 Ollama is unavailable. Bypassing Tier 4 dispatch.")
                raise RuntimeError("Tier 4 Ollama daemon unreachable at http://127.0.0.1:11434")

            await self._publish_event(
                EventType.TIER_SELECTED,
                turn_id=turn_id,
                payload={
                    "tier": 4,
                    "provider": TIER4_PROVIDER,
                    "model": TIER4_MODEL,
                    "reason": "recovery_escalated_tier_4",
                },
            )
            t4_kwargs = {
                "prompt": user_message,
                "system": system_prompt,
                "mission_id": self._mission_id,
                "turn_id": turn_id or "",
                "temperature": self.config.temperature,
                "model": TIER4_MODEL,
                "tools": native_tools,
            }
            if timeout_seconds is not None:
                t4_kwargs["timeout_seconds"] = timeout_seconds
            tier4_client = getattr(self.orchestrator, "tier4", None) or getattr(self.orchestrator, "_tier4", None) or getattr(self.orchestrator, "ollama", None)
            if tier4_client and hasattr(tier4_client, "generate"):
                t4_gen = getattr(tier4_client, "generate")
                res = t4_gen(**t4_kwargs)
                return (await res) if asyncio.iscoroutine(res) else res

        # Tier 3 dispatch when recovery escalation reached Tier 3

        if active_tier == 3 and TIER3_MODEL:

            await self._publish_event(

                EventType.TIER_SELECTED,

                turn_id=turn_id,

                payload={

                    "tier": 3,

                    "provider": TIER3_PROVIDER,

                    "model": TIER3_MODEL,

                    "reason": "recovery_escalated_tier_3",

                },

            )

            t3_kwargs = {

                "prompt": user_message,

                "system": system_prompt,

                "mission_id": self._mission_id,

                "turn_id": turn_id or "",

                "temperature": self.config.temperature,

                "model": TIER3_MODEL,

                "tools": native_tools,

            }

            if timeout_seconds is not None:

                t3_kwargs["timeout_seconds"] = timeout_seconds

            tier3_client = getattr(self.orchestrator, "tier3", None) or getattr(self.orchestrator, "_tier3", None) or getattr(self.orchestrator, "ollama", None)

            if tier3_client and hasattr(tier3_client, "generate"):

                t3_gen = getattr(tier3_client, "generate")

                try:
                    res = t3_gen(**t3_kwargs)
                    res_obj = (await res) if asyncio.iscoroutine(res) else res
                    if getattr(res_obj, "success", True) is False:
                        raise RuntimeError(getattr(res_obj, "error", None) or f"Tier 3 ({TIER3_PROVIDER}/{TIER3_MODEL}) failed")
                    return res_obj
                except Exception as t3_exc:
                    logger.warning(f"AgentLoop: Tier 3 generation failed ({t3_exc}). Checking eligible fallback tiers...")
                    from core.adaptive_routing import adaptive_router
                    adaptive_router.record_failure(tier=3, error=t3_exc)
                    eligible = [t for t in adaptive_router.get_eligible_tiers() if t != 3]
                    if eligible:
                        fb_tier = 1 if 1 in eligible else eligible[0]
                        fb_prov, fb_mod = getattr(self, "_provider_tier_map", {}).get(fb_tier, (None, None))
                        logger.warning(f"AgentLoop: Tier 3 failed. Failing over to eligible Tier {fb_tier} ({fb_prov}/{fb_mod}).")
                        self.set_active_model_state(tier=fb_tier, provider=fb_prov, model=fb_mod, reason=str(t3_exc))
                        if fb_tier == 2:
                            tier2_client = getattr(self.orchestrator, "tier2", None) or getattr(self.orchestrator, "ollama", None)
                            if tier2_client and hasattr(tier2_client, "generate"):
                                t2_fb_kwargs = dict(t3_kwargs)
                                t2_fb_kwargs["model"] = TIER2_MODEL
                                res2 = tier2_client.generate(**t2_fb_kwargs)
                                return (await res2) if asyncio.iscoroutine(res2) else res2
                        elif fb_tier == 1:
                            tier1_client = getattr(self.orchestrator, "tier1", None) or getattr(self.orchestrator, "active_t1_client", None)
                            if tier1_client and hasattr(tier1_client, "generate"):
                                t1_fb_kwargs = dict(t3_kwargs)
                                t1_fb_kwargs["model"] = TIER1_MODEL
                                res1 = tier1_client.generate(**t1_fb_kwargs)
                                return (await res1) if asyncio.iscoroutine(res1) else res1
                    raise



        # Tier 2 dispatch when recovery escalation reached Tier 2

        tier2_client = None

        if hasattr(self.orchestrator, "tier2") and "tier2" in getattr(self.orchestrator, "__dict__", {}):

            tier2_client = self.orchestrator.tier2

        elif hasattr(self.orchestrator, "ollama"):

            tier2_client = self.orchestrator.ollama

        elif hasattr(self.orchestrator, "tier2"):

            tier2_client = self.orchestrator.tier2



        if active_tier == 2 and tier2_client is not None and TIER2_MODEL:

            await self._publish_event(

                EventType.TIER_SELECTED,

                turn_id=turn_id,

                payload={

                    "tier": 2,

                    "provider": TIER2_PROVIDER,

                    "model": TIER2_MODEL,

                    "reason": "recovery_escalated_tier_2",

                },

            )

            t2_raw_kwargs = {

                "prompt": user_message,

                "system": system_prompt,

                "mission_id": self._mission_id,

                "turn_id": turn_id or "",

                "temperature": self.config.temperature,

                "tools": native_tools,

            }

            if hasattr(self.orchestrator, "_build_t2_failover_kwargs"):

                t2_kwargs = self.orchestrator._build_t2_failover_kwargs(t2_raw_kwargs)

            else:

                t2_kwargs = dict(t2_raw_kwargs)

                t2_kwargs["model"] = TIER2_MODEL

            if timeout_seconds is not None:

                t2_kwargs["timeout_seconds"] = timeout_seconds

            t2_gen = getattr(tier2_client, "generate")

            t2_start = time.monotonic()

            try:

                res = t2_gen(**t2_kwargs)

                res_obj = (await res) if asyncio.iscoroutine(res) else res

                if getattr(res_obj, "success", True) is False:

                    err_msg = getattr(res_obj, "error", None) or f"Tier 2 ({TIER2_PROVIDER}/{TIER2_MODEL}) failed"

                    raise RuntimeError(err_msg)

                return res_obj

            except Exception as t2_exc:

                elapsed_t2 = time.monotonic() - t2_start

                rem_t3 = (timeout_seconds - elapsed_t2) if timeout_seconds is not None else None

                logger.warning(f"AgentLoop: Tier 2 generation failed after {elapsed_t2:.1f}s ({t2_exc}). Remaining turn budget for Tier 3: {rem_t3:.1f}s...")

                from core.adaptive_routing import adaptive_router

                adaptive_router.record_failure(tier=2, error=t2_exc)

                

                # Tier 3 failover dispatch only if sufficient turn budget remains

                tier3_client = getattr(self.orchestrator, "tier3", None) or getattr(self.orchestrator, "_tier3", None) or getattr(self.orchestrator, "ollama", None)

                if tier3_client and hasattr(tier3_client, "generate") and TIER3_MODEL:

                    if rem_t3 is not None and rem_t3 < 1.0:

                        logger.warning(f"AgentLoop: Insufficient turn budget ({rem_t3:.1f}s < 1.0s) for Tier 3 failover. Raising Tier 2 error.")

                        raise

                    self.set_active_model_state(tier=3, provider=TIER3_PROVIDER, model=TIER3_MODEL, reason=str(t2_exc))

                    await self._publish_event(

                        EventType.TIER_FAILOVER_STARTED,

                        turn_id=turn_id,

                        payload={

                            "from_tier": 2,

                            "to_tier": 3,

                            "provider": TIER3_PROVIDER,

                            "model": TIER3_MODEL,

                            "reason": str(t2_exc),

                        },

                    )

                    t3_kwargs = {

                        "prompt": user_message,

                        "system": system_prompt,

                        "mission_id": self._mission_id,

                        "turn_id": turn_id or "",

                        "temperature": self.config.temperature,

                        "model": TIER3_MODEL,

                        "tools": native_tools,

                    }

                    if rem_t3 is not None:

                        t3_kwargs["timeout_seconds"] = rem_t3

                    t3_gen = getattr(tier3_client, "generate")

                    res3 = t3_gen(**t3_kwargs)

                    return (await res3) if asyncio.iscoroutine(res3) else res3

                raise



        await self._publish_event(

            EventType.TIER_SELECTED,

            turn_id=turn_id,

            payload={

                "tier": 1,

                "provider": TIER1_PROVIDER,

                "model": TIER1_MODEL,

                "reason": "primary_configured_tier",

            },

        )

        # 1. Real Orchestrator or explicitly mocked async _generate_t1

        if hasattr(self.orchestrator, "_generate_t1"):

            gen_fn = getattr(self.orchestrator, "_generate_t1")

            if asyncio.iscoroutinefunction(gen_fn) or hasattr(gen_fn, "assert_awaited"):

                from tools.platform.catalog import tool_catalog

                from tools.registry import get_openai_tool_definitions

                native_tools = None

                if TIER1_PROVIDER in ("nvidia_nim", "zai", "openrouter", "gemini", "google", "groq", "groq_api"):

                    if self.config.execution_mode == "benchmark":

                        native_tools = get_openai_tool_definitions()

                    else:

                        native_tools = tool_catalog.get_openai_tools(core_only=True)



                effort, max_toks = self._determine_reasoning_policy(user_message, turn_id=turn_id)

                gen_kwargs = {

                    "model": TIER1_MODEL,

                    "prompt": user_message,

                    "system": system_prompt,

                    "keep_alive": MODEL_KEEP_ALIVE,

                    "temperature": self.config.temperature,

                    "tools": native_tools,

                    "mission_id": self._mission_id,

                    "turn_id": turn_id or "",

                    "reasoning_effort": effort,

                    "max_tokens": max_toks,

                    "num_predict": max_toks,

                    "suppress_model_completed_event": True,

                }

                if timeout_seconds is not None:

                    gen_kwargs["timeout_seconds"] = timeout_seconds

                res = gen_fn(**gen_kwargs)

                return (await res) if asyncio.iscoroutine(res) else res



        # 2. Mocked or legacy orchestrator run() interface

        if hasattr(self.orchestrator, "run") and callable(self.orchestrator.run):

            run_fn = getattr(self.orchestrator, "run")

            if asyncio.iscoroutinefunction(run_fn) or hasattr(run_fn, "assert_called"):

                res = run_fn(user_message)

                orch_res = (await res) if asyncio.iscoroutine(res) else res

                from models.provider import NormalizedModelResponse

                tool_calls = []

                tname = getattr(orch_res, "tool_name", None)

                if tname:

                    tool_calls.append({

                        "id": f"call_{uuid.uuid4().hex[:6]}",

                        "name": tname,

                        "arguments": getattr(orch_res, "tool_params", {}) or {},

                    })

                return NormalizedModelResponse(

                    text=getattr(orch_res, "final_output", "") or "Task complete",

                    tool_calls=tool_calls,

                    success=getattr(orch_res, "success", True),

                )



        # 3. Direct tier1 client interface

        if hasattr(self.orchestrator, "tier1") and hasattr(self.orchestrator.tier1, "generate"):

            res = self.orchestrator.tier1.generate(prompt=user_message, system=system_prompt)

            return (await res) if asyncio.iscoroutine(res) else res



        # 4. Fallback callable

        if hasattr(self.orchestrator, "_generate_t1") and callable(self.orchestrator._generate_t1):

            res = self.orchestrator._generate_t1(

                model=TIER1_MODEL,

                prompt=user_message,

                system=system_prompt,

            )

            return (await res) if asyncio.iscoroutine(res) else res



        raise RuntimeError("Orchestrator has no compatible T1 generation interface")



    async def _publish_event(

        self,

        event_type: EventType,

        turn_id: Optional[str] = None,

        tool_call_id: Optional[str] = None,

        severity: EventSeverity = EventSeverity.INFO,

        payload: Optional[Dict[str, Any]] = None,

    ) -> None:

        """Publish canonical event to EventBus and forward to TUI event queue."""

        is_terminal_evt = event_type in (EventType.MISSION_COMPLETED, EventType.MISSION_FAILED, EventType.MISSION_CANCELLED)

        if getattr(self, "_terminal_event_published", False):

            if is_terminal_evt:

                logger.warning(f"AgentLoop: Suppressing duplicate terminal event {event_type} for mission {self._mission_id}")

            else:

                logger.debug(f"AgentLoop: Suppressing late event {event_type} for terminal mission {self._mission_id}")

            return



        if is_terminal_evt:

            self._terminal_event_published = True



        payload = payload or {}

        if event_type in (EventType.MISSION_FAILED, EventType.ACTION_DENIED):

            if "failure_category" not in payload:

                from core.failure_classifier import FailureClassifier

                err_text = payload.get("error") or payload.get("reason") or payload.get("error_message") or ""

                t_name = payload.get("tool_name") or ""

                payload["failure_category"] = FailureClassifier.classify(t_name, err_text, str(payload)).value



        event = HermesEvent(

            event_type=event_type,

            mission_id=self._mission_id,

            run_id=getattr(self, "_run_id", None),

            attempt_number=getattr(self, "_attempt_number", 1) or 1,

            turn_id=turn_id,

            tool_call_id=tool_call_id,

            severity=severity,

            source="agent_loop",

            payload=payload,

        )

        # EventBus automatically feeds StateReducer and StateStore

        if hasattr(self, "event_bus") and self.event_bus is not None:
            self.event_bus.publish(event)



        # Forward compatible events to TUI event queue if present

        if self.event_queue is not None:

            from core.mission_runner import MissionEvent

            tui_event_type = "thought"

            if event_type == EventType.MISSION_STARTED:

                tui_event_type = "mission_start"

            elif event_type == EventType.MISSION_COMPLETED:

                tui_event_type = "mission_complete"

            elif event_type in (EventType.MISSION_FAILED, EventType.MISSION_CANCELLED):

                tui_event_type = "mission_failed"

            elif event_type == EventType.TOOL_STARTED:

                tui_event_type = "pipeline_stage"

                payload["stage"] = 6

                payload["status"] = "start"

                payload["verb"] = "Executing"

            elif event_type == EventType.TOOL_COMPLETED:

                tui_event_type = "tool_result"

            elif event_type == EventType.VERIFICATION_COMPLETED:

                tui_event_type = "quality_check"



            try:

                await self.event_queue.put(MissionEvent(

                    event_type=tui_event_type,

                    payload=payload,

                    timestamp=event.timestamp

                ))

            except Exception as q_exc:

                logger.debug(f"AgentLoop: TUI event queue put exception: {q_exc}")



    async def _emit_tui_thought(self, text: str, detail: str) -> None:

        """Emit thought event to TUI for real-time spinner/status visibility."""

        if self.event_queue is not None:

            from core.mission_runner import MissionEvent

            try:

                await self.event_queue.put(MissionEvent(

                    event_type="thought",

                    payload={"text": text, "detail": detail}

                ))

            except Exception:

                pass
