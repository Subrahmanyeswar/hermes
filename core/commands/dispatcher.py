# core/commands/dispatcher.py
"""
Central Command Dispatcher for HERMES 2.x (Prompt 16).

Central Invariants:
1. UNIFIED EXECUTION PIPELINE: All commands from TUI, CLI, and Headless flow through this single dispatcher.
2. UNKNOWN COMMAND CONTAINMENT: Unknown commands NEVER trigger an accidental model call; return safe error.
3. CANONICAL DISPATCH: Routes to appropriate Prompt 7/9/10/12/13/14 service handlers.
4. OBSERVABLE: Emits structured command lifecycle events to EventBus with correlation IDs.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional

from core.commands.handlers.control_handlers import (
    handle_btw,
    handle_clear,
    handle_compact,
    handle_goal,
    handle_plan,
    handle_resume,
    handle_rewind,
)
from core.commands.handlers.query_handlers import (
    handle_context,
    handle_cost,
    handle_diff,
    handle_doctor,
    handle_status,
    handle_tasks,
)
from core.commands.models import (
    CommandErrorCode,
    CommandExecutionClass,
    CommandIntent,
    CommandOrigin,
    CommandResult,
    CommandStatus,
)
from core.commands.registry import CommandRegistry, command_registry as global_registry
from core.commands.shell import ShellExecutor
from core.event_bus import EventBus
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.store import StateStore
from core.security.service import SecurityService

logger = logging.getLogger("hermes.commands.dispatcher")


class CommandDispatcher:
    """Dispatches parsed CommandIntents to authoritative domain handlers."""

    def __init__(
        self,
        registry: Optional[CommandRegistry] = None,
        workspace_root: Optional[Path | str] = None,
        state_store: Optional[StateStore] = None,
        event_bus: Optional[EventBus] = None,
        security_service: Optional[SecurityService] = None,
        context_engine: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        rewind_engine: Optional[Any] = None,
        recovery_engine: Optional[Any] = None,
        planning_service: Optional[Any] = None,
        shell_executor: Optional[ShellExecutor] = None,
        model_client: Optional[Any] = None,
        network_supervisor: Optional[Any] = None,
    ):
        self.registry = registry or global_registry
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self.state_store = state_store
        self.event_bus = event_bus
        self.security = security_service
        self.context_engine = context_engine
        self.session_manager = session_manager
        self.rewind_engine = rewind_engine
        self.recovery_engine = recovery_engine
        self.planning_service = planning_service
        self.shell_executor = shell_executor or ShellExecutor(
            workspace_root=self.workspace_root,
            security_service=self.security,
            event_bus=self.event_bus,
        )
        self.model_client = model_client
        self.network_supervisor = network_supervisor

    async def dispatch(
        self,
        intent: CommandIntent,
        is_headless: bool = False,
    ) -> CommandResult:
        """
        Execute command intent through canonical registry and handler pipeline.
        """
        start_time = time.monotonic()
        name = intent.name.lower().lstrip("/")

        # 1. Publish command received event
        if self.event_bus:
            self.event_bus.publish(
                HermesEvent(
                    event_type=EventType.COMMAND_RECEIVED,
                    session_id=intent.session_id,
                    mission_id=intent.mission_id,
                    payload={
                        "command_id": intent.command_id,
                        "name": name,
                        "origin": intent.origin.value,
                    },
                )
            )

        # 2. Shell Escape execution (!)
        if name == "shell":
            res = await self.shell_executor.execute_command(
                intent=intent,
                is_headless=is_headless or (intent.origin == CommandOrigin.USER_HEADLESS),
            )
            await self._publish_completion_event(intent, res)
            return res

        # 3. Help command fast-path
        if name in ("help", "?"):
            target_cmd = intent.args[0] if intent.args else None
            help_text = self.registry.get_help_text(target_cmd)
            elapsed = time.monotonic() - start_time
            res = CommandResult.success(
                intent=intent,
                message=help_text,
                data={"target": target_cmd},
                duration_seconds=elapsed,
            )
            await self._publish_completion_event(intent, res)
            return res

        # 4. Resolve definition
        definition = self.registry.get_definition(name)
        if not definition:
            # Check Prompt 8 skill registry fallback
            skill_result = await self._try_skill_fallback(intent)
            if skill_result:
                await self._publish_completion_event(intent, skill_result)
                return skill_result

            # Unknown command: Never forward to LLM
            elapsed = time.monotonic() - start_time
            res = CommandResult.failure(
                intent=intent,
                message=f"Unknown command: /{name}\nUse /help to view available commands.",
                error_code=CommandErrorCode.UNKNOWN_COMMAND,
                exit_code=2,
                duration_seconds=elapsed,
            )
            await self._publish_completion_event(intent, res)
            return res

        # 5. Execution mode / capability validation
        if intent.origin == CommandOrigin.USER_HEADLESS and not definition.headless_supported:
            elapsed = time.monotonic() - start_time
            res = CommandResult.failure(
                intent=intent,
                message=f"Command /{definition.name} is not supported in headless mode.",
                error_code=CommandErrorCode.UNAVAILABLE_MODE,
                exit_code=2,
                duration_seconds=elapsed,
            )
            await self._publish_completion_event(intent, res)
            return res

        if intent.origin == CommandOrigin.REPLAY and not definition.replay_supported:
            elapsed = time.monotonic() - start_time
            res = CommandResult.failure(
                intent=intent,
                message=f"Command /{definition.name} cannot be executed during historical replay.",
                error_code=CommandErrorCode.UNAVAILABLE_MODE,
                exit_code=2,
                duration_seconds=elapsed,
            )
            await self._publish_completion_event(intent, res)
            return res

        # 6. Execute Canonical Handler
        canon = definition.name
        try:
            if canon == "status":
                res = await handle_status(
                    intent=intent,
                    state_store=self.state_store,
                    workspace_root=self.workspace_root,
                )
            elif canon == "context":
                res = await handle_context(
                    intent=intent,
                    context_engine=self.context_engine,
                    state_store=self.state_store,
                )
            elif canon == "cost":
                res = await handle_cost(intent=intent)
            elif canon == "doctor":
                res = await handle_doctor(
                    intent=intent,
                    workspace_root=self.workspace_root,
                    network_supervisor=self.network_supervisor,
                )
            elif canon == "diff":
                res = await handle_diff(
                    intent=intent,
                    workspace_root=self.workspace_root,
                )
            elif canon == "tasks":
                res = await handle_tasks(
                    intent=intent,
                    state_store=self.state_store,
                )
            elif canon == "plan":
                res = await handle_plan(
                    intent=intent,
                    planning_service=self.planning_service,
                )
            elif canon == "compact":
                res = await handle_compact(
                    intent=intent,
                    context_engine=self.context_engine,
                    event_bus=self.event_bus,
                )
            elif canon == "rewind":
                res = await handle_rewind(
                    intent=intent,
                    rewind_engine=self.rewind_engine,
                    is_headless=is_headless or (intent.origin == CommandOrigin.USER_HEADLESS),
                )
            elif canon == "resume":
                res = await handle_resume(
                    intent=intent,
                    recovery_engine=self.recovery_engine,
                    session_manager=self.session_manager,
                    is_headless=is_headless or (intent.origin == CommandOrigin.USER_HEADLESS),
                )
            elif canon == "clear":
                res = await handle_clear(
                    intent=intent,
                    session_manager=self.session_manager,
                    context_engine=self.context_engine,
                    event_bus=self.event_bus,
                )
            elif canon == "goal":
                res = await handle_goal(
                    intent=intent,
                    planning_service=self.planning_service,
                    state_store=self.state_store,
                    event_bus=self.event_bus,
                )
            elif canon == "btw":
                res = await handle_btw(
                    intent=intent,
                    model_client=self.model_client,
                    context_engine=self.context_engine,
                )
            else:
                elapsed = time.monotonic() - start_time
                res = CommandResult.failure(
                    intent=intent,
                    message=f"Handler not configured for /{canon}",
                    error_code=CommandErrorCode.EXECUTION_ERROR,
                    duration_seconds=elapsed,
                )

        except Exception as e:
            logger.exception(f"Exception executing command /{canon}: {e}")
            elapsed = time.monotonic() - start_time
            res = CommandResult.failure(
                intent=intent,
                message=f"Command execution error: {e}",
                error_code=CommandErrorCode.EXECUTION_ERROR,
                duration_seconds=elapsed,
            )

        await self._publish_completion_event(intent, res)
        return res

    async def _try_skill_fallback(self, intent: CommandIntent) -> Optional[CommandResult]:
        """Check if command matches a registered user skill from Prompt 8."""
        if hasattr(self.registry, "_skill_provider") and self.registry._skill_provider:
            provider = self.registry._skill_provider
            try:
                if hasattr(provider, "get_skill"):
                    skill = provider.get_skill(intent.name)
                    if skill:
                        return CommandResult.success(
                            intent=intent,
                            message=f"Skill '{skill.name}' invoked:\n{skill.description}",
                            data={"skill_name": skill.name},
                            execution_class=CommandExecutionClass.CONTROL_OPERATION,
                        )
            except Exception:
                pass
        return None

    async def _publish_completion_event(self, intent: CommandIntent, result: CommandResult) -> None:
        if not self.event_bus:
            return

        evt_type = (
            EventType.COMMAND_COMPLETED
            if result.status == CommandStatus.SUCCESS
            else (
                EventType.COMMAND_DENIED
                if result.status == CommandStatus.DENIED
                else EventType.COMMAND_FAILED
            )
        )
        try:
            self.event_bus.publish(
                HermesEvent(
                    event_type=evt_type,
                    session_id=intent.session_id,
                    mission_id=intent.mission_id,
                    payload={
                        "command_id": intent.command_id,
                        "name": intent.name,
                        "status": result.status.value,
                        "exit_code": result.exit_code,
                        "duration_seconds": result.duration_seconds,
                        "llm_called": result.llm_called,
                    },
                )
            )
        except Exception:
            pass
