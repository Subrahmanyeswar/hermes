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

from core.mission_planner import Mission, MissionTask, TaskState
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
        Handles retries, error injection, and repair cycles.
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

        # Build the enriched prompt for this specific task
        enriched_prompt = self._build_task_prompt(task, mission)

        # Temporarily inject the skill hint into the orchestrator
        original_skill = None
        if task.skill_hint and hasattr(self.orchestrator, 'classifier'):
            # Force the skill for this specific task
            original_skill = task.skill_hint

        # Emit thought about what we're doing
        await self._emit(MissionEvent(
            event_type="thought",
            payload={
                "text": f"Executing: {task.title}",
                "detail": f"Skill: {task.skill_hint or 'none'} | Retry: {task.retry_count}"
            }
        ))

        # Call the existing Orchestrator — it handles T1/T2/T3 pipeline
        try:
            orch_result = await self.orchestrator.run(enriched_prompt)

            # Update cost tracking
            if hasattr(orch_result, 'tier3_was_called') and orch_result.tier3_was_called:
                self._tier3_calls += 1
                cost = self.orchestrator.claude.get_cost_summary()
                self._total_cost = cost.get("total_spent", 0.0)

            # Emit tool result
            await self._emit(MissionEvent(
                event_type="tool_result",
                payload={
                    "task_id": task.task_id,
                    "tool_name": orch_result.tool_name,
                    "success": orch_result.success,
                    "stage_reached": orch_result.pipeline_stage_reached,
                    "output_preview": (orch_result.final_output or "")[:200],
                    "tier3_called": orch_result.tier3_was_called,
                    "trace_id": orch_result.trace_id,
                }
            ))

            # Track file changes
            self._track_file_changes(orch_result)

            if orch_result.final_output:
                self._recent_outputs.append(orch_result.final_output[:500])
                if len(self._recent_outputs) > 10:
                    self._recent_outputs = self._recent_outputs[-10:]  # Keep last 10 only

            # Determine task success
            if orch_result.success and orch_result.pipeline_stage_reached >= 6:
                mission.mark_task_complete(task.task_id)
                await self._emit(MissionEvent(
                    event_type="task_complete",
                    payload={
                        "task_id": task.task_id,
                        "title": task.title,
                        "output_preview": (orch_result.final_output or "")[:200],
                    }
                ))
            else:
                # Task failed — enter repair cycle
                await self._handle_task_failure(
                    mission, task,
                    error=orch_result.error or "Tool execution did not succeed",
                    output=orch_result.final_output or "",
                )

        except Exception as exc:
            logger.error(f"MissionRunner: unexpected error during task '{task.title}': {exc}")
            await self._handle_task_failure(
                mission, task,
                error=f"Unexpected error: {type(exc).__name__}: {str(exc)[:200]}",
                output=""
            )

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
                "error": error[:200],
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
            }
        ))

        if task.retry_count < task.max_retries:
            # Retry with error context
            task.retry_count += 1
            task.state = TaskState.PENDING

            await self._emit(MissionEvent(
                event_type="repair_attempt",
                payload={
                    "task_id": task.task_id,
                    "attempt": task.retry_count,
                    "max": task.max_retries,
                    "error_injected": error[:100],
                }
            ))

            # Inject error context into the task description for next attempt
            task.description = (
                f"REPAIR ATTEMPT {task.retry_count}/{task.max_retries}: {task.description}\n\n"
                f"PREVIOUS ATTEMPT FAILED WITH:\n{error}\n\n"
                f"Previous output:\n{output[:300]}\n\n"
                f"Analyze the error above and provide a corrected implementation."
            )

            logger.info(
                f"MissionRunner: retrying task '{task.title}' "
                f"(attempt {task.retry_count}/{task.max_retries})"
            )
        else:
            # Max retries exceeded
            mission.mark_task_failed(task.task_id, error)
            logger.error(
                f"MissionRunner: task '{task.title}' FAILED after "
                f"{task.max_retries} attempts — marking FAILED"
            )

    # ── Context building ──────────────────────────────────────────────────────

    def _build_task_prompt(self, task: MissionTask, mission: Mission) -> str:
        """
        Build enriched task prompt using ContextBuilder.
        Budget-aware — never exceeds 6000 tokens of context.
        """
        error_ctx = task.error_message if task.retry_count > 0 else ""

        context = self._context_builder.build(
            task=task,
            mission=mission,
            memory_context=self._get_memory_context(),
            previous_outputs=self._recent_outputs[-3:],
            error_context=error_ctx,
        )

        logger.debug(context.summary())
        return context.to_string() + f"\n\nTASK: {task.description}"

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
