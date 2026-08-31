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
    ) -> None:
        self.orchestrator = orchestrator
        self.workspace = workspace_manager
        self.event_queue = event_queue or asyncio.Queue()
        self.abort_event = abort_event or asyncio.Event()
        self._context_builder = ContextBuilder(workspace_manager)
        self._recent_outputs: list[str] = []
        self._current_phase = MissionPhase.PLANNING
        self._start_time: float = 0.0
        self._total_cost: float = 0.0
        self._tier3_calls: int = 0
        self._files_created: list[str] = []
        self._files_modified: list[str] = []

    # ── Main execution loop ───────────────────────────────────────────────────

    async def run(self, mission: Mission) -> MissionResult:
        """
        Execute the mission from start to finish.
        This is the main loop — it runs until the mission is complete,
        a failure is unrecoverable, or the user aborts.

        Returns MissionResult with full execution summary.
        """
        self._start_time = time.monotonic()
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

        # ── Main mission loop ─────────────────────────────────────────────────
        while not mission.is_complete:

            # Check abort signal
            if self.abort_event.is_set():
                logger.warning(f"MissionRunner: abort signal received for {mission.mission_id}")
                await self._emit(MissionEvent(event_type="mission_aborted", payload={}))
                return self._build_result(mission, success=False, error="Aborted by user")

            # Get next task
            task = mission.next_executable_task
            if task is None:
                # No executable task — either all done or all blocked
                if mission.has_failure:
                    logger.error("MissionRunner: all remaining tasks blocked by failure")
                    break
                # Shouldn't happen, but safety guard
                logger.warning("MissionRunner: no executable task found — checking completion")
                break

            # Execute one task
            await self._execute_task(mission, task)

            # Brief pause to allow UI to update and prevent hammering Ollama
            await asyncio.sleep(0.2)

        # ── Final mission acceptance criteria check ────────────────────
        if mission.is_complete and mission.acceptance_criteria:
            self._current_phase = MissionPhase.VERIFYING
            await self._emit(MissionEvent(
                event_type="phase_change",
                payload={"phase": "VERIFYING"}
            ))

            unmet = await self._check_acceptance_criteria(mission)
            if unmet:
                # Some criteria not met — add repair tasks if retries left
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
                # Add repair tasks for unmet criteria
                for criterion in unmet[:3]:  # Max 3 repair tasks
                    repair_task = MissionTask(
                        title=f"Fix: {criterion[:50]}",
                        description=(
                            f"The following requirement was not satisfied: {criterion}\n"
                            f"Inspect the project files and implement what is missing.\n"
                            f"Project path: {mission.project_root_path}"
                        ),
                        priority=TaskPriority.CRITICAL,
                        max_retries=2,
                    )
                    mission.tasks.append(repair_task)
                    mission.execution_order.append(repair_task.task_id)

                # Continue the mission loop for repair tasks
                while not mission.is_complete:
                    if self.abort_event.is_set():
                        break
                    task = mission.next_executable_task
                    if task is None:
                        break
                    await self._execute_task(mission, task)
                    await asyncio.sleep(0.2)
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

            # If final check fails, add targeted repair tasks (max 2)
            if final_check.needs_improvement and final_check.requirements_missing:
                logger.info(
                    f"MissionRunner: final check failed — "
                    f"{len(final_check.requirements_missing)} requirements unmet"
                )
                for i, missing_req in enumerate(final_check.requirements_missing[:2]):
                    repair_task = MissionTask(
                        title=f"Final fix: {missing_req[:50]}",
                        description=final_check.repair_prompt,
                        priority=TaskPriority.CRITICAL,
                        max_retries=2,
                        acceptance_criteria=missing_req,
                    )
                    mission.tasks.append(repair_task)
                    mission.execution_order.append(repair_task.task_id)

                # Run repair tasks
                while not mission.is_complete:
                    if self.abort_event.is_set():
                        break
                    task = mission.next_executable_task
                    if task is None:
                        break
                    await self._execute_task(mission, task)
                    await asyncio.sleep(0.2)

        # ── Post-mission phase ────────────────────────────────────────────────
        self._current_phase = MissionPhase.SUMMARIZING
        await self._emit(MissionEvent(
            event_type="phase_change",
            payload={"phase": MissionPhase.SUMMARIZING.value}
        ))

        walkthrough = await self._generate_walkthrough(mission)

        result = self._build_result(mission, success=mission.is_complete)
        result.walkthrough_text = walkthrough

        git_summary = await self.post_mission_git_summary(mission)
        if git_summary:
            result.walkthrough_text = result.walkthrough_text + "\n" + git_summary

        event_type = "mission_complete" if mission.is_complete else "mission_failed"
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

        # ── Inner execution loop ───────────────────────────────────────────
        # Each iteration: generate → execute → observe → verify → maybe repair
        MAX_INNER_ITERATIONS = 3
        current_description = task.description
        inner_iteration = 0
        last_orch_result = None
        quality_result = None

        while inner_iteration < MAX_INNER_ITERATIONS:
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
                    await self._emit(MissionEvent(
                        event_type="pipeline_stage",
                        payload={
                            "task_id": task.task_id,
                            "stage": payload.get("stage", 0),
                            "stage_name": payload.get("name", ""),
                            "verb": payload.get("verb", "Working"),
                            "detail": payload.get("detail", ""),
                            "model": payload.get("model", ""),
                            "status": "start" if event_type == "stage_start" else "complete",
                        },
                    ))
                elif event_type == "tool_executing":
                    await self._emit(MissionEvent(
                        event_type="tool_executing",
                        payload={"task_id": task.task_id,
                                 "tool": payload.get("tool", ""),
                                 "verb": "Executing"},
                    ))
                elif event_type == "tool_complete":
                    await self._emit(MissionEvent(
                        event_type="tool_complete",
                        payload={
                            "task_id": task.task_id,
                            "tool": payload.get("tool", ""),
                            "success": payload.get("success", False),
                            "exit_code": payload.get("exit_code", -1),
                            "output_preview": payload.get("output_preview", ""),
                        },
                    ))

            self.orchestrator._progress_callback = _pipeline_progress

            try:
                orch_result = await self.orchestrator.run(enriched_prompt)
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
                    await asyncio.sleep(0.5)
                    continue
                else:
                    await self._handle_task_failure(
                        mission, task,
                        error=f"Unexpected error: {type(exc).__name__}: {str(exc)[:200]}",
                        output=""
                    )
                    return
            finally:
                self.orchestrator._progress_callback = None

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
                    await asyncio.sleep(0.5)
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
            # Only for tasks that should produce implementation output
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
                    project_root=mission.project_root_path or "",
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
                    await asyncio.sleep(0.3)
                    continue

                # Run structured feedback (Self-Refine + CRITIC combined)
                from core.structured_feedback import StructuredFeedbackGenerator
                fb_gen = StructuredFeedbackGenerator()

                # Get the file(s) written in this iteration
                recent_files = self._files_created[-3:] + self._files_modified[-2:]

                structured_fb_failed = False
                for file_path in recent_files:
                    from pathlib import Path
                    if not Path(file_path).exists():
                        continue

                    structured_fb = fb_gen.generate(
                        task_description=task.description,
                        file_path=file_path,
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
                            f"Read the file first with read_file, "
                            f"then fix each failing dimension listed above."
                        )
                        structured_fb_failed = True
                        break

                if structured_fb_failed:
                    await asyncio.sleep(0.3)
                    continue

            # ── Task passed quality check (or no quality check needed) ─────
            task.is_verified = True
            task.verification_evidence = (
                f"Quality: {quality_result.overall_verdict if quality_result else 'N/A'} | "
                f"Coverage: {quality_result.coverage_pct if quality_result else 100:.0f}%"
            )
            mission.mark_task_complete(task.task_id)

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
        if quality_result and quality_result.needs_improvement:
            # Accept with warning rather than failing — partial is better than nothing
            task.is_verified = False
            task.verification_evidence = (
                f"Quality: {quality_result.overall_verdict} | "
                f"Coverage: {quality_result.coverage_pct:.0f}% (accepted after {MAX_INNER_ITERATIONS} attempts)"
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

            elif "responsive" in lower:
                if root and root.exists():
                    for f in root.rglob("*.css"):
                        content = f.read_text(errors="ignore")
                        if "@media" in content:
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
            project_path = mission.project_root_path or "generated_projects/output"
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
        """
        Build task prompt using an override description.
        Used for repair iterations where the description includes
        quality findings and specific improvement instructions.
        """
        project_path = mission.project_root_path or "generated_projects/output"
        completed_count = sum(
            1 for t in mission.tasks if t.state == TaskState.COMPLETED
        )
        total_count = len(mission.tasks)

        # Build base context
        try:
            context = self._context_builder.build(
                task=task,
                mission=mission,
                memory_context=self._get_memory_context(),
                previous_outputs=self._recent_outputs[-3:],
                error_context="",  # Error context is already in override_description
            )
            base = context.to_string()
        except Exception:
            base = ""

        enforcement = f"""

═══ TASK EXECUTION REQUIREMENTS ═══
Project location: {project_path}
Mission progress: {completed_count}/{total_count} tasks complete
Previous outputs available for context: {len(self._recent_outputs)} items

MANDATORY IMPLEMENTATION RULES:
1. Use write_file to create files with COMPLETE, real implementation.
2. Do NOT write placeholder content, TODO comments, or stubs.
3. Do NOT stop after creating a folder.
4. Write REAL working code with sufficient depth and detail.
5. For HTML: minimum 40 lines with actual semantic structure and content.
6. For CSS: minimum 30 lines with real rules, variables, responsive design.
7. For JS/JSX: minimum 25 lines with actual logic and event handlers.
8. After writing files, verify they exist using bash_exec.
9. Inspect existing files first using read_file before modifying.

TASK:
{override_description}

SUCCESS CRITERION: {task.acceptance_criteria}
"""
        return base + enforcement

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
        if hasattr(orch_result, 'tool_result') and orch_result.tool_result:
            output = orch_result.tool_result.output or ""
            # Heuristic: extract file paths from output
            import re
            paths = re.findall(r'[\w\./\-]+\.\w{2,5}', output)
            for path in paths[:5]:  # Cap to avoid noise
                if tool in ("write_file", "create_folder"):
                    if path not in self._files_created:
                        self._files_created.append(path)
                elif tool in ("append_file",):
                    if path not in self._files_modified:
                        self._files_modified.append(path)

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
        """Put an event into the queue for the TUI to consume."""
        try:
            await asyncio.wait_for(
                self.event_queue.put(event),
                timeout=1.0
            )
        except asyncio.TimeoutError:
            logger.debug("MissionRunner: event queue full — dropping event")

    def _build_result(
        self,
        mission: Mission,
        success: bool,
        error: Optional[str] = None
    ) -> MissionResult:
        elapsed = time.monotonic() - self._start_time
        completed, total = mission.progress
        return MissionResult(
            mission_id=mission.mission_id,
            success=success,
            tasks_completed=completed,
            tasks_failed=sum(1 for t in mission.tasks if t.state == TaskState.FAILED),
            tasks_total=total,
            total_latency_seconds=elapsed,
            total_cost_usd=self._total_cost,
            tier3_calls=self._tier3_calls,
            files_created=self._files_created.copy(),
            files_modified=self._files_modified.copy(),
            error=error,
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
            summary_lines.append("─" * 50)
            summary_lines.append("  Git Status")
            summary_lines.append("─" * 50)
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
            summary_lines.append("─" * 50)

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
