# kairos/mission_driver.py
# MissionDriver — the KAIROS component that drives missions through MissionRunner.
#
# In HERMES v4.0, KAIROS has two distinct responsibilities:
#   1. Background monitor: stuck detection, runaway detection, memory consolidation (existing)
#   2. Mission driver: takes user requests, creates Missions, drives them to completion (NEW)
#
# The MissionDriver is NOT a daemon — it is called by HermesApp when a user submits
# a prompt. It bridges the gap between the TUI and the mission execution engine.
#
# Design rule: MissionDriver holds all the stateful components (workspace, runner, planner)
# so HermesApp stays lightweight and focused on UI concerns only.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from loguru import logger

from core.mission_planner import MissionPlanner, Mission
from core.mission_runner import MissionRunner, MissionEvent, MissionResult
from core.workspace import workspace_manager as global_workspace
from core.context_builder import ContextBuilder


class MissionDriver:
    """
    The orchestrating component that connects HermesApp to MissionRunner.

    Responsibilities:
    1. Initialise workspace on first run or when path changes
    2. Create MissionPlanner and MissionRunner instances
    3. Drive the mission execution loop
    4. Emit events to the TUI via asyncio.Queue
    5. Handle abort signals from the TUI

    Usage in HermesApp:
        driver = MissionDriver(orchestrator)
        await driver.initialise_workspace("/path/to/project")
        result = await driver.run_mission("Build Flask API and write tests")
    """

    def __init__(self, orchestrator: object) -> None:
        self.orchestrator = orchestrator
        self._planner = MissionPlanner()
        self._current_mission: Optional[Mission] = None
        self._current_runner: Optional[MissionRunner] = None
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._abort_event: Optional[asyncio.Event] = None
        self._workspace_initialised: bool = False

    # ── Workspace lifecycle ───────────────────────────────────────────────────

    async def initialise_workspace(self, path: Optional[str] = None) -> dict:
        """
        Initialise or switch the active workspace.
        If path is None, uses the current working directory.
        Returns workspace summary dict.
        """
        try:
            if path:
                global_workspace.lock(path)
            elif not global_workspace.is_locked:
                global_workspace.lock_to_cwd()

            self._workspace_initialised = True
            summary = global_workspace.get_workspace_summary()

            logger.info(
                f"MissionDriver: workspace initialised | "
                f"root={summary.get('root')} | "
                f"framework={summary.get('framework')} | "
                f"files={summary.get('total_files')}"
            )

            await self._emit(MissionEvent(
                event_type="workspace_ready",
                payload=summary,
            ))

            return summary

        except Exception as e:
            logger.error(f"MissionDriver: workspace init failed: {e}")
            return {"locked": False, "error": str(e)}

    # ── Mission execution ─────────────────────────────────────────────────────

    async def run_mission(self, user_prompt: str) -> MissionResult:
        """
        Main entry point: plan and execute a complete mission.

        Args:
            user_prompt: The raw user request (can be multi-objective)

        Returns:
            MissionResult with execution summary
        """
        # Ensure workspace is initialised
        if not self._workspace_initialised:
            await self.initialise_workspace()

        # Create fresh abort event for this mission
        self._abort_event = asyncio.Event()
        self._event_queue = asyncio.Queue(maxsize=500)

        # Plan the mission
        logger.info(f"MissionDriver: planning mission from prompt ({len(user_prompt)} chars)")
        mission = self._planner.plan(
            user_prompt,
            workspace_root=global_workspace.root_str,
        )
        self._current_mission = mission

        # Emit plan event
        await self._emit(MissionEvent(
            event_type="mission_planned",
            payload={
                "mission_id": mission.mission_id,
                "task_count": len(mission.tasks),
                "tasks": [t.to_dict() for t in mission.tasks],
                "workspace": global_workspace.get_workspace_summary(),
            }
        ))

        # Create MissionRunner with shared event queue and abort event
        self._current_runner = MissionRunner(
            orchestrator=self.orchestrator,
            workspace_manager=global_workspace,
            event_queue=self._event_queue,
            abort_event=self._abort_event,
        )

        # Run the mission
        result = await self._current_runner.run(mission)

        # Refresh workspace index after mission completes
        try:
            global_workspace.refresh_index()
        except Exception:
            pass

        return result

    def abort_current_mission(self) -> None:
        """Signal the current mission to stop at the next checkpoint."""
        if self._current_runner is not None and self._abort_event is not None:
            self._current_runner.abort()
            logger.info("MissionDriver: abort signal sent")

    # ── Event system ──────────────────────────────────────────────────────────

    def get_event_queue(self) -> asyncio.Queue:
        """Return the event queue for the TUI to consume."""
        return self._event_queue

    async def _emit(self, event: MissionEvent) -> None:
        try:
            await asyncio.wait_for(self._event_queue.put(event), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    # ── State access ───────────────────────────────────────────────────

    @property
    def current_mission(self) -> Optional[Mission]:
        return self._current_mission

    @property
    def workspace_summary(self) -> dict:
        return global_workspace.get_workspace_summary()

    def get_mission_status_lines(self) -> list[str]:
        if self._current_mission is None:
            return []
        return self._current_mission.get_status_lines()
