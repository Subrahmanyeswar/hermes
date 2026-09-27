# ui/runtime/observer.py
"""
Read-Only TUI Runtime Observer.

STRICT INVARIANTS:
1. TUI OBSERVES; TUI DOES NOT DECIDE.
2. Observer failure or disconnect NEVER terminates backend execution.
3. EventBus subscriber isolation protects the runtime.
4. Reconnection reconstructs state from authoritative StateStore without replaying side-effects.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent
from core.runtime_state.models import HermesRuntimeState
from ui.rendering.render_scheduler import RenderScheduler
from ui.runtime.event_projection import EventProjector
from ui.state.selectors import build_root_view_model
from ui.viewmodels.checkpoint import CheckpointItemViewModel
from ui.viewmodels.root import HermesViewModel


class TuiRuntimeObserver:
    """Subscribes to runtime events and drives the RenderScheduler."""

    def __init__(
        self,
        event_bus: EventBus,
        state_provider: Callable[[], HermesRuntimeState],
        scheduler: RenderScheduler,
        checkpoints_provider: Optional[Callable[[], List[CheckpointItemViewModel]]] = None,
    ):
        self.event_bus = event_bus
        self.state_provider = state_provider
        self.scheduler = scheduler
        self.checkpoints_provider = checkpoints_provider

        self.projector = EventProjector()
        self.is_attached: bool = False
        self._revision: int = 0
        self._subscription_id: Optional[str] = None

    def attach(self) -> None:
        """Connect observer to EventBus and trigger full initial render."""
        if self.is_attached:
            return

        self.is_attached = True
        # Subscribe to EventBus
        try:
            self._subscription_id = self.event_bus.subscribe(
                "*",
                self.on_event,
                subscriber_id="tui_runtime_observer",
            )
        except Exception:
            # Fallback if subscribe signature differs
            pass

        # Reconstruct initial view model from authoritative state and do full repaint
        self._render_current_state(urgent=True, force_full_repaint=True)

    def detach(self) -> None:
        """Safely disconnect observer without affecting running mission."""
        if not self.is_attached:
            return

        self.is_attached = False
        if self._subscription_id:
            try:
                self.event_bus.unsubscribe(self._subscription_id)
            except Exception:
                pass
            self._subscription_id = None

    def on_event(self, event: HermesEvent) -> None:
        """Receive live event from EventBus with complete exception isolation."""
        if not self.is_attached:
            return

        try:
            # 1. Update projection
            changed = self.projector.process_event(event)

            # 2. Urgent events trigger immediate render
            et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            urgent = et in (
                "MISSION_COMPLETED",
                "MISSION_FAILED",
                "SECURITY_DENIED",
                "PERMISSION_REQUESTED",
                "RECOVERY_COMPLETED",
            )

            # 3. Schedule render
            self._render_current_state(urgent=urgent)

        except Exception as e:
            # Strict isolation: Never propagate UI observer failure into EventBus
            pass

    def on_user_prompt(self, text: str) -> None:
        """Record user prompt submission in chat history."""
        self.projector.add_user_message(text)
        self._render_current_state(urgent=True)

    def _render_current_state(
        self,
        urgent: bool = False,
        force_full_repaint: bool = False,
    ) -> None:
        """Sample current authoritative state, build ViewModel, and request render."""
        self._revision += 1
        state = self.state_provider()

        checkpoints = []
        if self.checkpoints_provider:
            try:
                checkpoints = self.checkpoints_provider()
            except Exception:
                checkpoints = []

        vm = build_root_view_model(
            state=state,
            revision=self._revision,
            chat_messages=self.projector.messages,
            is_streaming=self.projector.is_streaming,
            streaming_content=self.projector.streaming_content,
            checkpoints=checkpoints,
            active_notifications=self.projector.notifications,
            is_fallback_active=self.scheduler.supervisor.circuit_state.value != "PRIMARY",
        )

        self.scheduler.request_render(vm, urgent=urgent)
        if force_full_repaint:
            self.scheduler.flush_pending(force_full_repaint=True)
