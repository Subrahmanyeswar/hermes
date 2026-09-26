# core/agent_loop/actions.py
"""
Harness Authorization and Action Execution Engine for HERMES 2.x Agent Loop.
Guarantees that:
    1. Model proposes actions, but harness authorizes.
    2. Unknown tools or out-of-workspace operations are rejected without physical execution.
    3. Execution produces canonical events, state updates, evidence, and observations.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple, Type
from loguru import logger

from core.agent_loop.types import ActionEnvelope, ActionStatus, Observation
from core.agent_loop.observations import ObservationBuilder
from core.event_bus import event_bus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from tools.registry import get_tool, list_tools, PermissionGate
from tools.base import BaseTool, ToolResult
from core.tool_validator import tool_validator
from core.workspace import WorkspaceManager


class HarnessPolicy:
    """
    Evaluates proposed actions against security rules, permissions,
    workspace boundaries, and parameter schemas.
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode if (isinstance(mode, str) and mode in ("auto", "plan", "safe")) else "auto"

    async def evaluate(
        self,
        action: ActionEnvelope,
        workspace: Optional[WorkspaceManager] = None
    ) -> Tuple[bool, str, Optional[Type[BaseTool]], Dict[str, Any]]:
        """
        Evaluate action envelope.
        Returns:
            (allowed: bool, reason: str, tool_class: Optional[Type], validated_params: dict)
        """
        tool_name = action.tool_name or ""
        if not tool_name:
            return False, "Tool name is empty", None, {}

        # ── 1. Check Tool Existence in Registry ──────────────────────────────
        tool_class = get_tool(tool_name)
        if tool_class is None:
            available = list_tools()
            return False, f"Unknown tool '{tool_name}'. Available tools: {', '.join(available[:10])}", None, {}

        # ── 2. Permission Gate Check ──────────────────────────────────────────
        gate = PermissionGate(self.mode)
        allowed, gate_reason = gate.check(tool_class)
        if not allowed:
            return False, f"Permission denied for '{tool_name}' in '{self.mode}' mode: {gate_reason}", None, {}

        # ── 3. Workspace Boundary Check ───────────────────────────────────────
        if workspace and workspace.is_locked:
            path_keys = ("path", "file", "filepath", "filename", "target", "file_path")
            for k in path_keys:
                raw_p = action.arguments.get(k)
                if isinstance(raw_p, str) and raw_p.strip():
                    try:
                        resolved = Path(raw_p)
                        if resolved.is_absolute():
                            ws_root = Path(workspace.root_str).resolve()
                            if not str(resolved.resolve()).startswith(str(ws_root)):
                                return False, f"Path traversal blocked: '{raw_p}' is outside workspace '{ws_root}'", None, {}
                        elif ".." in resolved.parts:
                            return False, f"Path traversal blocked: relative '..' navigation not allowed: '{raw_p}'", None, {}
                    except Exception as p_exc:
                        return False, f"Invalid path argument '{raw_p}': {p_exc}", None, {}

        # ── 4. Parameter Validation via ToolValidator ─────────────────────────
        try:
            val_res = await tool_validator.process_and_validate(
                tool_name=tool_name,
                raw_params=action.arguments,
                task_text=action.arguments.get("task_context", "") or tool_name,
                ollama_client=None,
                budget_manager=None,
            )
            if not val_res.is_valid:
                err_msg = f"Validation failed for '{tool_name}': {'; '.join(val_res.errors)}"
                return False, err_msg, tool_class, {}

            validated_params = val_res.normalized_params
            return True, "Allowed", tool_class, validated_params

        except Exception as val_exc:
            logger.warning(f"HarnessPolicy: validator exception for '{tool_name}': {val_exc}")
            # Fallback to arguments as-is if validator throws unexpected error
            return True, "Allowed (validation fallback)", tool_class, action.arguments


