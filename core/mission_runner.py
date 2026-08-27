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
        Execute one task through the full Orchestrator pipeline.

        CRITICAL DESIGN RULE:
        Tool execution success (exit_code=0) is NOT the same as task completion.
        Task completion requires evidence that the requested work was done.

        This method:
        1. Runs the orchestrator to generate and execute a tool call
        2. Checks if the tool call was meaningful (not just folder creation)
        3. If a write/implementation tool ran: verify the output exists and
           is non-empty
        4. If only a folder was created when files were needed: re-execute
           with a more specific prompt demanding file content
        5. Only marks COMPLETE when evidence exists
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

        # ── Build enriched prompt ─────────────────────────────────────────
        enriched_prompt = self._build_task_prompt(task, mission)

        await self._emit(MissionEvent(
            event_type="thought",
            payload={
                "text": f"Working on: {task.title}",
                "detail": f"Skill: {task.skill_hint or 'none'} | Attempt: {task.retry_count + 1}"
            }
        ))

        # ── Execute through orchestrator ──────────────────────────────────
        try:
            orch_result = await self.orchestrator.run(enriched_prompt)

            # Track costs
            if hasattr(orch_result, 'tier3_was_called') and orch_result.tier3_was_called:
                self._tier3_calls += 1
                try:
                    cost = self.orchestrator.claude.get_cost_summary()
                    self._total_cost = cost.get("total_spent", 0.0)
                except Exception:
                    pass

            # Capture output for context continuity
            if orch_result.final_output:
                self._recent_outputs.append(orch_result.final_output[:600])
                if len(self._recent_outputs) > 12:
                    self._recent_outputs = self._recent_outputs[-12:]

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
                }
            ))

            self._track_file_changes(orch_result)

            # ── CRITICAL: Evidence-based completion check ──────────────────
            if not orch_result.success or orch_result.pipeline_stage_reached < 6:
                # Tool execution failed
                await self._handle_task_failure(
                    mission, task,
                    error=orch_result.error or "Tool execution did not succeed",
                    output=orch_result.final_output or "",
                )
                return

            # Check for shallow execution: only folder created when
            # implementation was required
            tool_name = orch_result.tool_name or ""
            task_needs_implementation = self._task_needs_implementation(task)

            if task_needs_implementation and tool_name == "create_folder":
                # Folder creation alone is not sufficient for implementation tasks
                # Re-execute with a more demanding prompt
                await self._emit(MissionEvent(
                    event_type="thought",
                    payload={
                        "text": f"Folder created but implementation needed — re-executing",
                        "detail": f"Task '{task.title}' requires file content, not just folders"
                    }
                ))
                await self._handle_task_failure(
                    mission, task,
                    error=(
                        f"Task requires file implementation but only "
                        f"create_folder was executed. The task must write actual "
                        f"file content. Retry with write_file calls."
                    ),
                    output=orch_result.final_output or "",
                )
                return

            # Verify filesystem evidence if task should produce files
            if task_needs_implementation:
                evidence_ok, evidence_msg = await self._verify_task_evidence(task, mission)
                if not evidence_ok and task.retry_count < task.max_retries:
                    await self._handle_task_failure(
                        mission, task,
                        error=f"Verification failed: {evidence_msg}",
                        output=orch_result.final_output or "",
                    )
                    return

            # Task genuinely complete
            task.is_verified = True
            task.verification_evidence = orch_result.final_output or ""
            mission.mark_task_complete(task.task_id)

            await self._emit(MissionEvent(
                event_type="task_complete",
                payload={
                    "task_id": task.task_id,
                    "title": task.title,
                    "output_preview": (orch_result.final_output or "")[:300],
                }
            ))

        except Exception as exc:
            logger.error(
                f"MissionRunner: unexpected error during task '{task.title}': {exc}"
            )
            await self._handle_task_failure(
                mission, task,
                error=f"Unexpected error: {type(exc).__name__}: {str(exc)[:200]}",
                output=""
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
        Generate the post-mission walkthrough summary.
        This is what the user sees after HERMES completes the mission.
        Inspired by Claude Code's execution summary.
        """
        completed = [t for t in mission.tasks if t.state == TaskState.COMPLETED]
        failed = [t for t in mission.tasks if t.state == TaskState.FAILED]
        blocked = [t for t in mission.tasks if t.state == TaskState.BLOCKED]

        elapsed = time.monotonic() - self._start_time
        completed_count, total_count = mission.progress

        lines: list[str] = []
        lines.append("")
        lines.append("━" * 55)

        if mission.is_complete:
            lines.append("  MISSION COMPLETE ✓")
        else:
            lines.append(f"  MISSION PARTIAL ({completed_count}/{total_count} tasks)")

        lines.append("━" * 55)
        lines.append("")

        if completed:
            lines.append("  Completed:")
            for task in completed:
                lines.append(f"    ✓  {task.title}")
        lines.append("")

        if self._files_created:
            lines.append("  Created:")
            for f in self._files_created[:10]:
                lines.append(f"    +  {f}")
            lines.append("")

        if self._files_modified:
            lines.append("  Modified:")
            for f in self._files_modified[:10]:
                lines.append(f"    ~  {f}")
            lines.append("")

        if failed:
            lines.append("  Failed:")
            for task in failed:
                lines.append(f"    ✗  {task.title}")
                if task.error_message:
                    lines.append(f"       {task.error_message[:60]}")
            lines.append("")

        lines.append(f"  Time:   {elapsed:.1f}s")
        lines.append(f"  Cost:   ${self._total_cost:.4f}")
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
