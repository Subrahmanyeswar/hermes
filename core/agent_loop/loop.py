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
from core.runtime_state.models import MissionStatus, WaitReason
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
    ) -> None:
        self.orchestrator = orchestrator
        self.workspace = workspace_manager or global_workspace
        self.event_bus = event_bus_instance or event_bus
        self.state_store = state_store_instance or state_store
        self.event_queue = event_queue
        self.abort_event = abort_event or asyncio.Event()
        self.user_input_callback = user_input_callback
        self.config = config or AgentLoopConfig()

        # Subsystems
        self._interpreter = DecisionInterpreter()
        orch_mode = getattr(self.orchestrator, "mode", "auto")
        mode_str = orch_mode if (isinstance(orch_mode, str) and orch_mode in ("auto", "plan", "safe")) else "auto"
        self._action_executor = ActionExecutor(mode=mode_str)
        self._completion_policy = CompletionPolicy()

        # Project Intelligence 2.x & Context Engine 2.x (Prompts 7 & 8)
        from core.context.engine import ContextEngine
        from core.project_intelligence.registry import ProjectIntelligenceRegistry
        self.project_intelligence = ProjectIntelligenceRegistry(
            workspace_root=self.workspace.root_str if hasattr(self.workspace, "root_str") and self.workspace.root_str else None,
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

        # Runtime trackers
        self._start_time: float = 0.0
        self._mission_id: str = ""
        self._turns_count: int = 0
        self._actions_count: int = 0
        self._tool_calls_count: int = 0
        self._verification_calls_count: int = 0
        self._written_files: List[str] = []
        self._observation_history: List[Observation] = []
        self._recent_actions: List[Tuple[str, str]] = []

    # ── Main continuous execution loop ────────────────────────────────────────

    async def run(self, mission: Mission) -> AgentLoopResult:
        """
        Execute mission via model-driven agentic loop.
        Runs until an authoritative terminal state is reached or safety budget is exhausted.
        """
        self._start_time = time.monotonic()
        self._mission_id = mission.mission_id
        self.state_store = self.event_bus.get_or_create_state(mission.mission_id)
        self._turns_count = 0
        self._actions_count = 0
        self._tool_calls_count = 0
        self._verification_calls_count = 0
        self._written_files.clear()
        self._observation_history.clear()
        self._recent_actions.clear()

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

        logger.info(f"AgentLoop: starting mission '{mission.mission_id}' in {self.config.execution_mode} mode")

        # Mission Planning Service 2.x (Prompt 9)
        self.planning_service = MissionPlanningService(
            mission_id=mission.mission_id,
            workspace_root=self.workspace.root_str if hasattr(self.workspace, "root_str") and self.workspace.root_str else None,
            event_bus=self.event_bus,
            state_store=self.state_store,
        )
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

        consecutive_failures = 0
        final_output = ""
        termination_reason = None
        mission_success = False

        # ── The Agent Loop ────────────────────────────────────────────────────
        while True:
            # 1. Check Abort / Cancellation
            if self.abort_event.is_set():
                logger.warning(f"AgentLoop: abort signal detected for mission {self._mission_id}")
                termination_reason = "Cancelled by user"
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

            # 3. Check Safety Budgets
            elapsed_time = time.monotonic() - self._start_time
            if elapsed_time > self.config.max_wall_time_seconds:
                termination_reason = f"Max wall time exceeded ({elapsed_time:.1f}s > {self.config.max_wall_time_seconds}s)"
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
            if self._detect_stall():
                stall_msg = "Repeated identical action detected without state change. Modifying strategy."
                logger.warning(f"AgentLoop: {stall_msg}")
                await self._publish_event(
                    EventType.AGENT_STALL_DETECTED,
                    payload={"reason": stall_msg}
                )
                self._observation_history.append(
                    Observation(
                        observation_id=f"obs_stall_{uuid.uuid4().hex[:6]}",
                        mission_id=self._mission_id,
                        source_type="system",
                        source_id="stall_detector",
                        success=False,
                        summary="Stall warning: do not repeat the same action.",
                        content=(
                            "SYSTEM NOTICE: You have repeated the same tool call with identical parameters. "
                            "Please inspect previous errors, try an alternative approach, or verify current progress."
                        )
                    )
                )

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
                EventType.MODEL_REQUESTED,
                turn_id=turn_id,
                payload={"model": TIER1_MODEL, "provider": TIER1_PROVIDER}
            )

            try:
                model_response = await self._generate_model_turn(system_prompt, user_message)
                t1_latency = time.monotonic() - t1_start
                await self._publish_event(
                    EventType.MODEL_COMPLETED,
                    turn_id=turn_id,
                    payload={"model": TIER1_MODEL, "latency": t1_latency}
                )
            except Exception as t1_exc:
                t1_latency = time.monotonic() - t1_start
                logger.error(f"AgentLoop: model generation failed ({t1_exc})")
                await self._publish_event(
                    EventType.MODEL_FAILED,
                    turn_id=turn_id,
                    severity=EventSeverity.ERROR,
                    payload={"error": str(t1_exc), "latency": t1_latency}
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
                await asyncio.sleep(0.5)
                continue

            # 8. Interpret Decision
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
                # Plan Mode gating check
                if hasattr(self, "planning_service") and self.planning_service and self.planning_service.plan_controller.execution_mode.value == "plan":
                    allowed, reason = self.planning_service.plan_controller.authorize_tool_call(
                        tool_name=decision.tool_name or "",
                        arguments=decision.arguments,
                    )
                    if not allowed:
                        logger.warning(f"AgentLoop: plan mode blocked mutation action {decision.tool_name}")
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
                        turn.completed_at = time.monotonic()
                        turn.state_version_after = self.state_store.get_snapshot().state_version
                        await self._publish_event(
                            EventType.AGENT_TURN_COMPLETED,
                            turn_id=turn_id,
                            payload={"turn_id": turn_id, "duration": turn.completed_at - turn.started_at}
                        )
                        self._turns_count += 1
                        continue

                action = ActionEnvelope(
                    mission_id=self._mission_id,
                    turn_id=turn_id,
                    tool_call_id=decision.tool_call_id,
                    tool_name=decision.tool_name,
                    arguments=decision.arguments,
                    policy_context={"user_prompt": mission.user_prompt},
                )
                turn.action_ids.append(action.action_id)

                obs = await self._action_executor.execute_action(action, workspace=self.workspace)
                turn.observation_ids.append(obs.observation_id)
                self._record_observation(obs)
                self._actions_count += 1
                self._tool_calls_count += 1

                # Track action pattern for stall detection
                self._recent_actions.append((decision.tool_name or "", str(decision.arguments)))

                if obs.success:
                    consecutive_failures = 0
                    # Record created files
                    delta_files = obs.metadata.get("files_created", [])
                    for f in delta_files:
                        if f not in self._written_files:
                            self._written_files.append(f)
                    if hasattr(self, "planning_service") and self.planning_service:
                        self.planning_service.update_progress(
                            event_summary=f"Executed {decision.tool_name}: {obs.summary}",
                            modified_files=set(delta_files),
                        )
                else:
                    consecutive_failures += 1

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
                    workspace=self.workspace,
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

            elif decision.decision_type in (AgentDecisionType.COMPLETE, AgentDecisionType.CONTINUE_REASONING):
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
                    workspace=self.workspace,
                    acceptance_criteria=mission.acceptance_criteria,
                    written_files=self._written_files,
                    runtime_state=self.state_store.get_state() if self.state_store else None,
                    acceptance_ledger=getattr(self.planning_service, "acceptance_ledger", None) if getattr(self, "planning_service", None) else None,
                    evidence_store=self.evidence_store,
                    strict_requirements=strict_req,
                )

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
                    await self._publish_event(
                        EventType.MISSION_COMPLETED,
                        turn_id=turn_id,
                        payload={"reason": v_reason, "files_created": self._written_files}
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
            await asyncio.sleep(0.1)

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

    def _detect_stall(self) -> bool:
        """Detect repeated identical actions or stalled progress fingerprint."""
        if hasattr(self, "planning_service") and self.planning_service:
            is_stalled, reason, advice = self.planning_service.progress_controller.detect_stall(stall_threshold_turns=3)
            if is_stalled:
                return True

        window_size = self.config.stall_window_size
        if len(self._recent_actions) < window_size:
            return False

        last_actions = self._recent_actions[-window_size:]
        first = last_actions[0]
        return all(a == first for a in last_actions)

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
            "- task.todo: Checklist management\n"
            "- user.ask: Ask user clarifying questions\n"
            "- tool_search: Discover specialized capabilities on demand\n"
            "Tool results are ground truth observations.\n"
            "Do not claim actions happened unless their results support that claim.\n"
            "Continue iterating when work is incomplete.\n"
            "Use available evidence and tests to verify your implementation.\n"
            "Do not invent tools. Emit valid tool calls.\n"
            "When the mission is completely implemented and verified, provide a final response."
        )

        # 2. Workspace Skeleton
        ws_info = "Workspace: generated_projects/"
        if self.workspace and self.workspace.is_locked:
            ws_summary = self.workspace.get_workspace_summary()
            skeleton = self.workspace.get_skeleton()
            ws_info = (
                f"Workspace: {ws_summary.get('root', 'active')}\n"
                f"Framework: {ws_summary.get('framework', 'unknown')}\n"
                f"Files ({ws_summary.get('total_files', 0)}):\n{skeleton[:600]}"
            )

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
                    content=f"Goal:\n{mission.user_prompt}\n\n{ws_info}",
                    provenance=ContextProvenance(source_type=ContextSourceType.USER, source_id=mission.mission_id),
                    priority=ContextPriority.MANDATORY,
                    pinned=True,
                ))
                # Sync planning service to context engine
                if hasattr(self, "planning_service") and self.planning_service:
                    try:
                        self.planning_service.sync_to_context_engine(self.context_engine)
                    except Exception as sync_exc:
                        logger.warning(f"AgentLoop: planning context sync warning: {sync_exc}")

                pack = self.context_engine.build_context(
                    mission_goal=mission.user_prompt,
                    state_snapshot=state,
                    turn_number=self._turns_count + 1,
                )
                messages = pack.to_messages()
                return messages[0]["content"], messages[1]["content"]
            except Exception as ctx_exc:
                logger.warning(f"AgentLoop: ContextEngine assembly encountered ({ctx_exc}), falling back to direct context")

        # Fallback to direct assembly
        obs_text = ""
        if self._observation_history:
            recent_obs = self._observation_history[-4:]
            obs_lines = ["\nRECENT OBSERVATIONS (Ground Truth):"]
            for o in recent_obs:
                obs_lines.append(o.to_context_string())
            obs_text = "\n".join(obs_lines)

        user_message = (
            f"MISSION GOAL:\n{mission.user_prompt}\n\n"
            f"{ws_info}\n"
            f"{obs_text}\n\n"
            f"What is the next useful action to achieve the mission goal?"
        )

        return system_prompt, user_message

    async def _generate_model_turn(self, system_prompt: str, user_message: str) -> Any:
        """Call T1 model using orchestrator client, provider, or mock bridge."""
        # 1. Real Orchestrator or explicitly mocked async _generate_t1
        if hasattr(self.orchestrator, "_generate_t1"):
            gen_fn = getattr(self.orchestrator, "_generate_t1")
            if asyncio.iscoroutinefunction(gen_fn) or hasattr(gen_fn, "assert_awaited"):
                from tools.platform.catalog import tool_catalog
                from tools.registry import get_openai_tool_definitions
                native_tools = None
                if TIER1_PROVIDER == "nvidia_nim":
                    if self.config.execution_mode == "benchmark":
                        native_tools = get_openai_tool_definitions()
                    else:
                        native_tools = tool_catalog.get_openai_tools(core_only=True)

                res = gen_fn(
                    model=TIER1_MODEL,
                    prompt=user_message,
                    system=system_prompt,
                    keep_alive=MODEL_KEEP_ALIVE,
                    temperature=self.config.temperature,
                    num_ctx=4096,
                    tools=native_tools,
                )
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
        payload = payload or {}
        event = HermesEvent(
            event_type=event_type,
            mission_id=self._mission_id,
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
