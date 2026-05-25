# kairos/daemon.py
# The HERMES KAIROS background daemon.
# KAIROS runs as an asyncio.Task in the same process as the main application.
# It loops every 60 seconds and performs monitoring and maintenance operations.
# It does NOT spawn sub-agents. It does NOT require additional VRAM.
# It only calls an LLM during memory consolidation (Triple-Gate guarded).
#
# Triple-Gate logic — ALL THREE must pass before consolidation runs:
#   Gate 1 (Time):    60+ minutes since last consolidation
#   Gate 2 (Session): 3+ tasks COMPLETED since last consolidation
#   Gate 3 (Lock):    hermes_consolidation.lock file does not exist
#
# KAIROS responsibilities:
#   1. Detect and mark STUCK tasks (running > 15 minutes)
#   2. Retry FAILED tasks that have remaining retries
#   3. Run memory consolidation when Triple-Gate passes
#   4. Track API costs against the hard cap
#   5. Log a status summary every loop iteration

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from loguru import logger

from kairos.db import init_db, get_total_api_cost, DB_PATH
from kairos.task_queue import (
    get_stuck_tasks,
    get_failed_retriable_tasks,
    get_running_tasks,
    mark_stuck,
    requeue_for_retry,
    get_kairos_state,
    reset_kairos_counter,
    get_pending_tasks,
)

if TYPE_CHECKING:
    from models.ollama_client import OllamaClient

LOOP_INTERVAL_SECONDS: int = 60           # How often KAIROS wakes up
STUCK_THRESHOLD_MINUTES: int = 15         # Running task time limit
CONSOLIDATION_MIN_MINUTES: int = 60       # Minimum time between consolidations
CONSOLIDATION_MIN_TASKS: int = 3          # Minimum completed tasks before consolidation
LOCK_FILE_PATH: Path = Path("data/hermes_consolidation.lock")
API_COST_CAP_USD: float = 25.0
API_COST_ALERT_USD: float = 15.0


