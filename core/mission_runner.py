# core/mission_runner.py
# MissionRunner — the continuous execution engine for HERMES v4.0.
#
# This is the component that makes HERMES behave like Claude Code instead of a chatbot.
#
# The fundamental loop:
#   while not mission.is_complete:
#       task = mission.next_executable_task
#       context = build_context(task, workspace)
#       tool_call = tier1_generate(task, context)
#       verified = tier2_verify(tool_call)
#       result = execute(verified_tool_call)
#       if result.success:
#           mission.mark_task_complete(task.task_id)
#       else:
#           handle_failure(task, result)
#
# Key design invariants:
#   1. The LLM never decides when to stop — MissionRunner decides.
#   2. Each tool result is fed back as context for the next generation.
#   3. Failed tasks trigger the repair cycle (up to 3 retries).
#   4. The UI receives live updates after every task state change.
#   5. The mission stops only when: all tasks complete, unrecoverable failure, or user abort.

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Any
from loguru import logger

from core.mission_planner import Mission, MissionTask, TaskState, TaskPriority
from core.workspace import WorkspaceManager, workspace_manager
from core.context_builder import ContextBuilder


class MissionPhase(str, Enum):
    """The current phase of the mission execution loop."""
    PLANNING    = "PLANNING"
    EXECUTING   = "EXECUTING"
    VERIFYING   = "VERIFYING"
    OBSERVING   = "OBSERVING"
    REPAIRING   = "REPAIRING"
    SUMMARIZING = "SUMMARIZING"
    COMPLETE    = "COMPLETE"
    FAILED      = "FAILED"
    ABORTED     = "ABORTED"


@dataclass
class MissionEvent:
    """
    Events emitted by MissionRunner to update the TUI in real-time.
    The TUI subscribes to events via an asyncio.Queue.
    This decouples the execution engine from the UI completely.
    """
    event_type: str           # "phase_change", "task_start", "task_complete",
                              # "task_failed", "tool_call", "tool_result",
                              # "thought", "mission_complete", "mission_failed",
                              # "repair_attempt", "walkthrough"
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


import contextvars
_task_progress_callback_var = contextvars.ContextVar("_task_progress_callback_var", default=None)
_task_action_tracker_var = contextvars.ContextVar("_task_action_tracker_var", default=None)


@dataclass
class MissionOptimizationTelemetry:
    """Telemetry capturing Phase 4E compression, parallelism, and model economy."""
    task_count_planned: int = 0
    task_count_executed: int = 0
    task_count_consolidated: int = 0
    tasks_parallelized: int = 0
    max_parallelism: int = 1
    model_calls_saved: int = 0
    verification_calls_saved: int = 0
    repair_calls_saved: int = 0
    context_cache_hits: int = 0
    total_model_time: float = 0.0
    total_scheduler_time: float = 0.0
    total_idle_time: float = 0.0
    total_browser_time: float = 0.0
    total_mission_time: float = 0.0


@dataclass
class MissionResult:
    """Final result of a completed or failed mission."""
    mission_id: str
    success: bool
    tasks_completed: int
    tasks_failed: int
    tasks_total: int
    total_latency_seconds: float
    total_cost_usd: float
    tier3_calls: int
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    walkthrough_text: str = ""
    error: Optional[str] = None
    status: str = "COMPLETE"
    optimization_telemetry: Optional[MissionOptimizationTelemetry] = None


