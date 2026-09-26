# core/agent_loop/actions.py
"""
Harness Authorization and Action Execution Engine for HERMES 2.x Agent Loop.
Guarantees that:
    1. Model proposes actions, but harness authorizes.
    2. Unknown tools or out-of-workspace operations are rejected without physical execution.
    3. Execution produces canonical events, state updates, evidence, and observations.
    4. Integrates seamlessly with tools.platform (Catalog, Validator, PermissionPolicy, OutputShaper).
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
from core.workspace import WorkspaceManager

# Tool Platform integration
from tools.platform.catalog import tool_catalog
from tools.platform.validator import Validator
from tools.platform.permissions import PermissionPolicy, PermissionDecision
from tools.platform.output import OutputShaper, output_store
from tools.platform.search import tool_search
from tools.platform.specs import ToolSpec, ResponseFormat
from tools.base import BaseTool, ToolResult


class HarnessPolicy:
    """
    Evaluates proposed actions against security rules, permissions,
    workspace boundaries, and parameter schemas using canonical ToolPlatform.
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode if (isinstance(mode, str) and mode in ("auto", "plan", "safe")) else "auto"
        self._permission_policy = PermissionPolicy(mode=self.mode)

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
        raw_tool_name = action.tool_name or ""
        if not raw_tool_name:
            return False, "Tool name is empty", None, {}

        # ── Handle Dynamic Discovery Built-in ────────────────────────────────
        if raw_tool_name in ("tool_search", "search_tools"):
            return True, "Allowed", None, action.arguments

        # ── 1. Resolve Canonical Name & ToolSpec ──────────────────────────────
        canonical_name = tool_catalog.resolve_name(raw_tool_name)
        spec = tool_catalog.get(canonical_name)

        if spec is None:
            core_tools = [s.canonical_name for s in tool_catalog.list_core()[:8]]
            return False, f"Unknown tool '{raw_tool_name}'. Available tools: {', '.join(core_tools)}", None, {}

        # ── 2. Parameter Validation via Platform Validator ───────────────────
        is_valid, val_err, validated_args = Validator.validate(spec, action.arguments, workspace=workspace)
        if not is_valid and val_err is not None:
            return False, val_err.message, spec.implementation_cls, {}

        # ── 3. Permission Clearance via Platform Policy ──────────────────────
        decision, perm_reason = self._permission_policy.authorize(spec, validated_args)
        if decision != PermissionDecision.ALLOW:
            return False, f"Permission denied for '{canonical_name}' in '{self.mode}' mode: {perm_reason}", spec.implementation_cls, {}

        return True, "Allowed", spec.implementation_cls, validated_args


class ActionExecutor:
    """
    Coordinates harness evaluation, event emission, physical tool execution,
    output shaping, and observation generation.
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
        raw_name = action.tool_name or ""
        canonical_name = tool_catalog.resolve_name(raw_name) if raw_name not in ("tool_search", "search_tools") else raw_name

        # Publish ACTION_REQUESTED event
        event_bus.publish(HermesEvent(
            event_type=EventType.ACTION_REQUESTED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            tool_call_id=action.tool_call_id,
            payload={
                "action_id": action.action_id,
                "tool_name": canonical_name,
                "requested_tool_name": raw_name,
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
                    "tool_name": canonical_name,
                    "reason": reason,
                }
            ))
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name or "unknown",
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
                "tool_name": canonical_name,
            }
        ))

        # ── Handle Dynamic Discovery Built-in Directly ───────────────────────
        if canonical_name in ("tool_search", "search_tools"):
            query = validated_params.get("query", "")
            results = tool_search.search(query=query)
            formatted = tool_search.format_search_results(query, results)
            return Observation(
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
                source_type="tool",
                source_id="tool_search",
                success=True,
                summary=f"Found {len(results)} tool(s) matching '{query}'",
                content=formatted,
            )

        # Capture filesystem snapshot before tool execution
        ws_root = Path(workspace.root_str) if (workspace and workspace.is_locked) else Path("generated_projects")
        files_before = set(str(f) for f in ws_root.rglob("*") if f.is_file()) if ws_root.exists() else set()

        # Physical Tool Execution
        if tool_class is None:
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name,
                reason=f"No executable class bound for {canonical_name}",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
            )

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
                "tool_name": canonical_name,
                "arguments_summary": str(validated_params)[:200],
            }
        ))

        try:
            input_model = getattr(tool_class, "Input", getattr(tool_class, "input_model", None))
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
            logger.warning(f"ActionExecutor: exception executing {canonical_name}: {exec_exc}")
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
            tool_name=canonical_name,
            tool_result=tool_result,
            duration=duration,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            action_id=action.action_id,
            files_before=files_before,
            files_after=files_after,
        )

        # Apply Output Shaping and Externalization for large output
        raw_out = getattr(tool_result, "output", "") or ""
        if len(raw_out) > OutputShaper.DEFAULT_NORMAL_MAX_CHARS:
            shaped = OutputShaper.shape(
                raw_output=raw_out,
                response_format=ResponseFormat.NORMAL,
                tool_name=canonical_name,
                tool_call_id=action.tool_call_id or action.action_id,
            )
            obs.content = shaped.to_observation_text()
            obs.full_result_ref = shaped.full_output_ref

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
                "tool_name": canonical_name,
                "exit_code": obs.exit_code,
                "duration": duration,
                "success": is_success,
                "error": obs.error_message,
                "full_output_ref": obs.full_result_ref,
                "details": getattr(tool_result, "details", {}) or {},
            },
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
                "tool_name": canonical_name,
                "summary": obs.summary,
                "success": obs.success,
                "evidence_id": f"ev_{obs.observation_id}",
                "kind": "TOOL_RESULT",
                "full_result_ref": obs.full_result_ref,
                "details": getattr(tool_result, "details", {}) or {},
            }
        ))


        return obs
