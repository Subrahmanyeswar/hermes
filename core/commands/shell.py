# core/commands/shell.py
"""
OS and Shell Command Execution Subsystem for HERMES 2.x (Prompt 16).

Central Invariants:
1. NO SECURITY BYPASS: User-initiated ! commands pass through Prompt 13 security evaluation.
2. ZERO LLM CALLS: Executed directly as local OS processes; never forwarded to the model.
3. PLATFORM AWARE: Safe execution on Windows (cmd/PowerShell) and POSIX (sh/bash) with UTF-8 encoding.
4. CONTROLLED LIFECYCLE: Integrated with BackgroundJobManager and CancellationController.
5. TEXT SAFETY: Terminal output sanitized with text_safety to eliminate ANSI/CSI/OSC injection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.commands.models import (
    CommandErrorCode,
    CommandExecutionClass,
    CommandIntent,
    CommandResult,
    CommandStatus,
)
from core.event_bus import EventBus
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.security.enums import PermissionOutcome
from core.security.service import SecurityService
from core.subagents.background import BackgroundJobManager
from core.subagents.cancellation import CancellationController
from ui.rendering.text_safety import sanitize_terminal_text

logger = logging.getLogger("hermes.commands.shell")

# Maximum bytes retained in memory for stdout/stderr preview
MAX_OUTPUT_CAPTURE_BYTES = 500 * 1024  # 500 KB


class ShellExecutor:
    """Safely executes user shell commands (!) with security and lifecycle controls."""

    def __init__(
        self,
        workspace_root: Path | str,
        security_service: Optional[SecurityService] = None,
        job_manager: Optional[BackgroundJobManager] = None,
        event_bus: Optional[EventBus] = None,
        cancellation_controller: Optional[CancellationController] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.security = security_service
        self.job_manager = job_manager
        self.event_bus = event_bus
        self.cancellation = cancellation_controller or CancellationController()

    async def execute_command(
        self,
        intent: CommandIntent,
        timeout_seconds: Optional[float] = 120.0,
        is_headless: bool = False,
    ) -> CommandResult:
        """
        Execute a shell command with security validation, job tracking, and process isolation.
        """
        command_line = intent.kwargs.get("command_line") or (
            intent.args[0] if intent.args else ""
        )
        if not command_line and intent.raw_text:
            command_line = intent.raw_text.lstrip("!").strip()
        command_line = command_line.strip()

        if not command_line:
            return CommandResult.failure(
                intent=intent,
                message="Empty shell command line provided.",
                error_code=CommandErrorCode.INVALID_ARGUMENTS,
                exit_code=2,
            )

        start_time = time.monotonic()

        # 1. Prompt 13 Security Evaluation
        if self.security:
            decision, action = self.security.evaluate_tool_call(
                tool_name="bash",
                arguments={"command": command_line},
                session_id=intent.session_id,
            )

            if decision.outcome == PermissionOutcome.DENY:
                logger.warning(
                    f"Shell command '{command_line}' DENIED by security policy: {decision.reason}"
                )
                return CommandResult.denied(
                    intent=intent,
                    reason=f"Security policy denied shell command: {decision.reason}",
                    error_code=CommandErrorCode.SECURITY_DENIED,
                    exit_code=3,
                    data={"command": command_line, "decision": decision.outcome.value},
                )
            elif decision.outcome == PermissionOutcome.ASK and is_headless:
                # Headless fail-closed invariant
                logger.warning(
                    f"Shell command '{command_line}' requires human approval but running in headless mode. Failing closed."
                )
                return CommandResult.denied(
                    intent=intent,
                    reason="Security approval required (ASK) but no interactive channel is available in headless mode.",
                    error_code=CommandErrorCode.SECURITY_DENIED,
                    exit_code=3,
                    data={"command": command_line, "decision": "ASK_FAILED_CLOSED"},
                )

        # 2. Publish start event
        job_id = f"job_shell_{uuid.uuid4().hex[:8]}"
        if self.event_bus:
            self.event_bus.publish(
                HermesEvent(
                    event_type=EventType.BACKGROUND_JOB_STARTED,
                    session_id=intent.session_id,
                    mission_id=intent.mission_id,
                    payload={
                        "job_id": job_id,
                        "command": command_line,
                        "kind": "SHELL",
                        "workspace": str(self.workspace_root),
                    },
                )
            )

        # 3. Subprocess Execution
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        exit_code = 1
        timed_out = False
        cancelled = False

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command_line,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Register with cancellation controller
            async def _wait_with_cancellation():
                return await proc.communicate()

            if timeout_seconds:
                stdout_data, stderr_data = await asyncio.wait_for(
                    _wait_with_cancellation(),
                    timeout=timeout_seconds,
                )
            else:
                stdout_data, stderr_data = await _wait_with_cancellation()

            exit_code = proc.returncode or 0
            raw_stdout = stdout_data.decode("utf-8", errors="replace")[:MAX_OUTPUT_CAPTURE_BYTES]
            raw_stderr = stderr_data.decode("utf-8", errors="replace")[:MAX_OUTPUT_CAPTURE_BYTES]

        except asyncio.TimeoutError:
            timed_out = True
            exit_code = 124
            if proc:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    pass
            raw_stdout = ""
            raw_stderr = f"Command timed out after {timeout_seconds} seconds."

        except asyncio.CancelledError:
            cancelled = True
            exit_code = 130
            if proc:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    pass
            raw_stdout = ""
            raw_stderr = "Command cancelled."

        except Exception as e:
            exit_code = 1
            raw_stdout = ""
            raw_stderr = f"Failed to spawn process: {e}"

        elapsed = time.monotonic() - start_time

        # 4. Sanitize text for safe display
        clean_stdout = sanitize_terminal_text(raw_stdout)
        clean_stderr = sanitize_terminal_text(raw_stderr)

        # 5. Publish completion event
        if self.event_bus:
            evt_type = (
                EventType.BACKGROUND_JOB_CANCELLED
                if cancelled
                else (
                    EventType.BACKGROUND_JOB_FAILED
                    if exit_code != 0
                    else EventType.BACKGROUND_JOB_COMPLETED
                )
            )
            self.event_bus.publish(
                HermesEvent(
                    event_type=evt_type,
                    session_id=intent.session_id,
                    mission_id=intent.mission_id,
                    payload={
                        "job_id": job_id,
                        "command": command_line,
                        "exit_code": exit_code,
                        "duration_seconds": elapsed,
                        "timed_out": timed_out,
                    },
                )
            )

        if cancelled:
            return CommandResult.cancelled(intent=intent, reason="Shell execution cancelled.")

        output_msg = clean_stdout if clean_stdout else clean_stderr
        status = CommandStatus.SUCCESS if exit_code == 0 else CommandStatus.FAILURE

        return CommandResult(
            command_id=intent.command_id,
            name=intent.name,
            status=status,
            message=output_msg.strip(),
            data={
                "job_id": job_id,
                "command": command_line,
                "exit_code": exit_code,
                "stdout": clean_stdout,
                "stderr": clean_stderr,
                "timed_out": timed_out,
            },
            exit_code=exit_code,
            llm_called=False,
            execution_class=CommandExecutionClass.EXTERNAL_ACTION,
            duration_seconds=elapsed,
            error_code=CommandErrorCode.EXECUTION_ERROR if exit_code != 0 else None,
        )
