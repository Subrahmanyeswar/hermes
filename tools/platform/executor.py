# tools/platform/executor.py
"""
Unified Tool Execution Engine for HERMES 2.x Tool Platform.
Coordinates tool validation, authorization, physical execution,
event emission, output shaping, and external storage within the harness.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from core.event_bus import event_bus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from core.workspace import WorkspaceManager
from tools.base import BaseTool, ToolResult
from tools.platform.specs import ToolSpec, ResponseFormat
from tools.platform.catalog import tool_catalog
from tools.platform.permissions import PermissionPolicy, PermissionDecision
from tools.platform.validator import Validator
from tools.platform.errors import ToolError, ToolErrorCode, ErrorGuidance
from tools.platform.output import OutputShaper, ShapedOutput


@dataclass
class ToolPlatformResult:
    """Complete structured result for an executed tool call."""
    tool_call_id: str
    action_id: str
    tool_name: str
    canonical_name: str
    success: bool
    status: str
    started_at: float
    completed_at: float
    duration_seconds: float
    output_summary: str
    full_output_ref: Optional[str] = None
    error: Optional[ToolError] = None
    exit_code: int = 0
    retry_count: int = 0
    evidence_refs: List[str] = field(default_factory=list)
    observation_text: str = ""
    shaped_output: Optional[ShapedOutput] = None


class ToolExecutor:
    """
    Harness-enforced tool execution layer.
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self.permission_policy = PermissionPolicy(mode=mode)

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: str = "",
        action_id: str = "",
        mission_id: str = "",
        task_id: str = "",
        turn_id: str = "",
        workspace: Optional[WorkspaceManager] = None,
        abort_event: Optional[asyncio.Event] = None,
        response_format: ResponseFormat = ResponseFormat.NORMAL,
    ) -> ToolPlatformResult:
        """
        Execute a tool through the full validation, permission, and execution pipeline.
        """
        start_t = time.monotonic()
        started_at = time.time()
        canonical_name = tool_catalog.resolve_name(tool_name)
        spec = tool_catalog.get(canonical_name)

        # ── 1. Check Tool Existence ──────────────────────────────────────────
        if spec is None:
            err = ToolError(
                code=ToolErrorCode.TOOL_NOT_FOUND,
                message=f"Unknown tool '{tool_name}'",
                what_failed=f"Lookup for {tool_name}",
                why_it_failed=f"Tool '{tool_name}' is not registered in the catalog.",
                actionable_guidance=ErrorGuidance.format_guidance(
                    ToolErrorCode.TOOL_NOT_FOUND,
                    tool_name,
                    {"closest": [s.canonical_name for s in tool_catalog.list_core()[:4]]},
                ),
            )
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=err,
                start_t=start_t,
                started_at=started_at,
                exit_code=1,
            )

        # ── 2. Parameter Validation ──────────────────────────────────────────
        is_valid, val_error, validated_args = Validator.validate(spec, arguments, workspace=workspace)
        if not is_valid and val_error is not None:
            event_bus.publish(HermesEvent(
                event_type=EventType.TOOL_FAILED,
                mission_id=mission_id,
                task_id=task_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                severity=EventSeverity.WARNING,
                payload={
                    "tool": canonical_name,
                    "error": val_error.message,
                    "code": val_error.code.value,
                },
            ))
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=val_error,
                start_t=start_t,
                started_at=started_at,
                exit_code=1,
            )

        # ── 3. Permission Clearance ──────────────────────────────────────────
        decision, perm_reason = self.permission_policy.authorize(spec, validated_args)
        if decision != PermissionDecision.ALLOW:
            perm_err = ToolError(
                code=ToolErrorCode.PERMISSION_DENIED if decision == PermissionDecision.DENY else ToolErrorCode.USER_REQUIRED,
                message=perm_reason,
                what_failed=f"Permission evaluation for {canonical_name}",
                why_it_failed=perm_reason,
                actionable_guidance=ErrorGuidance.format_guidance(
                    ToolErrorCode.PERMISSION_DENIED,
                    canonical_name,
                ),
            )
            event_bus.publish(HermesEvent(
                event_type=EventType.ACTION_DENIED,
                mission_id=mission_id,
                task_id=task_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                severity=EventSeverity.WARNING,
                payload={
                    "tool": canonical_name,
                    "reason": perm_reason,
                    "decision": decision.value,
                },
            ))
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=perm_err,
                start_t=start_t,
                started_at=started_at,
                exit_code=126,
            )

        # ── 4. Check Cancellation Before Launch ──────────────────────────────
        if abort_event is not None and abort_event.is_set():
            cancel_err = ToolError(
                code=ToolErrorCode.PROCESS_FAILED,
                message="Tool execution cancelled by user signal",
                what_failed=f"Execution of {canonical_name}",
                why_it_failed="Abort signal active before execution.",
            )
            event_bus.publish(HermesEvent(
                event_type=EventType.TOOL_CANCELLED,
                mission_id=mission_id,
                task_id=task_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                payload={"tool": canonical_name},
            ))
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=cancel_err,
                start_t=start_t,
                started_at=started_at,
                exit_code=130,
            )

        # ── 5. Fire TOOL_STARTED Event ───────────────────────────────────────
        event_bus.publish(HermesEvent(
            event_type=EventType.TOOL_STARTED,
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            payload={
                "tool": canonical_name,
                "arguments": str(validated_args)[:200],
            },
        ))

        # ── 6. Physical Tool Execution ───────────────────────────────────────
        tool_cls = spec.implementation_cls
        if tool_cls is None:
            err = ToolError(
                code=ToolErrorCode.TOOL_UNAVAILABLE,
                message=f"Tool implementation for '{canonical_name}' is not loaded.",
                what_failed=f"Instantiation of {canonical_name}",
                why_it_failed="No implementation class bound in ToolSpec.",
            )
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=err,
                start_t=start_t,
                started_at=started_at,
                exit_code=1,
            )

        instance = tool_cls()
        if workspace is not None and isinstance(validated_args, dict):
            validated_args["_workspace"] = workspace

        try:
            # Handle Pydantic Input model if needed
            inp_model = getattr(tool_cls, "Input", getattr(tool_cls, "input_model", None))
            if inp_model is not None and isinstance(validated_args, dict):
                try:
                    tool_inp = inp_model(**validated_args)
                except Exception:
                    tool_inp = validated_args
            else:
                tool_inp = validated_args

            # Execute sync or async
            if asyncio.iscoroutinefunction(instance.execute):
                raw_res = await instance.execute(tool_inp)
            else:
                raw_res = instance.execute(tool_inp)

            if isinstance(raw_res, ToolResult):
                success = raw_res.success
                output_str = raw_res.output or ""
                error_str = raw_res.error
                exit_code = raw_res.exit_code
            else:
                success = True
                output_str = str(raw_res)
                error_str = None
                exit_code = 0

        except Exception as exc:
            duration = time.monotonic() - start_t
            logger.warning(f"ToolExecutor: execution exception in {canonical_name}: {exc}")
            err = ToolError(
                code=ToolErrorCode.INTERNAL_ERROR,
                message=f"Execution error: {exc}",
                what_failed=f"Execution of {canonical_name}",
                why_it_failed=str(exc),
                actionable_guidance="Check error logs and adjust tool parameters.",
            )
            event_bus.publish(HermesEvent(
                event_type=EventType.TOOL_FAILED,
                mission_id=mission_id,
                task_id=task_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                severity=EventSeverity.WARNING,
                payload={"tool": canonical_name, "error": str(exc)},
            ))
            return self._build_failure_result(
                tool_call_id=tool_call_id,
                action_id=action_id,
                tool_name=tool_name,
                canonical_name=canonical_name,
                error=err,
                start_t=start_t,
                started_at=started_at,
                exit_code=1,
            )

        duration = time.monotonic() - start_t
        completed_at = time.time()

        # ── 7. Output Shaping & External Storage ─────────────────────────────
        shaped = OutputShaper.shape(
            raw_output=output_str,
            response_format=response_format,
            tool_name=canonical_name,
            tool_call_id=tool_call_id,
        )

        obs_text = shaped.to_observation_text()
        if not success and error_str:
            obs_text = f"Tool '{canonical_name}' reported failure:\n{error_str}\n\nOutput:\n{obs_text}"

        # ── 8. Fire Completion or Failure Event ──────────────────────────────
        ev_type = EventType.TOOL_COMPLETED if success else EventType.TOOL_FAILED
        event_bus.publish(HermesEvent(
            event_type=ev_type,
            mission_id=mission_id,
            task_id=task_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            payload={
                "tool": canonical_name,
                "success": success,
                "duration_seconds": duration,
                "output_preview": shaped.content[:200],
                "truncated": shaped.truncated,
                "full_output_ref": shaped.full_output_ref,
            },
        ))

        return ToolPlatformResult(
            tool_call_id=tool_call_id,
            action_id=action_id,
            tool_name=tool_name,
            canonical_name=canonical_name,
            success=success,
            status="COMPLETED" if success else "FAILED",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            output_summary=shaped.summary,
            full_output_ref=shaped.full_output_ref,
            error=ToolError(
                code=ToolErrorCode.PROCESS_FAILED,
                message=error_str or "Tool execution failed",
                what_failed=canonical_name,
                why_it_failed=error_str or "Exit code non-zero",
            ) if not success else None,
            exit_code=exit_code,
            observation_text=obs_text,
            shaped_output=shaped,
        )

    def _build_failure_result(
        self,
        tool_call_id: str,
        action_id: str,
        tool_name: str,
        canonical_name: str,
        error: ToolError,
        start_t: float,
        started_at: float,
        exit_code: int = 1,
    ) -> ToolPlatformResult:
        duration = time.monotonic() - start_t
        completed_at = time.time()
        return ToolPlatformResult(
            tool_call_id=tool_call_id,
            action_id=action_id,
            tool_name=tool_name,
            canonical_name=canonical_name,
            success=False,
            status="FAILED",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            output_summary=f"Failed: {error.code.value}",
            error=error,
            exit_code=exit_code,
            observation_text=error.to_observation_text(),
        )