class KairosDaemon:
    """The HERMES KAIROS background daemon."""

    def __init__(
        self,
        ollama_client: Optional["OllamaClient"] = None,
        db_path: Path = DB_PATH,
    ) -> None:
        self.ollama_client = ollama_client
        self.db_path = db_path
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.loop_count = 0
        self.stuck_tasks_detected = 0
        self.tasks_retried = 0
        self.consolidations_run = 0
        logger.info("KAIROS daemon initialised")

    async def start(self) -> None:
        """Start the KAIROS daemon as a background asyncio Task.

        Call this once at application startup.
        """
        if self.is_running:
            logger.warning("KAIROS: already running — ignoring start() call")
            return
        init_db(db_path=self.db_path)
        self.is_running = True
        self._task = asyncio.create_task(self._main_loop(), name="kairos-daemon")
        logger.info("KAIROS daemon started")

    async def stop(self) -> None:
        """Stop the KAIROS daemon gracefully."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        LOCK_FILE_PATH.unlink(missing_ok=True)  # Clean up lock if we hold it
        logger.info(
            f"KAIROS daemon stopped | loops={self.loop_count} | "
            f"stuck_detected={self.stuck_tasks_detected} | retried={self.tasks_retried} | "
            f"consolidations={self.consolidations_run}"
        )

    async def _main_loop(self) -> None:
        """Main daemon loop — runs _run_one_cycle every LOOP_INTERVAL_SECONDS."""
        logger.info("KAIROS main loop started")
        while self.is_running:
            try:
                await self._run_one_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"KAIROS loop error (continuing): {type(e).__name__}: {e}")

            try:
                await asyncio.sleep(LOOP_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _run_one_cycle(self) -> None:
        """Run one complete KAIROS monitoring cycle.

        Called every LOOP_INTERVAL_SECONDS.
        """
        self.loop_count += 1
        logger.debug(f"KAIROS cycle #{self.loop_count}")

        # ── 1. Detect and mark STUCK tasks ───────────────────────────────────
        await self._handle_stuck_tasks()

        # ── 2. Retry failed tasks ─────────────────────────────────────────────
        await self._handle_failed_tasks()

        # ── 3. Check API cost cap ─────────────────────────────────────────────
        await self._check_cost_cap()

        # ── 4. Triple-Gate memory consolidation ──────────────────────────────
        await self._maybe_consolidate_memory()

        # ── 5. Log status summary ─────────────────────────────────────────────
        self._log_status_summary()

    async def _handle_stuck_tasks(self) -> None:
        """Detect RUNNING tasks that have exceeded the stuck threshold and mark them STUCK."""
        stuck = get_stuck_tasks(db_path=self.db_path)
        for task in stuck:
            logger.warning(
                f"KAIROS: marking task {task.id} as STUCK | "
                f"title={task.title[:50]!r} | "
                f"running since={task.started_at}"
            )
            mark_stuck(
                task.id,
                reason=f"KAIROS: task exceeded {STUCK_THRESHOLD_MINUTES}-minute limit",
                db_path=self.db_path,
            )
            self.stuck_tasks_detected += 1

    async def _handle_failed_tasks(self) -> None:
        """Requeue FAILED tasks that still have remaining retries."""
        retriable = get_failed_retriable_tasks(db_path=self.db_path)
        for task in retriable:
            success = requeue_for_retry(task.id, db_path=self.db_path)
            if success:
                self.tasks_retried += 1
                logger.info(
                    f"KAIROS: requeued task {task.id} for retry "
                    f"#{task.retry_count + 1}/{task.max_retries} | "
                    f"title={task.title[:40]!r}"
                )

    async def _check_cost_cap(self) -> None:
        """Check total API costs and log warnings/errors if approaching or exceeding cap."""
        total_cost = get_total_api_cost(db_path=self.db_path)
        if total_cost >= API_COST_CAP_USD:
            logger.error(
                f"KAIROS: API cost cap REACHED (${total_cost:.4f} / ${API_COST_CAP_USD}). "
                f"Tier 3 calls will be blocked."
            )
        elif total_cost >= API_COST_ALERT_USD:
            logger.warning(
                f"KAIROS: API cost alert (${total_cost:.4f} / ${API_COST_ALERT_USD}). "
                f"Approaching cap — review Tier 3 escalation frequency."
            )

    async def _maybe_consolidate_memory(self) -> None:
        """Check Triple-Gate logic. If all three gates pass, run memory consolidation."""
        # Gate 3: Lock file check
        if LOCK_FILE_PATH.exists():
            logger.debug("KAIROS: consolidation lock held by another instance — skipping")
            return

        state = get_kairos_state(db_path=self.db_path)

        # Gate 2: Session gate — enough completed tasks?
        tasks_since = state.get("tasks_since_consolidation", 0)
        if tasks_since < CONSOLIDATION_MIN_TASKS:
            logger.debug(f"KAIROS: session gate not met ({tasks_since}/{CONSOLIDATION_MIN_TASKS} tasks)")
            return

        # Gate 1: Time gate — enough time elapsed?
        last_consolidation = state.get("last_consolidation_at")
        if last_consolidation:
            try:
                last_dt = datetime.fromisoformat(last_consolidation)
                elapsed_minutes = (datetime.now() - last_dt).total_seconds() / 60
                if elapsed_minutes < CONSOLIDATION_MIN_MINUTES:
                    logger.debug(
                        f"KAIROS: time gate not met ({elapsed_minutes:.1f}/{CONSOLIDATION_MIN_MINUTES} min)"
                    )
                    return
            except (ValueError, TypeError):
                pass  # If we can't parse the timestamp, proceed with consolidation

        # All gates passed — acquire lock and consolidate
        logger.info(
            f"KAIROS: Triple-Gate passed | "
            f"tasks_since={tasks_since} | "
            f"last_consolidation={last_consolidation}"
        )
        await self._run_consolidation()

    async def _run_consolidation(self) -> None:
        """Acquire lock, run memory consolidation, release lock."""
        try:
            # Acquire lock
            LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            LOCK_FILE_PATH.write_text(f"locked by KAIROS at {datetime.now().isoformat()}")
            logger.info("KAIROS: consolidation lock acquired — running memory consolidation")

            # Run consolidation
            from memory.consolidator import consolidate_memory

            stats = consolidate_memory()

            # Record in database
            reset_kairos_counter(db_path=self.db_path)
            self.consolidations_run += 1

            logger.info(
                f"KAIROS: consolidation complete | "
                f"stats={stats} | "
                f"total_consolidations={self.consolidations_run}"
            )

        except Exception as e:
            logger.error(f"KAIROS: consolidation failed: {type(e).__name__}: {e}")
        finally:
            # Always release the lock
            LOCK_FILE_PATH.unlink(missing_ok=True)
            logger.debug("KAIROS: consolidation lock released")

    def _log_status_summary(self) -> None:
        """Log a summary of the current KAIROS state."""
        pending = len(get_pending_tasks(db_path=self.db_path))
        running = len(get_running_tasks(db_path=self.db_path))
        total_cost = get_total_api_cost(db_path=self.db_path)
        logger.debug(
            f"KAIROS status | loop={self.loop_count} | "
            f"pending={pending} | running={running} | "
            f"cost=${total_cost:.4f} | "
            f"consolidations={self.consolidations_run}"
        )

    def get_stats(self) -> dict:
        """Return a dictionary of KAIROS daemon statistics."""
        return {
            "is_running": self.is_running,
            "loop_count": self.loop_count,
            "stuck_tasks_detected": self.stuck_tasks_detected,
            "tasks_retried": self.tasks_retried,
            "consolidations_run": self.consolidations_run,
            "total_api_cost": get_total_api_cost(db_path=self.db_path),
            "pending_tasks": len(get_pending_tasks(db_path=self.db_path)),
        }
