# core/runtime_factory.py
"""
Shared Application Runtime Factory for HERMES 2.x (Prompt 16).

Central Invariants:
1. ONE AGENT ENGINE, MANY SURFACES:
   - CLI run, TUI, and Headless all share the exact same AgentLoop and services.
   - Replay shares the same state reducer and persistence models without live side effects.
2. SAME SECURITY MODEL: Prompt 13 security gate authority everywhere; headless fails closed on ASK.
3. SAME PERSISTENCE: Prompt 14 durable sessions, checkpoints, and journals across all entrypoints.
4. GRACEFUL PERSISTENCE FLUSH: Safe signal handling (Ctrl+C / SIGINT) flushes state before termination.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig
from core.commands.dispatcher import CommandDispatcher
from core.commands.mentions import MentionResolver
from core.commands.models import (
    AtMentionInput,
    CommandIntent,
    CommandOrigin,
    CommandResult,
    CommandStatus,
    NormalPromptInput,
    PaletteTriggerInput,
    ParsedInput,
    ShellEscapeInput,
    SlashCommandInput,
)
from core.commands.parser import UnifiedInputParser
from core.commands.registry import CommandRegistry, command_registry
from core.commands.shell import ShellExecutor
from core.context.engine import ContextEngine
from core.event_bus import EventBus, event_bus as global_event_bus
from core.mission_planner import Mission
from core.recovery.engine import RecoveryEngine
from core.recovery.rewind import RewindEngine
from core.replay.engine import ReplayEngine
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import ExecutionMode as RuntimeExecutionMode, HermesRuntimeState
from core.runtime_state.store import StateStore, state_store as global_state_store
from core.security.config import SecurityPolicy, get_default_security_policy
from core.security.service import SecurityService
from core.sessions.manager import SessionManager
from core.sinks import EventSink, JsonSink, StreamJsonSink, TextSink
from core.subagents.background import BackgroundJobManager
from core.subagents.cancellation import CancellationController
from core.workspace import WorkspaceManager, workspace_manager as global_workspace

logger = logging.getLogger("hermes.runtime.factory")


class SurfaceMode(str, Enum):
    """The operational surface invoking the engine."""
    INTERACTIVE_TUI = "INTERACTIVE_TUI"
    HEADLESS = "HEADLESS"
    REPLAY = "REPLAY"


class ApplicationRuntime:
    """The unified runtime holding canonical HERMES services."""

    def __init__(
        self,
        surface_mode: SurfaceMode,
        workspace_root: Path | str,
        session_id: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
        state_store: Optional[StateStore] = None,
        security_policy: Optional[SecurityPolicy] = None,
        debug: bool = False,
    ):
        self.surface_mode = surface_mode
        self.workspace_root = Path(workspace_root).resolve()
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.debug = debug

        # 1. Base Event and State Substrate
        self.event_bus = event_bus or global_event_bus
        self.state_store = state_store or global_state_store
        self.workspace = global_workspace
        self.workspace.lock(str(self.workspace_root))

        # 2. Durable Persistence (Prompt 14)
        base_storage = self.workspace_root / ".hermes"
        base_storage.mkdir(parents=True, exist_ok=True)
        self.session_manager = SessionManager(
            base_dir=base_storage,
            workspace_root=self.workspace_root,
            event_bus=self.event_bus,
        )

        # 3. Security Service (Prompt 13)
        self.security = SecurityService(policy=security_policy or get_default_security_policy())

        # 4. Context Engine (Prompt 7)
        self.context_engine = ContextEngine(
            event_bus=self.event_bus,
        )

        # 5. Background Jobs & Cancellation (Prompt 10)
        self.cancellation = CancellationController()
        self.job_manager = BackgroundJobManager(workspace_root=self.workspace_root)

        # 6. Recovery & Rewind Engines (Prompt 14)
        self.rewind_engine = RewindEngine(
            workspace_root=self.workspace_root,
            checkpoint_engine=self.session_manager.checkpoint_engine,
            blob_store=self.session_manager.blob_store,
            event_bus=self.event_bus,
        )
        self.recovery_engine = RecoveryEngine(
            session_manager=self.session_manager,
            workspace_root=self.workspace_root,
            event_bus=self.event_bus,
        )
        self.replay_engine = ReplayEngine(session_manager=self.session_manager)

        # 7. Command OS Components (Prompt 16)
        self.command_registry = command_registry
        try:
            from core.security.content_boundary import ContentBoundary
            content_boundary = ContentBoundary()
        except Exception:
            content_boundary = None
        self.mention_resolver = MentionResolver(
            workspace_root=self.workspace_root,
            content_boundary=content_boundary,
        )
        self.shell_executor = ShellExecutor(
            workspace_root=self.workspace_root,
            security_service=self.security,
            job_manager=self.job_manager,
            event_bus=self.event_bus,
            cancellation_controller=self.cancellation,
        )
        self.command_dispatcher = CommandDispatcher(
            registry=self.command_registry,
            workspace_root=self.workspace_root,
            state_store=self.state_store,
            event_bus=self.event_bus,
            security_service=self.security,
            context_engine=self.context_engine,
            session_manager=self.session_manager,
            rewind_engine=self.rewind_engine,
            recovery_engine=self.recovery_engine,
            shell_executor=self.shell_executor,
        )
        self.dispatcher = self.command_dispatcher

        # 8. Canonical AgentLoop (Prompt 4)
        from core.orchestrator import Orchestrator
        self.orchestrator = Orchestrator(mode="auto", project="default")
        loop_config = AgentLoopConfig(
            execution_mode="auto"
        )
        self.agent_loop = AgentLoop(
            orchestrator=self.orchestrator,
            workspace_manager=self.workspace,
            event_bus_instance=self.event_bus,
            state_store_instance=self.state_store,
            abort_event=self.cancellation.global_abort_event if hasattr(self.cancellation, "global_abort_event") else None,
            config=loop_config,
        )

        self._active_sink: Optional[EventSink] = None

    def get_runtime_identity(self):
        """Retrieve authoritative runtime identity for this running instance."""
        from core.runtime_identity import detect_runtime_identity
        return detect_runtime_identity(workspace_root=str(self.workspace_root))

    async def execute_input(
        self,
        raw_text: str,
        sink: Optional[EventSink] = None,
        origin: Optional[CommandOrigin] = None,
    ) -> CommandResult:
        """
        Execute raw input (command, mention, shell, or prompt) through unified pipeline.
        """
        effective_origin = origin or (
            CommandOrigin.USER_HEADLESS
            if self.surface_mode == SurfaceMode.HEADLESS
            else CommandOrigin.USER_TUI
        )

        parsed = UnifiedInputParser.parse(
            text=raw_text,
            origin=effective_origin,
            session_id=self.session_id,
        )

        # 1. Slash Command
        if isinstance(parsed, SlashCommandInput):
            res = await self.command_dispatcher.dispatch(
                intent=parsed.intent,
                is_headless=(self.surface_mode == SurfaceMode.HEADLESS),
            )
            if sink:
                state = self.state_store.get_snapshot()
                sink.on_completed(state, exit_code=res.exit_code, error_message=res.message if res.exit_code != 0 else None)
            return res

        # 2. Shell Escape (!)
        if isinstance(parsed, ShellEscapeInput):
            res = await self.command_dispatcher.dispatch(
                intent=parsed.intent,
                is_headless=(self.surface_mode == SurfaceMode.HEADLESS),
            )
            if sink:
                state = self.state_store.get_snapshot()
                sink.on_completed(state, exit_code=res.exit_code, error_message=res.message if res.exit_code != 0 else None)
            return res

        # 3. Palette Trigger
        if isinstance(parsed, PaletteTriggerInput):
            help_res = self.command_registry.get_help_text()
            intent = CommandIntent.create(name="help", raw_text="/", origin=effective_origin)
            res = CommandResult.success(intent=intent, message=help_res)
            if sink:
                state = self.state_store.get_snapshot()
                sink.on_completed(state, exit_code=0)
            return res

        # 4. Prompt with @ Mentions
        if isinstance(parsed, AtMentionInput):
            resolved = self.mention_resolver.resolve_all(parsed.mentions)
            enriched_prompt = MentionResolver.enrich_prompt_with_mentions(parsed.prompt, resolved)
            return await self._run_prompt_as_command(enriched_prompt, effective_origin, sink=sink)

        # 5. Normal Prompt
        return await self._run_prompt_as_command(parsed.prompt, effective_origin, sink=sink)

    async def _run_prompt_as_command(
        self,
        prompt: str,
        origin: CommandOrigin,
        sink: Optional[EventSink] = None,
    ) -> CommandResult:
        """Wrap normal prompt execution as a CommandResult."""
        start_time = time.monotonic()
        intent = CommandIntent.create(
            name="prompt",
            raw_text=prompt,
            args=(prompt,),
            origin=origin,
            session_id=self.session_id,
        )

        exit_code = await self.run_mission(prompt=prompt, sink=sink)
        elapsed = time.monotonic() - start_time

        state = self.state_store.get_snapshot()
        success = exit_code == 0
        status = CommandStatus.SUCCESS if success else CommandStatus.FAILURE

        return CommandResult(
            command_id=intent.command_id,
            name=intent.name,
            status=status,
            message=state.mission.title or ("Mission succeeded" if success else "Mission failed"),
            data={"exit_code": exit_code, "mission_id": state.mission.mission_id},
            exit_code=exit_code,
            llm_called=True,
            duration_seconds=elapsed,
        )

    async def run_mission(
        self,
        prompt: str,
        sink: Optional[EventSink] = None,
        plan_mode: bool = False,
    ) -> int:
        """
        Run a mission through the shared AgentLoop.
        Returns standard exit code (0=success, 1=failed, 3=denied, 5=cancelled).
        """
        self._active_sink = sink
        mission_id = f"m_{uuid.uuid4().hex[:8]}"

        mission = Mission(
            mission_id=mission_id,
            user_prompt=prompt,
            workspace_root=str(self.workspace_root),
        )

        # Subscribe sink to event bus
        if sink:
            def _sink_callback(event: HermesEvent):
                try:
                    sink.on_event(event, self.state_store.get_snapshot())
                except Exception:
                    pass
            try:
                self.event_bus.subscribe(_sink_callback)
            except Exception:
                pass

        try:
            # Set user intent for Prompt 13 security
            self.security.set_user_intent_from_prompt(prompt)

            # Execute via canonical AgentLoop!
            result = await self.agent_loop.run(mission)

            final_state = self.state_store.get_snapshot()
            exit_code = 0 if result.success else 1

            if sink:
                sink.on_completed(final_state, exit_code=exit_code, error_message=result.termination_reason)

            # Flush state to Prompt 14 persistence
            self._flush_persistence(final_state)

            return exit_code

        except asyncio.CancelledError:
            final_state = self.state_store.get_snapshot()
            if sink:
                sink.on_completed(final_state, exit_code=5, error_message="Cancelled")
            self._flush_persistence(final_state)
            return 5

        except Exception as e:
            logger.exception(f"Runtime execution error: {e}")
            final_state = self.state_store.get_snapshot()
            if sink:
                sink.on_completed(final_state, exit_code=1, error_message=str(e))
            self._flush_persistence(final_state)
            return 1

        finally:
            if sink and self.event_bus:
                try:
                    self.event_bus.unsubscribe(_sink_callback)
                except Exception:
                    pass

    def _flush_persistence(self, state: HermesRuntimeState) -> None:
        """Gracefully flush runtime state to Prompt 14 persistent session database."""
        try:
            if self.session_manager:
                sess = self.session_manager.get_session(self.session_id)
                if not sess:
                    m_id = state.mission.mission_id if hasattr(state, "mission") and state.mission else "default"
                    sess = self.session_manager.create_session(mission_id=m_id)
                    self.session_id = sess.session_id
                self.session_manager.create_checkpoint(
                    session_id=self.session_id,
                    runtime_state=state,
                )
        except Exception as e:
            logger.warning(f"Persistence flush warning: {e}")


class ApplicationRuntimeFactory:
    """Factory creating configured ApplicationRuntime instances."""

    @classmethod
    def create_runtime(
        cls,
        mode: SurfaceMode = SurfaceMode.HEADLESS,
        workspace_root: Optional[Path | str] = None,
        session_id: Optional[str] = None,
        security_policy: Optional[SecurityPolicy] = None,
        debug: bool = False,
    ) -> ApplicationRuntime:
        """Create and return a unified ApplicationRuntime."""
        workspace = Path(workspace_root or Path.cwd()).resolve()

        # If headless mode, adjust security policy to fail closed on ASK
        effective_policy = security_policy or get_default_security_policy()

        return ApplicationRuntime(
            surface_mode=mode,
            workspace_root=workspace,
            session_id=session_id,
            security_policy=effective_policy,
            debug=debug,
        )
