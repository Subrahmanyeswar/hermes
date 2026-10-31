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
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from loguru import logger

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
FINAL_VERIFICATION_RESERVE_SECONDS: float = 10.0
MIN_MODEL_REQUEST_TIMEOUT_SECONDS: float = 15.0


def calculate_effective_turn_timeout(
    remaining_wall_time: float,
    configured_timeout: float = 360.0,
    reserve_seconds: float = FINAL_VERIFICATION_RESERVE_SECONDS,
    min_model_timeout: float = MIN_MODEL_REQUEST_TIMEOUT_SECONDS,
) -> Optional[float]:
    """
    Calculate effective model turn timeout ensuring verification reserve is never consumed.
    Never start a new model request when remaining budget cannot accommodate min request time + reserve.
    Never select an effective request timeout greater than the remaining usable budget.
    Returns float timeout if allowed, or None if remaining budget is insufficient.
    """
    if remaining_wall_time < (min_model_timeout + reserve_seconds):
        return None
    usable_budget = remaining_wall_time - reserve_seconds
    return min(float(configured_timeout), usable_budget)


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
        self._observation_history: List[Observation] = []
        self._recent_actions: List[Tuple[str, str]] = []
        self._tasks: List[Dict[str, Any]] = []
        self._active_task_idx: int = -1
        self._consecutive_planning_turns: int = 0
        self._consecutive_non_mutating_turns: int = 0
        self._file_write_counts: Dict[str, int] = {}
        self._read_fingerprint_tracker: Dict[str, Tuple[str, int]] = {}
        self._consecutive_no_progress_blocks: int = 0
        self._recovery_attempt_count: int = 0
        self._recovery_escalation_attempted: bool = False

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
                                        source_type=EvidenceSourceType.FUNCTIONAL_EVALUATION,
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
                                            source_type=EvidenceSourceType.FUNCTIONAL_EVALUATION,
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

    async def run(self, mission: Mission) -> AgentLoopResult:
        """
        Execute mission via model-driven agentic loop.
        Runs until an authoritative terminal state is reached or safety budget is exhausted.
        """
        self._start_time = time.monotonic()
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
        self._consecutive_no_progress_blocks = 0
        self._recovery_attempt_count = 0
        self._recovery_escalation_attempted = False
        from core.agent_loop.mvp_gate import WebsiteMvpGate
        ws_root = Path(self.workspace.workspace_root) if (self.workspace and hasattr(self.workspace, "workspace_root") and self.workspace.workspace_root) else Path(".")
        self.mvp_gate = WebsiteMvpGate(workspace_root=ws_root)

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
                if state_snap and getattr(state_snap, "mission", None) and getattr(state_snap.mission, "active_skills", None):
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
                    for s_name in routing_decision.selected_skills:
                        self.project_intelligence.load_skill_body(s_name)
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
                prof = classify_verification_profile(mission.user_prompt, workspace_path=str(ws_root), written_files=self._written_files)
                prof_res = VerificationProfileEvaluator.evaluate(prof, ws_root, mission.user_prompt, written_files=self._written_files)
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
                configured_timeout=float(getattr(self.config, "model_timeout_seconds", 360.0) or 360.0),
                reserve_seconds=FINAL_VERIFICATION_RESERVE_SECONDS,
                min_model_timeout=MIN_MODEL_REQUEST_TIMEOUT_SECONDS,
            )

            if turn_timeout is None:
                termination_reason = (
                    f"Insufficient remaining wall time budget ({remaining_wall_time:.1f}s < "
                    f"{MIN_MODEL_REQUEST_TIMEOUT_SECONDS + FINAL_VERIFICATION_RESERVE_SECONDS:.1f}s required for "
                    f"{MIN_MODEL_REQUEST_TIMEOUT_SECONDS:.1f}s minimum model request + {FINAL_VERIFICATION_RESERVE_SECONDS:.1f}s verification reserve)"
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
                termination_reason = f"Consecutive failure budget exceeded ({consecutive_failures} failures)"
                logger.error(f"AgentLoop: {termination_reason}")
                await self._publish_event(
                    EventType.MISSION_FAILED,
                    severity=EventSeverity.CRITICAL,
                    payload={"error": termination_reason}
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

                    # Escalate repeated stalls to consecutive_failures so the loop can terminate
                    self._stall_consecutive_count = getattr(self, "_stall_consecutive_count", 0) + 1
                    if self._stall_consecutive_count >= 3:
                        consecutive_failures += 1
                        self._stall_consecutive_count = 0
                        logger.warning(
                            f"AgentLoop: Stall repeated {self._stall_consecutive_count + 3}x "
                            f"— escalated to consecutive failure "
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
            await self._publish_event(
                EventType.TIER_SELECTED,
                turn_id=turn_id,
                payload={
                    "tier": 1,
                    "model": TIER1_MODEL,
                    "provider": TIER1_PROVIDER,
                    "headline": f"Selected Tier 1 ({TIER1_MODEL})",
                }
            )
            await self._publish_event(
                EventType.MODEL_REQUESTED,
                turn_id=turn_id,
                payload={"model": TIER1_MODEL, "provider": TIER1_PROVIDER}
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
                model_response = await self._generate_model_turn(system_prompt, user_message, turn_id=turn_id, timeout_seconds=turn_timeout)
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
                resp_model = getattr(model_response, "model", None) or TIER1_MODEL
                from config.model_config import TIER1_MODEL as C_T1, TIER2_MODEL as C_T2, TIER3_MODEL as C_T3
                resp_tier = 1 if resp_model == C_T1 else (2 if resp_model == C_T2 else 3)
                await self._publish_event(
                    EventType.MODEL_COMPLETED,
                    turn_id=turn_id,
                    payload={
                        "model": resp_model,
                        "tier": resp_tier,
                        "latency": t1_latency,
                        "duration_ms": int(t1_latency * 1000),
                        "headline": f"Thought for {t1_latency:.1f}s",
                    }
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
                await self._publish_event(
                    EventType.TIER_FAILOVER_STARTED,
                    turn_id=turn_id,
                    payload={
                        "from_tier": 1,
                        "to_tier": 2,
                        "headline": "Failover: Tier 1 -> Tier 2 (Ollama 120b)",
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
                self._consecutive_empty_turns = 0
                calls_to_run = getattr(decision, "tool_calls", None) or [
                    {"name": decision.tool_name, "arguments": decision.arguments, "id": decision.tool_call_id}
                ]
                has_mutated_in_turn = False
                break_to_terminal = False
                self._recovery_triggered_this_turn = False
                seen_signatures_in_turn: Set[str] = set()

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
                            consecutive_failures += 1
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
                        consecutive_failures += 1
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
                            consecutive_failures += 1
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
                                if target_repair and norm_target != target_repair.lower():
                                    target_disk = ws_dir_p / target_write_path
                                    if target_disk.exists() and target_disk.stat().st_size > 50 and self._file_write_counts.get(norm_target, 0) >= 1:
                                        if not any(norm_target in u.lower() for u in unmet_reqs_cur):
                                            logger.warning(f"AgentLoop: blocking redundant write on completed file '{target_write_path}' while '{target_repair}' needs attention")
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
                                                    f"Next step: call fs.write or fs.edit on '{target_repair}'."
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

                            if file_has_active_issue:
                                # When investigating an active defect or DOM mismatch, reading is permitted for diagnosis
                                should_block = False
                            else:
                                should_block = (read_count >= 3) or (was_written_in_mission and is_scaffold_incomplete and read_count >= 2)

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

                                # Deterministic loop breaker after 2 consecutive blocks (at most once per turn)
                                if self._consecutive_no_progress_blocks >= 2 and not getattr(self, "_recovery_triggered_this_turn", False):
                                    self._recovery_triggered_this_turn = True
                                    logger.warning(
                                        f"AgentLoop: Consecutive no-progress blocks reached {self._consecutive_no_progress_blocks}. "
                                        "Executing recovery transition."
                                    )
                                    recovery_handled = await self._execute_no_progress_recovery(
                                        turn_id=turn_id,
                                        mission=mission,
                                        unmet_reqs=unmet_reqs,
                                        rejection_reason=rejection_reason,
                                    )
                                    if not recovery_handled:
                                        # Deterministic In-Tier Correction before aborting: if actionable deliverable is missing, command fs.write
                                        target_file_to_write = None
                                        if unmet_reqs:
                                            from core.agent_loop.mvp_gate import WebsiteMvpGate
                                            tf, _ = WebsiteMvpGate.parse_scaffold_target(unmet_reqs[0])
                                            if tf and tf not in ("npm run build", "browser_open_preview"):
                                                target_file_to_write = tf

                                        in_tier_corrections = getattr(self, "_in_tier_correction_count", 0)
                                        if target_file_to_write and in_tier_corrections < 2:
                                            self._in_tier_correction_count = in_tier_corrections + 1
                                            logger.warning(
                                                f"AgentLoop: In-tier corrective directive issued for '{target_file_to_write}' (attempt {in_tier_corrections + 1}/2)"
                                            )
                                            from core.agent_loop.observations import Observation
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

                    self.network_supervisor.register_executed_tool_call(
                        call_id, turn_id=turn_id, action_key=action_key
                    )
                    turn.observation_ids.append(obs.observation_id)
                    self._record_observation(obs)
                    self._actions_count += 1
                    self._tool_calls_count += 1

                    # Track action pattern for stall detection
                    self._recent_actions.append((call_name, str(call_args)))

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
                    is_mutating = bool(obs.success and (call_name in ("fs.write", "fs.edit", "write_file", "edit_file", "write_files_batch", "download_image", "fetch_image") or bool(delta_files)))
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
                        consecutive_failures = 0
                        unchanged_read_governor_blocks = 0
                        if is_mutating:
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
                            if any(w in call_str for w in ("browser_open_preview", "open_preview", "browser.navigate", "navigate")):
                                self.mvp_gate.browser_verified = True

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
                            cur_task = self._tasks[self._active_task_idx] if (self._tasks and 0 <= self._active_task_idx < len(self._tasks)) else {}
                            cur_tid = cur_task.get("task_id", "")
                            cur_title = cur_task.get("title", "").lower()
                            is_test_or_verif = any(w in cur_tid.lower() or w in cur_title for w in ("test", "verif", "qualification", "check"))
                            is_test_file = any("test" in Path(f).name.lower() for f in delta_files)
                            if not is_test_or_verif or is_test_file:
                                # For website missions, verify scaffold deliverables exist before advancing requirements
                                if hasattr(self, "mvp_gate") and self.mvp_gate and WebsiteMvpGate.is_website_mission(mission.user_prompt or "", ws_dir_p, set(self._written_files)):
                                    scaffold_ok, _ = self.mvp_gate.check_scaffold_complete(ws_dir_p)
                                    if scaffold_ok or any(f.endswith((".js", ".html")) for f in delta_files):
                                        await self._advance_active_task(f"Progress recorded by {call_name}: {obs.summary}")
                                else:
                                    await self._advance_active_task(f"Progress recorded by {call_name}: {obs.summary}")
                        elif call_name in ("search.glob", "search.grep", "fs.read", "list_directory", "search_files", "verify"):
                            # If active task is a verification, test, or qualification requirement,
                            # or if target files exist and pass verification profile, advance task.
                            cur_task = self._tasks[self._active_task_idx] if (self._tasks and 0 <= self._active_task_idx < len(self._tasks)) else {}
                            cur_tid = cur_task.get("task_id", "")
                            cur_title = cur_task.get("title", "").lower()
                            is_test_or_verif = any(w in cur_tid.lower() or w in cur_title for w in ("test", "verif", "qualification", "check", "inspect", "summary"))

                            from core.verification_profiles import classify_verification_profile, VerificationProfileEvaluator, VerificationProfile
                            prof = classify_verification_profile(mission.user_prompt, written_files=self._written_files, task_id=cur_tid)
                            ws_root = Path(self.workspace.workspace_root) if (self.workspace and hasattr(self.workspace, "workspace_root") and self.workspace.workspace_root) else Path(".")

                            prof_res = VerificationProfileEvaluator.evaluate(prof, ws_root, mission.user_prompt, written_files=self._written_files, task_id=cur_tid)
                            if is_test_or_verif and prof_res.passed:
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
                                logger.error(
                                    f"AgentLoop: Case C Recovery: bounded failure after {unchanged_read_governor_blocks} unchanged read blocks. Issues: {issues}"
                                )
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
                            consecutive_failures += 1

                if break_to_terminal:
                    break

                if not has_mutated_in_turn:
                    self._consecutive_non_mutating_turns += 1

                # Forward progress thought to TUI
                await self._emit_tui_thought(
                    text=f"Executed {decision.tool_name}",
                    detail=obs.summary
                )

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

                if self._consecutive_empty_turns >= 2 or has_unmet_deliverables:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

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

                if self._consecutive_empty_turns >= 2 and consecutive_failures >= 2:
                    logger.warning(
                        f"AgentLoop: {self._consecutive_empty_turns} consecutive empty turns with {consecutive_failures} failures. "
                        "Triggering bounded recovery transition."
                    )
                    rec_ok = await self._trigger_recovery_transition(
                        turn_id=turn_id,
                        rejection_reason=f"Model stalled in reasoning-only loop ({self._consecutive_empty_turns} turns with 0 tool calls)",
                        unmet_reqs=unmet_list,
                    )
                    if not rec_ok:
                        termination_reason = "AGENT_NO_PROGRESS: Exhausted recovery transitions while in reasoning-only loop"
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
                payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}
            )

            self._turns_count += 1
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
                return True, "Repeated inspection on empty workspace.", "Implement the project entrypoint or required files using write_file."

        # Progress stagnation: only check if NO file mutations occurred recently and >= 8 turns without fingerprint change
        if hasattr(self, "planning_service") and self.planning_service:
            if hasattr(self.planning_service, "progress_controller"):
                ctrl = self.planning_service.progress_controller
                if getattr(ctrl, "_consecutive_identical_fingerprints", 0) >= 8 and getattr(self, "_consecutive_non_mutating_turns", 0) >= 4:
                    is_stalled, reason, advice = ctrl.detect_stall(stall_threshold_turns=8)
                    if is_stalled:
                        return True, reason, advice

        return False, "", ""

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
            recent_obs = self._observation_history[-4:]
            obs_lines = ["\nRECENT OBSERVATIONS (Ground Truth):"]
            for o in recent_obs:
                obs_lines.append(o.to_context_string())
            obs_text = "\n".join(obs_lines)

        recovery_suffix = f"\n\n{self._active_recovery_brief}" if getattr(self, "_active_recovery_brief", None) else ""
        user_message = (
            f"MISSION GOAL:\n{mission.user_prompt}\n\n"
            f"{ws_info}\n\n"
            f"{authoritative_state_block}\n"
            f"{skills_text}\n"
            f"{obs_text}\n\n"
            f"What is the next useful action to achieve the mission goal?{recovery_suffix}"
        )

        return system_prompt, user_message

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
        if recovery_count >= 2:
            logger.warning(f"AgentLoop: Recovery transitions exhausted ({recovery_count} >= 2).")
            return False

        self._recovery_attempt_count = recovery_count + 1
        current_tier = getattr(self.orchestrator, "_active_tier", 1)
        next_tier = current_tier + 1 if current_tier < 3 else None

        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
        )

        target_provider = TIER2_PROVIDER if next_tier == 2 else (TIER3_PROVIDER if next_tier == 3 else None)
        target_model = TIER2_MODEL if next_tier == 2 else (TIER3_MODEL if next_tier == 3 else None)

        if next_tier and target_model:
            logger.info(
                f"AgentLoop: Bounded recovery transition from Tier {current_tier} to Tier {next_tier} "
                f"({target_provider} / {target_model}) | reason: {rejection_reason}"
            )
            setattr(self.orchestrator, "_active_tier", next_tier)
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
            logger.warning(f"AgentLoop: No further tier available for recovery escalation from Tier {current_tier}.")
            if current_tier >= 3:
                return False

        # Reset consecutive stall/no-progress counters for the newly engaged tier
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
        Execute bounded recovery transition when model repeatedly requests no-progress operations.
        Delegates to canonical _trigger_recovery_transition.
        """
        return await self._trigger_recovery_transition(
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
        # 1. Recovery escalation
        if getattr(self, "_recovery_triggered_this_turn", False) or getattr(self, "_in_recovery", False) or getattr(self, "_consecutive_empty_turns", 0) > 0:
            return "high", 8192

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

        from tools.platform.catalog import tool_catalog
        from tools.registry import get_openai_tool_definitions
        native_tools = (
            get_openai_tool_definitions()
            if self.config.execution_mode == "benchmark"
            else tool_catalog.get_openai_tools(core_only=True)
        )

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
                res = t3_gen(**t3_kwargs)
                return (await res) if asyncio.iscoroutine(res) else res

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
            try:
                res = t2_gen(**t2_kwargs)
                res_obj = (await res) if asyncio.iscoroutine(res) else res
                if getattr(res_obj, "success", True) is False:
                    err_msg = getattr(res_obj, "error", None) or f"Tier 2 ({TIER2_PROVIDER}/{TIER2_MODEL}) failed"
                    raise RuntimeError(err_msg)
                return res_obj
            except Exception as t2_exc:
                logger.warning(f"AgentLoop: Tier 2 generation failed ({t2_exc}). Escalating failover to Tier 3 ({TIER3_PROVIDER}/{TIER3_MODEL})...")
                from core.adaptive_routing import adaptive_router
                adaptive_router.record_failure(tier=2, error=t2_exc)
                
                # Tier 3 failover dispatch
                tier3_client = getattr(self.orchestrator, "tier3", None) or getattr(self.orchestrator, "_tier3", None) or getattr(self.orchestrator, "ollama", None)
                if tier3_client and hasattr(tier3_client, "generate") and TIER3_MODEL:
                    setattr(self.orchestrator, "_active_tier", 3)
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
                    if timeout_seconds is not None:
                        t3_kwargs["timeout_seconds"] = timeout_seconds
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