class ActionExecutor:
    """
    Coordinates harness evaluation, event emission, physical tool execution,
    and observation generation.
    """

    def __init__(self, mode: str = "auto") -> None:
        self.policy = HarnessPolicy(mode=mode)

    async def execute_action(
        self,
        action: ActionEnvelope,
        workspace: Optional[WorkspaceManager] = None
    ) -> Observation:
        """
        Execute action through harness policy.
        Emits canonical events and returns an Observation.
        """
        # Publish ACTION_REQUESTED event
        event_bus.publish(HermesEvent(
            event_type=EventType.ACTION_REQUESTED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            tool_call_id=action.tool_call_id,
            payload={
                "action_id": action.action_id,
                "tool_name": action.tool_name,
                "arguments": action.arguments,
            }
        ))

        # Evaluate policy
        allowed, reason, tool_class, validated_params = await self.policy.evaluate(action, workspace=workspace)

        if not allowed:
            action.status = ActionStatus.DENIED
            action.error = reason
            event_bus.publish(HermesEvent(
                event_type=EventType.ACTION_DENIED,
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                tool_call_id=action.tool_call_id,
                severity=EventSeverity.WARNING,
                payload={
                    "action_id": action.action_id,
                    "tool_name": action.tool_name,
                    "reason": reason,
                }
            ))
            return ObservationBuilder.from_harness_rejection(
                tool_name=action.tool_name or "unknown",
                reason=reason,
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
            )

        # Action is allowed
        action.status = ActionStatus.ALLOWED
        event_bus.publish(HermesEvent(
            event_type=EventType.ACTION_ALLOWED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            tool_call_id=action.tool_call_id,
            payload={
                "action_id": action.action_id,
                "tool_name": action.tool_name,
            }
        ))

        # Capture filesystem snapshot before tool execution
        ws_root = Path(workspace.root_str) if (workspace and workspace.is_locked) else Path("generated_projects")
        files_before = set(str(f) for f in ws_root.rglob("*") if f.is_file()) if ws_root.exists() else set()

        # Physical Tool Execution
        tool_instance = tool_class()
        t_start = time.monotonic()
        action.status = ActionStatus.EXECUTING

        event_bus.publish(HermesEvent(
            event_type=EventType.TOOL_STARTED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            tool_call_id=action.tool_call_id,
            payload={
                "action_id": action.action_id,
                "tool_name": action.tool_name,
                "arguments_summary": str(validated_params)[:200],
            }
        ))

        try:
            # Handle Pydantic input model if present on tool class
            input_model = getattr(tool_class, "input_model", None)
            if input_model is not None and isinstance(validated_params, dict):
                try:
                    tool_input = input_model(**validated_params)
                except Exception:
                    tool_input = validated_params
            else:
                tool_input = validated_params

            if asyncio.iscoroutinefunction(tool_instance.execute):
                tool_result = await tool_instance.execute(tool_input)
            else:
                tool_result = tool_instance.execute(tool_input)

            duration = time.monotonic() - t_start

        except Exception as exec_exc:
            duration = time.monotonic() - t_start
            logger.warning(f"ActionExecutor: exception executing {action.tool_name}: {exec_exc}")
            tool_result = ToolResult(
                success=False,
                exit_code=1,
                output="",
                error=f"Tool execution exception: {exec_exc}",
            )

        # Capture filesystem snapshot after tool execution
        files_after = set(str(f) for f in ws_root.rglob("*") if f.is_file()) if ws_root.exists() else set()

        # Build Observation
        obs = ObservationBuilder.from_tool_result(
            tool_name=action.tool_name,
            tool_result=tool_result,
            duration=duration,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            action_id=action.action_id,
            files_before=files_before,
            files_after=files_after,
        )

        # Publish tool completion / failure event
        is_success = obs.success
        action.status = ActionStatus.SUCCEEDED if is_success else ActionStatus.FAILED
        event_bus.publish(HermesEvent(
            event_type=EventType.TOOL_COMPLETED if is_success else EventType.TOOL_FAILED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            tool_call_id=action.tool_call_id,
            severity=EventSeverity.INFO if is_success else EventSeverity.ERROR,
            payload={
                "action_id": action.action_id,
                "tool_name": action.tool_name,
                "exit_code": obs.exit_code,
                "duration": duration,
                "success": is_success,
                "error": obs.error_message,
            }
        ))

        # Publish Observation event
        event_bus.publish(HermesEvent(
            event_type=EventType.OBSERVATION_CREATED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            payload={
                "observation_id": obs.observation_id,
                "action_id": action.action_id,
                "tool_name": action.tool_name,
                "summary": obs.summary,
                "success": obs.success,
                "evidence_id": f"ev_{obs.observation_id}",
                "kind": "TOOL_RESULT",
            }
        ))

        return obs