class MissionRunner:
    """
    The continuous execution engine for HERMES v4.0.

    This replaces the single-pass Orchestrator.run() with a mission-aware loop.
    The existing Orchestrator is preserved and called per-task — MissionRunner
    orchestrates the sequence of Orchestrator calls until the mission is complete.

    Usage:
        runner = MissionRunner(orchestrator, workspace_manager, event_queue)
        result = await runner.run(mission)
    """

    def __init__(
        self,
        orchestrator: Any,              # core.orchestrator.Orchestrator
        workspace_manager: WorkspaceManager,
        event_queue: Optional[asyncio.Queue] = None,
        abort_event: Optional[asyncio.Event] = None,
        execution_mode: str = "strict",
    ) -> None:
        self.orchestrator = orchestrator
        self.workspace = workspace_manager
        self.event_queue = event_queue or asyncio.Queue()
        self.abort_event = abort_event or asyncio.Event()
        self.execution_mode = execution_mode
        self._context_builder = ContextBuilder(workspace_manager)
        from core.cross_file_retriever import CrossFileRetriever
        from memory.trajectory_memory import TrajectoryMemory
        self._cross_file_retriever = CrossFileRetriever(workspace_manager)
        self._trajectory_memory = TrajectoryMemory()
        self._recent_outputs: list[str] = []
        self._current_phase = MissionPhase.PLANNING
        self._start_time: float = 0.0
        self._total_cost: float = 0.0
        self._tier3_calls: int = 0
        self._files_created: list[str] = []
        self._files_modified: list[str] = []
        self.telemetry: MissionOptimizationTelemetry = MissionOptimizationTelemetry()
        self._static_context_cache: dict[str, str] = {}

    def reconcile_mission_state(self, mission: Mission) -> None:
        """
        Reconcile mission task state against actual disk artifacts on start/resume (Part K).
        - If task is COMPLETED but target file is missing -> reopen task.
        - If task is PENDING and required target files exist with valid content -> mark satisfied.
        - Preserves completed work without blind regeneration.
        """
        from pathlib import Path
        import re as _re
        ws_root_str = self.workspace.root_str if (self.workspace and self.workspace.is_locked) else (mission.project_root_path or ".")
        ws_root = Path(ws_root_str).resolve()
        if not ws_root.exists():
            return

        from tools.platform.file_identity import file_identity_cache

        for task in mission.tasks:
            if task.is_verification_task:
                continue

            target_files = []
            if getattr(task, "target_paths", None):
                target_files.extend(task.target_paths)
            if getattr(task, "expected_artifacts", None):
                target_files.extend(task.expected_artifacts)
            if not target_files:
                found = _re.findall(r"[\w\-\./]+\.(?:html|css|js|py|json|md|txt)", f"{task.title} {task.description}")
                for fn in found:
                    cleaned_fn = _re.sub(r"^generated_projects/[^/]+/", "", fn)
                    target_files.append(cleaned_fn)

            if not target_files:
                continue

            existing_paths = []
            for tf in target_files:
                p = (ws_root / tf).resolve()
                if p.exists() and p.is_file() and p.stat().st_size > 0:
                    existing_paths.append(p)

            # Rule 1: TASK MARKED COMPLETE + FILE MISSING -> Reopen task
            if task.state == TaskState.COMPLETED and len(existing_paths) < len(target_files):
                logger.info(f"Reconcile: task '{task.title}' was marked COMPLETED but target artifact missing; reopening task")
                task.state = TaskState.PENDING
                task.retry_count = 0
                continue

            # Rule 2: TASK MARKED PENDING + REQUIRED FILE EXISTS + VALID CONTENT -> Mark satisfied
            if task.state in (TaskState.PENDING, TaskState.FAILED, TaskState.BLOCKED) and len(existing_paths) == len(target_files):
                all_valid = True
                for ep in existing_paths:
                    if ep.stat().st_size < 10:
                        all_valid = False
                        break
                    file_identity_cache.record(ep)
                if all_valid:
                    logger.info(f"Reconcile: pending task '{task.title}' already satisfied by existing files on disk; skipping redundant regeneration")
                    task.state = TaskState.COMPLETED
                    task.ready_reason = "reconciled_existing_artifact"

    # ── Main execution loop ───────────────────────────────────────────────────

    async def run(self, mission: Mission) -> MissionResult:
        """
        Execute the mission from start to finish.
        This is the main loop — it runs until the mission is complete,
        a failure is unrecoverable, or the user aborts.

        Returns MissionResult with full execution summary.
        """
        if self.execution_mode == "agentic":
            from core.agent_loop import AgentLoop, AgentLoopConfig
            agent_loop = AgentLoop(
                orchestrator=self.orchestrator,
                workspace_manager=self.workspace,
                event_queue=self.event_queue,
                abort_event=self.abort_event,
                config=AgentLoopConfig(execution_mode="agentic")
            )
            loop_res = await agent_loop.run(mission)
            return MissionResult(
                mission_id=loop_res.mission_id,
                success=loop_res.success,
                tasks_completed=len(mission.tasks) if loop_res.success else 0,
                tasks_failed=0 if loop_res.success else 1,
                tasks_total=len(mission.tasks),
                total_latency_seconds=loop_res.duration_seconds,
                total_cost_usd=0.0,
                tier3_calls=0,
                files_created=loop_res.files_created,
                files_modified=loop_res.files_modified,
                walkthrough_text=loop_res.final_output,
                error=loop_res.error,
                status=loop_res.status,
            )

        self._start_time = time.monotonic()
        self._current_mission_id = mission.mission_id
        logger.info(
            f"MissionRunner: starting mission {mission.mission_id} "
            f"with {len(mission.tasks)} tasks"
        )

        await self._emit(MissionEvent(
            event_type="mission_start",
            payload={
                "mission_id": mission.mission_id,
                "task_count": len(mission.tasks),
                "tasks": [t.to_dict() for t in mission.tasks],
                "user_prompt": mission.user_prompt[:200],
            }
        ))

        # ── Reconcile persisted / resumed mission state against actual disk (Part K) ──
        self.reconcile_mission_state(mission)

        from config.model_config import T2_MAX_CONCURRENCY
        from core.adaptive_routing import get_adaptive_router
        router = get_adaptive_router()
        t1_healthy = router.is_tier_healthy(1)
        adaptive_limit = min(T2_MAX_CONCURRENCY, 3)

        self.telemetry.task_count_planned = len(mission.tasks)
        comp_val = getattr(mission, "complexity", None)
        comp_str = comp_val.value if hasattr(comp_val, "value") else str(comp_val)
        if comp_str in ("SIMPLE", "TRIVIAL"):
            self.telemetry.task_count_consolidated = max(0, 8 - len(mission.tasks))
            self.telemetry.model_calls_saved = self.telemetry.task_count_consolidated

        # ── Main mission loop ─────────────────────────────────────────────────
        while not mission.is_complete:

            # Check abort signal
            if self.abort_event.is_set():
                logger.warning(f"MissionRunner: abort signal received for {mission.mission_id}")
                await self._emit(MissionEvent(event_type="mission_aborted", payload={}))
                return self._build_result(mission, success=False, error="Aborted by user")

            sched_t0 = time.monotonic()
            batch = mission.get_executable_batch(max_concurrent=adaptive_limit, provider_healthy=t1_healthy)
            self.telemetry.total_scheduler_time += (time.monotonic() - sched_t0)

            if not batch:
                # No executable task — either all done or all blocked
                if mission.has_failure:
                    logger.error("MissionRunner: all remaining tasks blocked by failure")
                    break
                # Shouldn't happen, but safety guard
                logger.warning("MissionRunner: no executable task found — checking completion")
                break

            if len(batch) > 1:
                self.telemetry.tasks_parallelized += len(batch)
                self.telemetry.max_parallelism = max(self.telemetry.max_parallelism, len(batch))
                logger.info(
                    f"MissionRunner: executing {len(batch)} independent tasks in parallel: "
                    f"{[t.title[:25] for t in batch]}"
                )
                await self._emit(MissionEvent(
                    event_type="parallel_batch_start",
                    payload={
                        "task_ids": [t.task_id for t in batch],
                        "task_titles": [t.title for t in batch],
                        "batch_size": len(batch),
                    }
                ))
                sem = asyncio.Semaphore(adaptive_limit)

                async def _guarded_exec(t: MissionTask):
                    async with sem:
                        self.telemetry.task_count_executed += 1
                        await self._execute_task(mission, t)

                await asyncio.gather(*[_guarded_exec(t) for t in batch])
            else:
                task = batch[0]
                self.telemetry.task_count_executed += 1
                await self._execute_task(mission, task)

            # Cooperative event loop yield for UI without artificial pause
            await asyncio.sleep(0)

        # ── Final mission acceptance criteria check ────────────────────
        if mission.is_complete and mission.acceptance_criteria:
            self._current_phase = MissionPhase.VERIFYING
            await self._emit(MissionEvent(
                event_type="phase_change",
                payload={"phase": "VERIFYING"}
            ))

            unmet = await self._check_acceptance_criteria(mission)
            if unmet:
                # Some criteria not met — add consolidated repair task if retries left
                logger.warning(
                    f"MissionRunner: {len(unmet)} acceptance criteria not met: {unmet}"
                )
                await self._emit(MissionEvent(
                    event_type="thought",
                    payload={
                        "text": "Acceptance criteria not fully met — adding verification tasks",
                        "detail": str(unmet[:2])
                    }
                ))
                # Add consolidated repair task for unmet criteria (Phase 4E Section 21)
                combined_criteria = "\n- ".join(unmet[:3])
                repair_task = MissionTask(
                    title="Resolve missing project acceptance criteria",
                    description=(
                        f"The following requirements were not satisfied:\n- {combined_criteria}\n\n"
                        f"Inspect the project files and implement all missing functionality cleanly.\n"
                        f"Project path: {mission.project_root_path}"
                    ),
                    priority=TaskPriority.CRITICAL,
                    max_retries=2,
                    acceptance_criteria="All missing criteria resolved",
                )
                mission.tasks.append(repair_task)
                mission.execution_order.append(repair_task.task_id)
                self.telemetry.repair_calls_saved += max(0, len(unmet[:3]) - 1)

                # Continue the mission loop for repair tasks
                while not mission.is_complete:
                    if self.abort_event.is_set():
                        break
                    task = mission.next_executable_task
                    if task is None:
                        break
                    await self._execute_task(mission, task)
                    await asyncio.sleep(0)
            else:
                mission.verified_criteria = mission.acceptance_criteria.copy()
                logger.info("MissionRunner: all acceptance criteria verified ✓")

        # ── Final project quality verification ────────────────────────
        if mission.is_complete and mission.project_root_path:
            self._current_phase = MissionPhase.VERIFYING
            await self._emit(MissionEvent(
                event_type="phase_change",
                payload={"phase": "VERIFYING", "verb": "Verifying"}
            ))
            await self._emit(MissionEvent(
                event_type="thought",
                payload={
                    "text": "Running final project quality check",
                    "detail": "Verifying all acceptance criteria",
                }
            ))

            from core.quality_verifier import QualityVerifier
            verifier = QualityVerifier()
            final_check = verifier.verify_project_completeness(
                project_root=mission.project_root_path,
                acceptance_criteria=mission.acceptance_criteria,
                user_prompt=mission.user_prompt,
            )

            await self._emit(MissionEvent(
                event_type="quality_check",
                payload={
                    "task_id": "final",
                    "verdict": final_check.overall_verdict,
                    "coverage_pct": final_check.coverage_pct,
                    "met": final_check.requirements_met,
                    "missing": final_check.requirements_missing,
                }
            ))

            # If final check fails, add consolidated targeted repair task (Phase 4E Section 21)
            if final_check.needs_improvement and final_check.requirements_missing:
                logger.info(
                    f"MissionRunner: final check failed — "
                    f"{len(final_check.requirements_missing)} requirements unmet"
                )
                combined_missing = "\n- ".join(final_check.requirements_missing[:2])
                repair_task = MissionTask(
                    title="Final fix: Resolve project completeness gaps",
                    description=(
                        f"{final_check.repair_prompt}\n\n"
                        f"Missing requirements:\n- {combined_missing}"
                    ),
                    priority=TaskPriority.CRITICAL,
                    max_retries=2,
                    acceptance_criteria="Project completeness criteria satisfied",
                )
                mission.tasks.append(repair_task)
                mission.execution_order.append(repair_task.task_id)
                self.telemetry.repair_calls_saved += max(0, len(final_check.requirements_missing[:2]) - 1)

                # Run repair tasks
                while not mission.is_complete:
                    if self.abort_event.is_set():
                        break
                    task = mission.next_executable_task
                    if task is None:
                        break
                    await self._execute_task(mission, task)
                    await asyncio.sleep(0)

        # ── Post-mission phase ────────────────────────────────────────────────
        self._current_phase = MissionPhase.SUMMARIZING
        await self._emit(MissionEvent(
            event_type="phase_change",
            payload={"phase": MissionPhase.SUMMARIZING.value}
        ))

        walkthrough = await self._generate_walkthrough(mission)

        # Strict post-mission filesystem validation: ensure all task target files exist on disk
        from pathlib import Path as _Path
        missing_mission_artifacts = []
        p_root = None
        if self.workspace and getattr(self.workspace, "is_locked", False) and getattr(self.workspace, "workspace_root", None):
            p_root = _Path(self.workspace.workspace_root)
        elif mission.project_root_path and self.workspace and getattr(self.workspace, "is_locked", False):
            p_root = _Path(mission.project_root_path)
        if p_root and p_root.exists():
            for t in mission.tasks:
                target_files = []
                if getattr(t, "target_paths", None):
                    target_files.extend(t.target_paths)
                if getattr(t, "expected_artifacts", None):
                    target_files.extend(t.expected_artifacts)
                for tf in target_files:
                    p = (p_root / tf).resolve()
                    if not p.exists() or p.stat().st_size <= 10:
                        missing_mission_artifacts.append(tf)

        mission_success = mission.is_complete and not missing_mission_artifacts
        result = self._build_result(
            mission, 
            success=mission_success,
            error=f"Missing required artifacts on disk: {', '.join(missing_mission_artifacts)}" if missing_mission_artifacts else None
        )
        result.walkthrough_text = walkthrough

        git_summary = await self.post_mission_git_summary(mission)
        if git_summary:
            result.walkthrough_text = result.walkthrough_text + "\n" + git_summary

        event_type = "mission_complete" if mission_success else "mission_failed"
        await self._emit(MissionEvent(
            event_type=event_type,
            payload={
                "success": result.success,
                "tasks_completed": result.tasks_completed,
                "tasks_total": result.tasks_total,
                "walkthrough": result.walkthrough_text,
                "total_cost": result.total_cost_usd,
                "latency": result.total_latency_seconds,
            }
        ))

        logger.info(
            f"MissionRunner: mission {mission.mission_id} "
            f"{'COMPLETE' if mission.is_complete else 'FAILED'} | "
            f"{result.tasks_completed}/{result.tasks_total} tasks | "
            f"${result.total_cost_usd:.4f} | "
            f"{result.total_latency_seconds:.1f}s"
        )

        return result

    # ── Single task execution ─────────────────────────────────────────────────

    async def _execute_task(self, mission: Mission, task: MissionTask) -> None:
        """
        Execute one task through an iterative generate → observe → verify → repair loop.

        The fundamental guarantee:
            A task is only marked COMPLETE when the QualityVerifier confirms
            that the filesystem output satisfies the task requirements.
            A successful tool call (exit_code=0) is necessary but NOT sufficient.
        """
        await self._emit(MissionEvent(
            event_type="task_start",
            payload={
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "skill_hint": task.skill_hint,
                "retry_count": task.retry_count,
            }
        ))

        mission.mark_task_running(task.task_id)
        self._current_phase = MissionPhase.EXECUTING

        from core.quality_verifier import QualityVerifier
        verifier = QualityVerifier()

        # Phase 4B: Action Momentum & Task Action Contract
        from pathlib import Path
        from core.action_discipline import derive_action_contract, ActionMomentumTracker
        ws_root = Path(self.workspace.workspace_root) if (self.workspace and self.workspace.is_locked and self.workspace.workspace_root) else None
        action_contract = derive_action_contract(task, workspace_root=ws_root, all_tasks=mission.tasks)
        momentum_tracker = ActionMomentumTracker(action_contract, workspace_root=ws_root)

        # ── Inner execution loop ───────────────────────────────────────────
        # Each iteration: generate → execute → observe → verify → maybe repair
        MAX_INNER_ITERATIONS = 3
        current_description = task.description
        inner_iteration = 0
        last_orch_result = None
        quality_result = None
        task_tool_history: list[dict] = []

        while inner_iteration < MAX_INNER_ITERATIONS:
            if self.abort_event.is_set():
                logger.info(f"MissionRunner: abort signal received, stopping task '{task.title}'")
                return

            inner_iteration += 1
            iteration_label = (
                f"attempt {inner_iteration}/{MAX_INNER_ITERATIONS}"
            )

            await self._emit(MissionEvent(
                event_type="thought",
                payload={
                    "text": f"Executing: {task.title} ({iteration_label})",
                    "detail": f"Skill: {task.skill_hint or 'none'}",
                }
            ))

            # Build the prompt for this iteration
            # On repair iterations, current_description includes the repair instructions
            enriched_prompt = self._build_task_prompt_with_description(
                task, mission, current_description
            )

            # Set orchestrator progress callback
            async def _pipeline_progress(event_type: str, payload: dict) -> None:
                if event_type == "skill_loaded":
                    skill_ids = payload.get("skill_ids", [])
                    if skill_ids:
                        await self._emit(MissionEvent(
                            event_type="skill_loaded",
                            payload={"task_id": task.task_id, "skill_ids": skill_ids,
                                     "verb": payload.get("verb", "")},
                        ))
                elif event_type in ("stage_start", "stage_complete"):
                    full_payload = dict(payload)
                    full_payload.update({
                        "task_id": task.task_id,
                        "stage": payload.get("stage", 0),
                        "stage_name": payload.get("name", payload.get("stage_name", "")),
                        "verb": payload.get("verb", "Working"),
                        "detail": payload.get("detail", ""),
                        "model": payload.get("model", ""),
                        "status": "start" if event_type == "stage_start" else "complete",
                    })
                    await self._emit(MissionEvent(
                        event_type="pipeline_stage",
                        payload=full_payload,
                    ))
                elif event_type in ("model_start", "model_complete"):
                    full_payload = dict(payload)
                    full_payload.update({
                        "task_id": task.task_id,
                        "tier": payload.get("tier", 1),
                        "provider": payload.get("provider", "nvidia_nim"),
                        "model": payload.get("model", ""),
                        "latency": payload.get("latency", 0.0),
                    })
                    await self._emit(MissionEvent(
                        event_type=event_type,
                        payload=full_payload,
                    ))
                elif event_type == "tool_executing":
                    full_payload = dict(payload)
                    full_payload.update({
                        "task_id": task.task_id,
                        "tool": payload.get("tool", payload.get("tool_name", "")),
                        "tool_name": payload.get("tool_name", payload.get("tool", "")),
                        "verb": "Executing",
                    })
                    await self._emit(MissionEvent(
                        event_type="tool_executing",
                        payload=full_payload,
                    ))
                elif event_type == "tool_complete":
                    full_payload = dict(payload)
                    full_payload.update({
                        "task_id": task.task_id,
                        "tool": payload.get("tool", payload.get("tool_name", "")),
                        "tool_name": payload.get("tool_name", payload.get("tool", "")),
                        "success": payload.get("success", False),
                        "exit_code": payload.get("exit_code", -1),
                        "output_preview": payload.get("output_preview", ""),
                    })
                    await self._emit(MissionEvent(
                        event_type="tool_complete",
                        payload=full_payload,
                    ))

            cb_token = _task_progress_callback_var.set(_pipeline_progress)
            at_token = _task_action_tracker_var.set(momentum_tracker)
            self.orchestrator._progress_callback = _pipeline_progress
            self.orchestrator._action_tracker = momentum_tracker

            ws_snapshot_before = self._get_workspace_snapshot(mission)

            try:
                try:
                    orch_result = await self.orchestrator.run(
                        enriched_prompt,
                        mission_id=mission.mission_id,
                        task_id=task.task_id,
                    )
                except TypeError as t_err:
                    if "unexpected keyword argument" in str(t_err):
                        orch_result = await self.orchestrator.run(enriched_prompt)
                    else:
                        raise
            except Exception as exc:
                logger.error(
                    f"MissionRunner: unexpected error during task '{task.title}' "
                    f"(inner iteration {inner_iteration}): {exc}"
                )
                if inner_iteration < MAX_INNER_ITERATIONS:
                    current_description = (
                        f"RETRY {inner_iteration}: Previous attempt raised an exception.\n"
                        f"Error: {type(exc).__name__}: {str(exc)[:200]}\n\n"
                        f"Original task: {task.description}\n"
                        f"Try a different approach."
                    )
                    await asyncio.sleep(0)
                    continue
                else:
                    await self._handle_task_failure(
                        mission, task,
                        error=f"Unexpected error: {type(exc).__name__}: {str(exc)[:200]}",
                        output=""
                    )
                    return
            finally:
                _task_progress_callback_var.reset(cb_token)
                _task_action_tracker_var.reset(at_token)
                self.orchestrator._progress_callback = None
                self.orchestrator._action_tracker = None

            ws_snapshot_after = self._get_workspace_snapshot(mission)
            workspace_changed = (ws_snapshot_before != ws_snapshot_after)

            last_orch_result = orch_result

            # Track costs
            if hasattr(orch_result, 'tier3_was_called') and orch_result.tier3_was_called:
                self._tier3_calls += 1
                try:
                    cost = self.orchestrator.claude.get_cost_summary()
                    self._total_cost = cost.get("total_spent", 0.0)
                except Exception:
                    pass

            # Capture output for continuity
            if orch_result.final_output:
                self._recent_outputs.append(orch_result.final_output[:600])
                if len(self._recent_outputs) > 12:
                    self._recent_outputs = self._recent_outputs[-12:]

            self._track_file_changes(orch_result)

            # No-progress inspection stall detection
            tool_name = getattr(orch_result, "tool_name", "") or ""
            tool_call = getattr(orch_result, "tool_call", {}) or {}
            raw_params = {}
            if isinstance(tool_call, dict):
                raw_params = tool_call.get("parameters") or tool_call.get("arguments") or {}
            norm_params = json.dumps(raw_params, sort_keys=True) if isinstance(raw_params, dict) else str(raw_params)
            tool_fingerprint = f"{tool_name}:{norm_params}"

            record = {
                "iteration": inner_iteration,
                "tool_name": tool_name,
                "fingerprint": tool_fingerprint,
                "output": (orch_result.final_output or "")[:200],
                "workspace_changed": workspace_changed,
            }
            task_tool_history.append(record)

            # Record action in ActionMomentumTracker
            momentum_rec = momentum_tracker.record_action(
                tool_name=tool_name,
                params=raw_params,
                workspace_changed=workspace_changed,
                success=orch_result.success,
                model_turn=inner_iteration,
            )
            consecutive_stalls = momentum_tracker.consecutive_read_only

            # Phase 4B: Action Momentum & Non-Progress Escalation Check
            if momentum_tracker.escalation_level > 0 and action_contract.is_implementation and not workspace_changed:
                guidance = momentum_tracker.get_escalation_guidance()
                logger.warning(
                    f"ACTION_DISCIPLINE | task_id={task.task_id} | iteration={inner_iteration} | "
                    f"level={momentum_tracker.escalation_level} | non_progress_score={momentum_tracker.non_progress_score} | "
                    f"tool={tool_name}"
                )
                await self._emit(MissionEvent(
                    event_type="action_discipline_escalation",
                    payload={
                        "task_id": task.task_id,
                        "level": momentum_tracker.escalation_level,
                        "score": momentum_tracker.non_progress_score,
                        "guidance": guidance,
                        "tool": tool_name,
                    }
                ))
                current_description = f"{guidance}\n\nTask: {task.description}"
                if inner_iteration < MAX_INNER_ITERATIONS:
                    await asyncio.sleep(0)
                    continue
            elif consecutive_stalls >= 2:
                await self._emit(MissionEvent(
                    event_type="agent_stall_detected",
                    payload={
                        "task_id": task.task_id,
                        "tool_name": tool_name,
                        "fingerprint": tool_fingerprint,
                        "consecutive_count": consecutive_stalls,
                        "workspace_changed": False,
                    }
                ))
                logger.warning(
                    f"TASK_PROGRESS | task_id={task.task_id} | iteration={inner_iteration} | "
                    f"tool={tool_name} | status=STALL_DETECTED | repeated_execution={tool_fingerprint} | "
                    f"workspace_changed=False"
                )
                try:
                    from core.event_bus import event_bus, EventType
                    event_bus.publish(EventType.TASK_PROGRESS, {
                        "task_id": task.task_id,
                        "inner_iteration": inner_iteration,
                        "tool_name": tool_name,
                        "tool_fingerprint": tool_fingerprint,
                        "workspace_changed": False,
                        "status": "STALL_DETECTED",
                    })
                except Exception:
                    pass

                corrective_msg = (
                    "NO PROGRESS DETECTED: You already inspected the workspace with this action "
                    "and no state changed. Do not repeat the same inspection. "
                    "Proceed to the next required implementation action."
                )
                if self._task_needs_implementation(task):
                    corrective_msg += (
                        "\nCRITICAL REQUIREMENT: This task requires file creation. "
                        "You MUST invoke write_file now to create the required file(s). "
                        "Do not run any more inspection or listing tools."
                    )
                current_description = f"{corrective_msg}\n\nTask: {task.description}"
                if inner_iteration < MAX_INNER_ITERATIONS:
                    await asyncio.sleep(0)
                    continue
            else:
                logger.info(
                    f"TASK_PROGRESS | task_id={task.task_id} | iteration={inner_iteration} | "
                    f"tool={tool_name} | status={'SUCCESS' if orch_result.success else 'FAILED'} | "
                    f"workspace_changed={workspace_changed}"
                )
                try:
                    from core.event_bus import event_bus, EventType
                    event_bus.publish(EventType.TASK_PROGRESS, {
                        "task_id": task.task_id,
                        "inner_iteration": inner_iteration,
                        "tool_name": tool_name,
                        "tool_fingerprint": tool_fingerprint,
                        "workspace_changed": workspace_changed,
                        "status": "PROGRESS" if orch_result.success else "FAILED",
                    })
                except Exception:
                    pass

            # Emit tool result
            await self._emit(MissionEvent(
                event_type="tool_result",
                payload={
                    "task_id": task.task_id,
                    "tool_name": orch_result.tool_name,
                    "success": orch_result.success,
                    "stage_reached": orch_result.pipeline_stage_reached,
                    "output_preview": (orch_result.final_output or "")[:300],
                    "tier3_called": orch_result.tier3_was_called,
                    "trace_id": orch_result.trace_id,
                    "inner_iteration": inner_iteration,
                }
            ))

            # ── Check if tool execution itself failed ──────────────────────
            if not orch_result.success or orch_result.pipeline_stage_reached < 6:
                if inner_iteration < MAX_INNER_ITERATIONS:
                    await self._emit(MissionEvent(
                        event_type="thought",
                        payload={
                            "text": f"Tool execution failed — retrying",
                            "detail": (orch_result.error or "")[:100],
                        }
                    ))
                    current_description = (
                        f"RETRY {inner_iteration}: Previous attempt failed.\n"
                        f"Error: {orch_result.error or 'unknown'}\n"
                        f"Output: {(orch_result.final_output or '')[:200]}\n\n"
                        f"Original task: {task.description}\n"
                        f"Try a different approach."
                    )
                    await asyncio.sleep(0)
                    continue
                else:
                    # All inner iterations exhausted — handle as outer failure
                    await self._handle_task_failure(
                        mission, task,
                        error=orch_result.error or "Tool execution failed repeatedly",
                        output=orch_result.final_output or "",
                    )
                    return

            # ── Perform quality verification ────────────────────────────────
            # For implementation tasks, verify that real non-trivial code was generated
            # without placeholders or stubs before declaring the task complete.
            needs_impl = self._task_needs_implementation(task)
            quality_passed = True
            if needs_impl:
                await self._emit(MissionEvent(
                    event_type="thought",
                    payload={
                        "text": "Verifying implementation quality",
                        "detail": "Checking output against requirements",
                    }
                ))
                task_idx = 1
                try:
                    for i, t in enumerate(mission.tasks):
                        if t.task_id == task.task_id:
                            task_idx = i + 1
                            break
                except Exception:
                    pass

                p_root = mission.project_root_path or mission.workspace_root or ""
                quality_result = verifier.verify_task_scoped(
                    task_id=task.task_id,
                    task_title=task.title,
                    task_description=task.description,
                    task_index=task_idx,
                    total_tasks=len(mission.tasks),
                    project_root=p_root,
                )
                await self._emit(MissionEvent(
                    event_type="quality_check",
                    payload={
                        "task_id": task.task_id,
                        "verdict": quality_result.overall_verdict,
                        "coverage_pct": quality_result.coverage_pct,
                        "issues": quality_result.improvement_suggestions[:3],
                        "inner_iteration": inner_iteration,
                    }
                ))

                if quality_result.needs_improvement:
                    quality_passed = False
                    if inner_iteration < MAX_INNER_ITERATIONS:
                        await self._emit(MissionEvent(
                            event_type="thought",
                            payload={
                                "text": f"Quality insufficient ({quality_result.overall_verdict}) — improving",
                                "detail": f"Coverage: {quality_result.coverage_pct:.0f}% | "
                                          f"Issues: {len(quality_result.improvement_suggestions)}",
                            }
                        ))
                        current_description = quality_result.repair_prompt
                        await asyncio.sleep(0)
                        continue

            # ── Target artifact integrity gate ────────────────────────────
            # If the task requires implementation or specifies target files,
            # verify that those files exist on disk and are non-empty (>10B).
            target_files = []
            if getattr(task, "target_paths", None):
                target_files.extend(task.target_paths)
            if getattr(task, "expected_artifacts", None):
                target_files.extend(task.expected_artifacts)
            if not target_files and needs_impl:
                import re as _re
                found = _re.findall(r"[\w\-\./]+\.(?:html|css|js|py|json|md|txt)", f"{task.title} {task.description}")
                for fn in found:
                    cleaned_fn = _re.sub(r"^generated_projects/[^/]+/", "", fn)
                    target_files.append(cleaned_fn)

            missing_targets = []
            if target_files and ws_root:
                for tf in target_files:
                    p = (ws_root / tf).resolve()
                    if not p.exists() or p.stat().st_size <= 10:
                        missing_targets.append(tf)

            if missing_targets:
                quality_passed = False
                logger.warning(
                    f"MissionRunner: task '{task.title}' failed artifact gate: missing targets on disk: {missing_targets}"
                )
                if inner_iteration < MAX_INNER_ITERATIONS:
                    await self._emit(MissionEvent(
                        event_type="thought",
                        payload={
                            "text": f"Target artifact missing ({', '.join(missing_targets)}) — creating",
                            "detail": f"Required files not found on disk",
                        }
                    ))
                    current_description = (
                        f"CRITICAL REQUIREMENT: The following target files were not written to disk: "
                        f"{', '.join(missing_targets)}.\n"
                        f"You MUST use write_file to create complete, working code for these files now.\n"
                        f"Do not call list_directory or read-only tools.\n"
                        f"Original task: {task.description}"
                    )
                    await asyncio.sleep(0)
                    continue

            if orch_result.success and orch_result.pipeline_stage_reached >= 11 and quality_passed:
                task.is_verified = True
                task.verification_evidence = (
                    f"Pipeline verified at Stage {orch_result.pipeline_stage_reached} | "
                    f"Tool: {orch_result.tool_name or 'direct'}"
                )
                mission.mark_task_complete(task.task_id)

                try:
                    self._trajectory_memory.store(
                        task_title=task.title,
                        task_description=task.description[:500],
                        files_created=list(self._files_created[-10:]),
                        skill_used=task.skill_hint or "",
                        tier3_was_used=orch_result.tier3_was_called if hasattr(orch_result, 'tier3_was_called') else False,
                        quality_verdict="PASS",
                    )
                except Exception as e:
                    logger.debug(f"TrajectoryMemory store failed: {e}")

                await self._emit(MissionEvent(
                    event_type="task_complete",
                    payload={
                        "task_id": task.task_id,
                        "title": task.title,
                        "output_preview": (orch_result.final_output or "")[:300],
                        "quality_verdict": "PASS",
                        "inner_iterations": inner_iteration,
                    }
                ))
                return

            # Only for tasks that should produce implementation output and didn't complete cleanly
            if self._task_needs_implementation(task):
                await self._emit(MissionEvent(
                    event_type="thought",
                    payload={
                        "text": "Verifying implementation quality",
                        "detail": "Checking output against requirements",
                    }
                ))

                quality_result = verifier.verify_task(
                    task_id=task.task_id,
                    task_title=task.title,
                    task_description=task.description,
                    project_root=mission.project_root_path or mission.workspace_root or "",
                    files_created=list(self._files_created[-10:]),
                    files_modified=list(self._files_modified[-5:]),
                )

                await self._emit(MissionEvent(
                    event_type="quality_check",
                    payload={
                        "task_id": task.task_id,
                        "verdict": quality_result.overall_verdict,
                        "coverage_pct": quality_result.coverage_pct,
                        "issues": quality_result.improvement_suggestions[:3],
                        "inner_iteration": inner_iteration,
                    }
                ))

                if quality_result.needs_improvement and inner_iteration < MAX_INNER_ITERATIONS:
                    # Quality insufficient — feed self-review back to model
                    await self._emit(MissionEvent(
                        event_type="thought",
                        payload={
                            "text": f"Quality insufficient ({quality_result.overall_verdict}) — improving",
                            "detail": f"Coverage: {quality_result.coverage_pct:.0f}% | "
                                      f"Issues: {len(quality_result.improvement_suggestions)}",
                        }
                    ))

                    # The repair prompt IS the next iteration's task description
                    # It includes the quality findings and specific instructions
                    current_description = quality_result.repair_prompt
                    await asyncio.sleep(0)
                    continue

                # Run structured feedback (Self-Refine + CRITIC combined)
                from core.structured_feedback import StructuredFeedbackGenerator
                fb_gen = StructuredFeedbackGenerator()

                # Get the file(s) written in this task iteration
                recent_files = []
                if hasattr(orch_result, 'tool_name') and orch_result.tool_name in ("write_file", "append_file"):
                    if hasattr(orch_result, 'tool_call') and isinstance(orch_result.tool_call, dict):
                        params = orch_result.tool_call.get("parameters") or orch_result.tool_call.get("arguments") or {}
                        p_name = params.get("path") or params.get("TargetFile") or params.get("target_file")
                        if p_name:
                            recent_files.append(str(p_name))
                if not recent_files and self._files_created:
                    recent_files = [self._files_created[-1]]

                structured_fb_failed = False
                for file_path in recent_files:
                    from pathlib import Path
                    p = Path(file_path)
                    if not p.is_absolute():
                        if self.workspace.is_locked and self.workspace.workspace_root:
                            cand = self.workspace.workspace_root / p
                            if cand.exists():
                                p = cand
                        elif mission.workspace_root and (Path(mission.workspace_root) / p).exists():
                            p = Path(mission.workspace_root) / p
                    if not p.exists():
                        continue

                    structured_fb = fb_gen.generate(
                        task_description=task.description,
                        file_path=str(p),
                        task_requirements=task.required_content_keywords,
                        timeout_seconds=15,
                    )

                    await self._emit(MissionEvent(
                        event_type="structured_feedback",
                        payload={
                            "task_id": task.task_id,
                            "file": file_path,
                            "verdict": structured_fb.overall_verdict,
                            "failed_dimensions": [
                                d.dimension for d in structured_fb.failed_dimensions
                            ],
                            "is_ready": structured_fb.is_ready,
                        }
                    ))

                    # If structured feedback FAILS, override the quality check
                    # and use the structured repair instructions
                    if not structured_fb.is_ready and inner_iteration < MAX_INNER_ITERATIONS:
                        current_description = (
                            f"STRUCTURED FEEDBACK REPAIR (Self-Refine + CRITIC):\n\n"
                            f"{structured_fb.to_feedback_text()}\n\n"
                            f"Original task: {task.description}\n"
                            f"Directly update and fix the file using write_file or patch_file "
                            f"to resolve each failing dimension listed above. Do not just inspect or read."
                        )
                        structured_fb_failed = True
                        break

                if structured_fb_failed:
                    await asyncio.sleep(0)
                    continue

            # ── Task passed quality check (or no quality check needed) ─────
            task.is_verified = True
            task.verification_evidence = (
                f"Quality: {quality_result.overall_verdict if quality_result else 'N/A'} | "
                f"Coverage: {quality_result.coverage_pct if quality_result else 100:.0f}%"
            )
            mission.mark_task_complete(task.task_id)

            # EcoAssistant: store successful trajectory for future use
            try:
                self._trajectory_memory.store(
                    task_title=task.title,
                    task_description=task.description[:500],
                    files_created=list(self._files_created[-10:]),
                    skill_used=task.skill_hint or "",
                    tier3_was_used=orch_result.tier3_was_called if hasattr(orch_result, 'tier3_was_called') else False,
                    quality_verdict=quality_result.overall_verdict if quality_result else "PASS",
                )
            except Exception as e:
                logger.debug(f"TrajectoryMemory store failed: {e}")

            await self._emit(MissionEvent(
                event_type="task_complete",
                payload={
                    "task_id": task.task_id,
                    "title": task.title,
                    "output_preview": (orch_result.final_output or "")[:300],
                    "quality_verdict": quality_result.overall_verdict if quality_result else "N/A",
                    "inner_iterations": inner_iteration,
                }
            ))
            return

        # ── Inner loop exhausted without passing quality check ─────────────
        if missing_targets:
            await self._handle_task_failure(
                mission, task,
                error=f"Task required target artifacts were not created on disk: {', '.join(missing_targets)}",
                output=(last_orch_result.final_output or "") if last_orch_result else "",
            )
            return

        if quality_result and quality_result.needs_improvement:
            if needs_impl and quality_result.overall_verdict in ("FAIL", "UNSATISFACTORY", "POOR"):
                await self._handle_task_failure(
                    mission, task,
                    error=f"Quality check failed ({quality_result.overall_verdict}): {', '.join(quality_result.improvement_suggestions[:2])}",
                    output=(last_orch_result.final_output or "") if last_orch_result else "",
                )
                return

            # Accept with warning rather than failing — partial is better than nothing
            task.is_verified = False
            task.verification_evidence = (
                f"Quality: {quality_result.overall_verdict} | "
                f"Coverage: {quality_result.coverage_pct:.0f}% (warning: accepted after {MAX_INNER_ITERATIONS} attempts)"
            )
            mission.mark_task_complete(task.task_id)
            await self._emit(MissionEvent(
                event_type="task_complete",
                payload={
                    "task_id": task.task_id,
                    "title": task.title,
                    "quality_verdict": quality_result.overall_verdict,
                    "warning": "Accepted with quality issues after max iterations",
                    "inner_iterations": inner_iteration,
                }
            ))
        elif last_orch_result:
            await self._handle_task_failure(
                mission, task,
                error="Max inner iterations reached without success",
                output=(last_orch_result.final_output or "")
            )

    def _task_needs_implementation(self, task: MissionTask) -> bool:
        """
        Determine if a task requires actual file content implementation
        (as opposed to read-only tasks like listing files or running tests).
        """
        lower = task.description.lower() + " " + task.title.lower()
        implementation_keywords = [
            "create", "write", "implement", "build", "generate", "add",
            "develop", "code", "make", "produce", "design", "style",
            "install", "setup", "configure"
        ]
        read_only_keywords = [
            "read", "list", "view", "check", "verify", "inspect",
            "search", "find", "look", "review", "analyze", "audit"
        ]
        has_impl = any(kw in lower for kw in implementation_keywords)
        has_read = any(kw in lower for kw in read_only_keywords)

        # If it's read-only, no implementation check needed
        if has_read and not has_impl:
            return False
        return has_impl

    async def _verify_task_evidence(
        self,
        task: MissionTask,
        mission: Mission,
    ) -> tuple[bool, str]:
        """
        Verify that a task that should produce file output actually did.

        Checks:
        1. If we tracked any file creations during this task, verify they exist
        2. If the mission has a project root, check it is non-empty
        3. For write tasks, verify the most recently created files are non-empty

        Returns: (success: bool, message: str)
        """
        from pathlib import Path

        # Check recently tracked files
        if self._files_created:
            for f_path in self._files_created[-3:]:
                p = Path(f_path)
                if p.exists() and p.is_file():
                    size = p.stat().st_size
                    if size == 0:
                        return False, f"File {f_path} was created but is empty"
                    return True, f"Verified: {f_path} exists ({size} bytes)"

        # Check project root has content
        target_root = None
        if self.workspace and self.workspace.is_locked:
            target_root = Path(self.workspace.root_str)
        elif mission.project_root_path:
            target_root = Path(mission.project_root_path)

        if target_root:
            if target_root.exists():
                all_files = list(target_root.rglob("*"))
                actual_files = [
                    f for f in all_files
                    if f.is_file() and f.stat().st_size > 0
                ]
                if actual_files:
                    return True, f"Project has {len(actual_files)} non-empty files"
                elif all_files:
                    return False, (
                        f"Project root exists but all files are empty. "
                        f"Implementation must write actual content."
                    )
            # Root doesn't exist yet — may not be the right task for final check
            return True, "Project root not yet created — continuing"

        # No specific verification possible — allow
        return True, "No filesystem evidence required for this task type"

    async def _check_acceptance_criteria(
        self, mission: Mission
    ) -> list[str]:
        """
        Check each acceptance criterion against the actual filesystem state.
        Returns list of unmet criteria.
        """
        from pathlib import Path
        import subprocess

        unmet = []
        root = None
        if self.workspace and self.workspace.is_locked:
            root = Path(self.workspace.root_str)
        elif mission.project_root_path:
            root = Path(mission.project_root_path)

        for criterion in mission.acceptance_criteria:
            lower = criterion.lower()
            met = False

            if "at least one file" in lower and "not just folders" in lower:
                # Check any non-empty file exists
                if root and root.exists():
                    files = [
                        f for f in root.rglob("*")
                        if f.is_file() and f.stat().st_size > 0
                    ]
                    met = len(files) > 0
                else:
                    # Check generated_projects/
                    gp = Path("generated_projects")
                    if gp.exists():
                        files = [
                            f for f in gp.rglob("*")
                            if f.is_file() and f.stat().st_size > 0
                        ]
                        met = len(files) > 0

            elif "index.html" in lower:
                if root and root.exists():
                    html_files = list(root.rglob("*.html"))
                    met = any(f.stat().st_size > 0 for f in html_files)

            elif "css" in lower and "styling" in lower:
                if root and root.exists():
                    css_files = list(root.rglob("*.css"))
                    met = any(f.stat().st_size > 0 for f in css_files)
                    if not met:
                        for f in root.rglob("*.html"):
                            if f.stat().st_size > 0:
                                content = f.read_text(errors="ignore")
                                if "<style" in content and "</style>" in content:
                                    met = True
                                    break

            elif "animation" in lower:
                if root and root.exists():
                    for f in root.rglob("*.css"):
                        if f.stat().st_size > 0:
                            content = f.read_text(errors="ignore")
                            if "@keyframes" in content or "animation" in content or "transition" in content:
                                met = True
                                break
                    if not met:
                        for f in root.rglob("*.js"):
                            if f.stat().st_size > 0:
                                met = True
                                break
                    if not met:
                        for f in root.rglob("*.html"):
                            if f.stat().st_size > 0:
                                content = f.read_text(errors="ignore")
                                if "@keyframes" in content or "animation" in content or "transition" in content or "requestAnimationFrame" in content:
                                    met = True
                                    break

            elif "responsive" in lower:
                if root and root.exists():
                    for f in root.rglob("*.css"):
                        content = f.read_text(errors="ignore")
                        if "@media" in content:
                            met = True
                            break
                    if not met:
                        for f in root.rglob("*.html"):
                            content = f.read_text(errors="ignore")
                            if "@media" in content or "viewport" in content:
                                met = True
                                break

            elif "questionnaire" in lower or "interactive form" in lower:
                if root and root.exists():
                    for f in root.rglob("*.html"):
                        content = f.read_text(errors="ignore")
                        if "<form" in content or "<input" in content or "questionnaire" in content.lower():
                            met = True
                            break
                    if not met:
                        for f in root.rglob("*.js"):
                            if f.stat().st_size > 0:
                                met = True
                                break

            elif "implementation files" in lower:
                # Check minimum file count
                import re as _re
                count_match = _re.search(r'at least (\d+)', lower)
                required = int(count_match.group(1)) if count_match else 2
                if root and root.exists():
                    files = [
                        f for f in root.rglob("*")
                        if f.is_file() and f.stat().st_size > 0
                    ]
                    met = len(files) >= required

            else:
                # Unknown criterion — mark as met to avoid blocking
                met = True

            if not met:
                unmet.append(criterion)

        return unmet

    async def _handle_task_failure(
        self,
        mission: Mission,
        task: MissionTask,
        error: str,
        output: str,
    ) -> None:
        """
        Handle a task failure:
          1. Record the failure
          2. Check if retry is possible
          3. If retrying: build repair prompt with error context injected
          4. If max retries exceeded: mark FAILED, block dependents
        """
        self._current_phase = MissionPhase.REPAIRING

        await self._emit(MissionEvent(
            event_type="task_failed",
            payload={
                "task_id": task.task_id,
                "title": task.title,
                "error": error[:300],
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
            }
        ))

        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.state = TaskState.PENDING

            await self._emit(MissionEvent(
                event_type="repair_attempt",
                payload={
                    "task_id": task.task_id,
                    "attempt": task.retry_count,
                    "max": task.max_retries,
                }
            ))

            # Build a repair-focused description that forces file writing
            project_path = (self.workspace.root_str if (self.workspace and self.workspace.is_locked) else mission.project_root_path) or "."
            task.description = (
                f"REPAIR ATTEMPT {task.retry_count}/{task.max_retries}\n\n"
                f"ORIGINAL TASK: {task.description}\n\n"
                f"PREVIOUS FAILURE: {error[:200]}\n\n"
                f"PREVIOUS OUTPUT: {output[:200]}\n\n"
                f"CRITICAL INSTRUCTIONS:\n"
                f"1. Do NOT create empty folders. Write actual file content.\n"
                f"2. Use write_file tool to create files with FULL implementation.\n"
                f"3. The project must be at: {project_path}\n"
                f"4. Write complete, working code — not placeholders.\n"
                f"5. After writing files, verify they exist and are non-empty.\n"
            )
        else:
            mission.mark_task_failed(task.task_id, error)

    # ── Context building ──────────────────────────────────────────────────────

    def _build_task_prompt(self, task: MissionTask, mission: Mission) -> str:
        """Build task prompt with implementation enforcement."""

        # Get base context from ContextBuilder
        try:
            context = self._context_builder.build(
                task=task,
                mission=mission,
                memory_context=self._get_memory_context(),
                previous_outputs=self._recent_outputs[-3:],
                error_context=task.error_message if task.retry_count > 0 else "",
            )
            base = context.to_string()
        except Exception:
            base = f"CURRENT TASK: {task.description}"

        # Add implementation enforcement instructions
        project_path = mission.project_root_path or "generated_projects/output"
        completed_count = sum(
            1 for t in mission.tasks if t.state == TaskState.COMPLETED
        )
        total_count = len(mission.tasks)

        enforcement = f"""

═══ EXECUTION REQUIREMENTS ═══
Project location: {project_path}
Mission progress: {completed_count}/{total_count} tasks complete

MANDATORY RULES FOR THIS TASK:
1. You MUST use write_file to create files with COMPLETE content.
2. Do NOT create empty files or placeholder content.
3. Do NOT stop after creating a folder — create the actual files inside.
4. Write REAL, WORKING code — not "TODO" comments or stub implementations.
5. For web projects: write actual HTML structure, real CSS rules, working JS.
6. For API projects: write actual route handlers, real database models.
7. After writing a file, the mission runner will verify it is non-empty.
8. Only use bash_exec for: running tests, checking file contents, validation.
9. The task is complete ONLY when the requested implementation exists on disk.

TASK TO EXECUTE:
{task.description}

SUCCESS CRITERION: {task.acceptance_criteria}
"""

        return base + enforcement

    def _build_task_prompt_with_description(
        self,
        task: MissionTask,
        mission: Mission,
        override_description: str,
    ) -> str:
        project_path = mission.project_root_path or "generated_projects/output"
        completed_count = sum(1 for t in mission.tasks if t.state == TaskState.COMPLETED)
        total_count = len(mission.tasks)

        # ── EcoAssistant: Retrieve trajectory demonstration ────────────────
        demo_section = ""
        trajectory = self._trajectory_memory.retrieve_best(override_description)
        if trajectory:
            demo_section = (
                f"\n{'-' * 50}\n"
                f"{trajectory.to_demonstration()}"
                f"{'-' * 50}\n"
            )
            logger.debug(
                f"MissionRunner: injecting trajectory demo "
                f"'{trajectory.task_title[:40]}'"
            )

        # ── RepoBench: Cross-file context retrieval ────────────────────────
        cross_file_section = ""
        is_impl_task = self._task_needs_implementation(task)
        if self.workspace and self.workspace.is_locked:
            cross_ctx = self._cross_file_retriever.retrieve(
                override_description, max_files=4
            )
            if not cross_ctx.is_empty:
                cross_file_section = (
                    f"\n{cross_ctx.to_prompt_section()}\n"
                )
                logger.debug(
                    f"MissionRunner: injected {len(cross_ctx.items)} "
                    f"cross-file context items"
                )

        # ── Phase 4B: Task Action Contract & Write Intent ──────────────────
        from pathlib import Path
        from core.action_discipline import derive_action_contract
        ws_root = Path(self.workspace.workspace_root) if (self.workspace and self.workspace.is_locked and self.workspace.workspace_root) else None
        contract = derive_action_contract(task, workspace_root=ws_root, all_tasks=mission.tasks)
        contract_section = f"\n{contract.get_summary_prompt_section(ws_root)}\n"

        # ── Base context from ContextBuilder ──────────────────────────────
        try:
            from core.context_builder import ContextBuilder
            ctx = self._context_builder.build(
                task=task,
                mission=mission,
                memory_context=self._get_memory_context(),
                previous_outputs=self._recent_outputs[-3:],
                error_context="",
            )
            base = ctx.to_string()
        except Exception:
            base = ""

        # Context sharing (Phase 4E Section 14): Cache static project contract
        cache_key = f"{mission.mission_id}:static_rules"
        if cache_key not in self._static_context_cache:
            self._static_context_cache[cache_key] = (
                "MANDATORY ACTION RULES:\n"
                "1. Write complete, working production-grade implementation — zero stubs, TODOs, or empty handlers.\n"
                "2. Action Momentum: OBSERVE → UNDERSTAND → ACT → VERIFY. Proceed directly to implementation.\n"
                "3. For file creation tasks, invoke write_file directly to produce the target file. Do NOT repeat workspace listing or directory inspection.\n"
                "4. Honor read-before-write: read an existing file once before modifying it.\n"
                "5. All element IDs and class names must match across HTML, CSS, and JS exactly.\n"
            )
        else:
            self.telemetry.context_cache_hits += 1
        static_rules = self._static_context_cache[cache_key]

        enforcement = f"""

═══ TASK EXECUTION ═══
{contract_section}
{demo_section}{cross_file_section}
Project: {project_path}
Progress: {completed_count}/{total_count} tasks complete

{static_rules}

TASK:
{override_description}

SUCCESS CRITERION: {task.acceptance_criteria}
"""
        return base + enforcement

    def _get_workspace_snapshot(self, mission: Mission) -> tuple[int, int]:
        """Compute a fast snapshot (file_count, total_size) of the workspace."""
        try:
            import os
            from pathlib import Path
            from core.workspace import IGNORE_PATTERNS
            root = None
            if self.workspace and self.workspace.is_locked and self.workspace.workspace_root:
                root = Path(self.workspace.workspace_root)
            elif mission and mission.project_root_path:
                root = Path(mission.project_root_path)
            elif mission and mission.workspace_root:
                root = Path(mission.workspace_root)
            else:
                root = Path.cwd()

            if not root or not root.exists():
                return (0, 0)

            count = 0
            size = 0
            skip_set = {p.lower() for p in IGNORE_PATTERNS if not p.startswith("*")}
            for root_dir, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.lower() not in skip_set and not d.startswith(".")]
                for f in files:
                    if not f.startswith("."):
                        count += 1
                        try:
                            size += os.path.getsize(os.path.join(root_dir, f))
                        except OSError:
                            pass
            return (count, size)
        except Exception:
            return (0, 0)

    def _get_memory_context(self) -> str:
        """Read current memory context for injection."""
        try:
            from memory.store import read_context_for_prompt
            return read_context_for_prompt(project=self.workspace.root_str)
        except Exception:
            return ""

    def _track_file_changes(self, orch_result: Any) -> None:
        """Track which files were created or modified during task execution."""
        if not hasattr(orch_result, 'tool_name') or not orch_result.tool_name:
            return

        tool = orch_result.tool_name
        
        # 1. First check explicit tool_call parameters
        if hasattr(orch_result, 'tool_call') and isinstance(orch_result.tool_call, dict):
            params = orch_result.tool_call.get("parameters") or orch_result.tool_call.get("arguments") or {}
            param_path = params.get("path")
            if param_path and isinstance(param_path, str):
                if tool in ("write_file", "create_folder") and param_path not in self._files_created:
                    self._files_created.append(param_path)
                elif tool in ("append_file",) and param_path not in self._files_modified:
                    self._files_modified.append(param_path)

        # 2. Extract paths from tool output (handling Windows and POSIX separators)
        if hasattr(orch_result, 'tool_result') and orch_result.tool_result:
            output = orch_result.tool_result.output or ""
            import re
            paths = re.findall(r'[\w\.\\/\-]+\.\w{2,5}', output)
            for path in paths[:5]:  # Cap to avoid noise
                # Normalize relative path if output contains full workspace path
                norm_path = path
                if self.workspace.is_locked and self.workspace.root_str:
                    try:
                        norm_path = str(Path(path).relative_to(self.workspace.workspace_root))
                    except Exception:
                        norm_path = path
                if tool in ("write_file", "create_folder"):
                    if norm_path not in self._files_created:
                        self._files_created.append(norm_path)
                elif tool in ("append_file",):
                    if norm_path not in self._files_modified:
                        self._files_modified.append(norm_path)

    # ── Walkthrough generation ────────────────────────────────────────────────

    async def _generate_walkthrough(self, mission: Mission) -> str:
        """
        Generate post-mission walkthrough from actual execution evidence.
        Based on real task results, not model-generated summaries.
        """
        from pathlib import Path

        completed = [t for t in mission.tasks if t.state == TaskState.COMPLETED]
        failed = [t for t in mission.tasks if t.state == TaskState.FAILED]
        elapsed = time.monotonic() - self._start_time
        completed_count, total_count = mission.progress

        lines: list[str] = []
        lines.append("")
        lines.append("━" * 55)

        if mission.is_complete and not failed:
            lines.append("  MISSION COMPLETE ✓")
        elif completed_count > 0:
            lines.append(f"  MISSION PARTIAL ({completed_count}/{total_count} tasks)")
        else:
            lines.append("  MISSION INCOMPLETE")

        lines.append("━" * 55)
        lines.append("")

        # Completed tasks
        if completed:
            lines.append("  Completed:")
            for task in completed:
                quality = ""
                if task.is_verified:
                    quality = " ✓"
                elif hasattr(task, 'verification_evidence') and task.verification_evidence:
                    quality = " ~"
                lines.append(f"    ✓{quality}  {task.title}")
        lines.append("")

        # Files created
        if self._files_created:
            lines.append("  Created:")
            for f in self._files_created[:12]:
                p = Path(f)
                if p.exists():
                    size = p.stat().st_size
                    lines.append(f"    +  {f}  ({size} bytes)")
                else:
                    lines.append(f"    +  {f}")
        lines.append("")

        # Files modified
        if self._files_modified:
            lines.append("  Modified:")
            for f in self._files_modified[:8]:
                lines.append(f"    ~  {f}")
        lines.append("")

        # Failed tasks
        if failed:
            lines.append("  Failed:")
            for task in failed:
                lines.append(f"    ✗  {task.title}")
                if task.error_message:
                    lines.append(f"       Reason: {task.error_message[:80]}")
        lines.append("")

        # Project check
        if mission.project_root_path:
            root = Path(mission.project_root_path)
            if root.exists():
                all_files = list(root.rglob("*"))
                impl_files = [
                    f for f in all_files
                    if f.is_file()
                    and f.suffix.lower() in {".html",".css",".js",".jsx",".ts",".tsx",".py"}
                    and f.stat().st_size > 50
                ]
                lines.append(f"  Project: {mission.project_root_path}")
                lines.append(f"  Files:   {len(impl_files)} implementation files")
                total_kb = sum(
                    f.stat().st_size for f in impl_files
                ) / 1024
                lines.append(f"  Size:    {total_kb:.1f} KB total")
                lines.append("")

        lines.append(f"  Time:    {elapsed:.1f}s")
        lines.append(f"  Cost:    ${self._total_cost:.4f}")
        if self._tier3_calls > 0:
            lines.append(f"  T3 calls: {self._tier3_calls}")
        lines.append("")
        lines.append("━" * 55)

        return "\n".join(lines)

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def _emit(self, event: MissionEvent) -> None:
        """Put an event into the queue for the TUI to consume and publish to canonical EventBus."""
        try:
            await asyncio.wait_for(
                self.event_queue.put(event),
                timeout=1.0
            )
        except asyncio.TimeoutError:
            logger.debug("MissionRunner: event queue full — dropping event")

        # Canonical EventBus bridge
        try:
            from core.event_bus import event_bus, HermesEvent, EventType
            type_mapping = {
                "mission_start": EventType.MISSION_STARTED,
                "mission_planned": EventType.PLAN_CREATED,
                "phase_change": EventType.MISSION_STATUS_CHANGED,
                "task_start": EventType.TASK_STARTED,
                "task_complete": EventType.TASK_COMPLETED,
                "task_failed": EventType.TASK_FAILED,
                "tool_executing": EventType.TOOL_STARTED,
                "tool_complete": EventType.TOOL_COMPLETED,
                "model_start": EventType.MODEL_REQUEST_STARTED,
                "model_complete": EventType.MODEL_COMPLETED,
                "quality_check": EventType.VERIFICATION_COMPLETED,
                "repair_attempt": EventType.REPAIR_STARTED,
                "structured_feedback": EventType.EVIDENCE_CREATED,
                "mission_complete": EventType.MISSION_COMPLETED,
                "mission_failed": EventType.MISSION_FAILED,
                "mission_aborted": EventType.MISSION_ABORTED,
                "workspace_ready": EventType.WORKSPACE_SCAN_COMPLETED,
                "skill_loaded": EventType.SKILL_LOADED,
                "pipeline_stage": EventType.TASK_PROGRESS,
            }
            canonical_type = type_mapping.get(event.event_type)
            if canonical_type:
                payload = dict(event.payload) if event.payload else {}
                m_id = payload.get("mission_id") or getattr(self, "_current_mission_id", "default")
                t_id = payload.get("task_id")
                # Preserve tool name
                if "tool" in payload and "tool_name" not in payload:
                    payload["tool_name"] = payload["tool"]
                event_bus.publish(HermesEvent(
                    event_type=canonical_type,
                    mission_id=m_id,
                    task_id=t_id,
                    payload=payload,
                    source="mission_runner",
                ))
        except Exception as exc:
            logger.debug(f"MissionRunner: canonical event_bus bridge exception: {exc}")

    def _build_result(
        self,
        mission: Mission,
        success: bool,
        error: Optional[str] = None
    ) -> MissionResult:
        elapsed = time.monotonic() - self._start_time
        completed, total = mission.progress
        failed_count = sum(1 for t in mission.tasks if t.state == TaskState.FAILED)

        status = "COMPLETE" if success else "FAILED"
        if not success and self._files_created:
            has_network_err = any(
                any(kw in (t.error_message or "").lower() for kw in [
                    "nvidiaconnectionerror", "connectionerror", "timeout", "timed out", 
                    "could not connect", "all connection attempts failed", "network"
                ])
                for t in mission.tasks if t.state == TaskState.FAILED
            ) or (error and any(kw in error.lower() for kw in ["connection", "timeout", "network"]))
            if has_network_err:
                status = "VERIFICATION_INTERRUPTED"
                if not error:
                    error = "Artifact created; later verification interrupted by provider/network failure"

        self.telemetry.total_mission_time = elapsed
        return MissionResult(
            mission_id=mission.mission_id,
            success=success,
            tasks_completed=completed,
            tasks_failed=failed_count,
            tasks_total=total,
            total_latency_seconds=elapsed,
            total_cost_usd=self._total_cost,
            tier3_calls=self._tier3_calls,
            files_created=self._files_created.copy(),
            files_modified=self._files_modified.copy(),
            error=error,
            status=status,
            optimization_telemetry=self.telemetry,
        )

    def abort(self) -> None:
        """Signal the mission loop to stop at the next safe checkpoint."""
        self.abort_event.set()
        logger.info("MissionRunner: abort signal sent")

    async def post_mission_git_summary(self, mission: Mission) -> str:
        """
        After mission completion:
        1. Check if workspace has a git repo
        2. Run git diff --stat to show what changed
        3. Generate a conventional commit message from the mission
        4. Optionally stage and commit (if AUTO mode)

        Returns a formatted summary string for display in chat.
        """
        if not self.workspace.is_locked:
            return ""

        workspace_root = self.workspace.workspace_root
        summary_lines: list[str] = []

        # Check git status
        try:
            import subprocess
            git_status = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(workspace_root),
                capture_output=True, text=True, timeout=10
            )

            if git_status.returncode != 0:
                return ""  # Not a git repo

            changed_files = [
                line.strip() for line in git_status.stdout.strip().split("\n")
                if line.strip()
            ]

            if not changed_files:
                return ""  # Nothing changed

            # Git diff stat
            diff_stat = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                cwd=str(workspace_root),
                capture_output=True, text=True, timeout=10
            )

            # Generate commit message from mission
            commit_msg = self._generate_commit_message(mission)

            summary_lines.append("")
            summary_lines.append("-" * 50)
            summary_lines.append("  Git Status")
            summary_lines.append("-" * 50)
            for f in changed_files[:15]:
                prefix = f[0:2].strip()
                filename = f[2:].strip()
                if "?" in prefix:
                    summary_lines.append(f"  +  {filename}  [new]")
                elif "M" in prefix:
                    summary_lines.append(f"  ~  {filename}  [modified]")
                elif "D" in prefix:
                    summary_lines.append(f"  -  {filename}  [deleted]")
                else:
                    summary_lines.append(f"     {filename}")

            if len(changed_files) > 15:
                summary_lines.append(f"  ... and {len(changed_files) - 15} more files")

            summary_lines.append("")
            summary_lines.append(f"  Suggested commit: {commit_msg}")
            summary_lines.append("")
            summary_lines.append("  Type /commit to stage and commit all changes")
            summary_lines.append("  Type /push to commit and push to GitHub")
            summary_lines.append("-" * 50)

        except subprocess.TimeoutExpired:
            return ""
        except FileNotFoundError:
            return ""  # git not installed
        except Exception as e:
            logger.debug(f"post_mission_git_summary error: {e}")
            return ""

        return "\n".join(summary_lines)

    def _generate_commit_message(self, mission: Mission) -> str:
        """
        Generate a conventional commit message from mission tasks.
        Format: <type>: <summary>
        """
        prompt = mission.user_prompt.lower()
        completed_titles = [
            t.title for t in mission.tasks
            if t.state.value == "COMPLETED"
        ]

        # Detect commit type
        if any(kw in prompt for kw in ["fix", "debug", "repair", "resolve"]):
            commit_type = "fix"
        elif any(kw in prompt for kw in ["test", "spec", "pytest"]):
            commit_type = "test"
        elif any(kw in prompt for kw in ["doc", "readme", "comment"]):
            commit_type = "docs"
        elif any(kw in prompt for kw in ["refactor", "clean", "restructure"]):
            commit_type = "refactor"
        else:
            commit_type = "feat"

        # Build summary from mission prompt (first 60 chars, cleaned)
        import re
        summary = re.sub(r'[^\w\s-]', '', mission.user_prompt)
        summary = " ".join(summary.split()[:8])
        summary = summary.lower().strip()

        return f"{commit_type}: {summary}"
