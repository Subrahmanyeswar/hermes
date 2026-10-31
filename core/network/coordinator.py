# core/network/coordinator.py
"""
HERMES Phase 7: Network Recovery Coordinator.
Coordinates:
1. Discovery of eligible waiting missions after connectivity or provider recovery.
2. Invariant verification (checkpoint integrity, original workspace presence, disk-vs-ledger).
3. Assignment of explicit continuation run identities (run_{attempt}_{uuid}).
4. Deterministic resumption from the first safe unfinished task.
5. Ineligible mission fencing (user-cancelled, completed, corrupted, auth/billing errors).
6. Deduplication and anti-flapping protections.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from core.network.connectivity import (
    ConnectivityMonitor,
    ConnectivityStatus,
    shared_connectivity_monitor,
)
from core.persistence.database import SQLiteDatabase
from core.persistence.models import OperationStatus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import MissionStatus, WaitReason
from core.transport.circuit_breaker import CircuitState, circuit_breaker_registry


class NetworkRecoveryCoordinator:
    """
    Supervises automatic recovery of waiting missions when network/provider recovers.
    Ensures safe continuation from the first unfinished task with zero duplicate tool executions.
    """

    def __init__(
        self,
        monitor: Optional[ConnectivityMonitor] = None,
        db: Optional[SQLiteDatabase] = None,
        runtime_adapter: Optional[Any] = None,
        recovery_engine: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        debounce_seconds: float = 1.0,
        provider_probe_interval: float = 10.0,
    ) -> None:
        self.monitor = monitor or shared_connectivity_monitor
        self.db = db
        self.runtime_adapter = runtime_adapter
        self.recovery_engine = recovery_engine
        self.event_bus = event_bus
        self.debounce_seconds = debounce_seconds
        self.provider_probe_interval = provider_probe_interval

        self._recovering_missions: Set[str] = set()
        self._lock = asyncio.Lock()
        self._last_recovery_at: float = 0.0
        self._listener_registered: bool = False
        self._cb_listener_registered: bool = False
        self._provider_probe_task: Optional[asyncio.Task] = None
        self._running: bool = False

    def _get_db(self) -> Optional[SQLiteDatabase]:
        if self.db is not None:
            return self.db
        if self.runtime_adapter is not None and getattr(self.runtime_adapter, "event_bus", None) is not None:
            return self.runtime_adapter.event_bus.get_database()
        if self.event_bus is not None and hasattr(self.event_bus, "get_database"):
            return self.event_bus.get_database()
        return None

    def _get_recovery_engine(self, db: SQLiteDatabase) -> Any:
        if self.recovery_engine is not None:
            return self.recovery_engine
        from core.persistence.blobs import BlobStore
        from core.persistence.recovery import RecoveryEngine
        blob_store = getattr(self.event_bus, "blob_store", None)
        if blob_store is None:
            blob_store = BlobStore(Path(db.db_path).parent / "blobs")
        ws_mgr = getattr(self.runtime_adapter, "workspace", None)
        return RecoveryEngine(db=db, blob_store=blob_store, workspace_manager=ws_mgr)

    def find_eligible_waiting_missions(self) -> List[Dict[str, Any]]:
        """
        Query database for missions waiting for network or provider recovery.
        Excludes terminal, actively executing, or permanently failed missions.
        """
        db = self._get_db()
        if db is None:
            return []

        eligible = []
        try:
            with db.transaction() as cur:
                cur.execute("""
                    SELECT mission_id, status, wait_reason, run_id, attempt_number,
                           workspace_path, latest_checkpoint_id, execution_active,
                           recovery_required, metadata_json, error_json
                    FROM missions
                    WHERE (
                        (status = 'WAITING' AND wait_reason IN ('WAITING_FOR_NETWORK', 'WAITING_FOR_PROVIDER', 'WAITING_FOR_RECOVERY', 'WAITING_FOR_WORKSPACE', 'WAITING_FOR_CHECKPOINT', 'RECOVERY_BLOCKED'))
                        OR (recovery_required = 1 AND execution_active = 0)
                    )
                    AND status NOT IN ('COMPLETED', 'CANCELLED', 'ABORTED', 'FAILED')
                    AND metadata_json NOT LIKE '%"cancelled_by_user": true%';
                """)
                rows = cur.fetchall()
                for r in rows:
                    eligible.append(dict(r))
        except Exception as exc:
            logger.error(f"NetworkRecoveryCoordinator: error querying waiting missions: {exc}")

        return eligible

    def evaluate_auto_resume_eligibility(self, mission_id: str) -> Tuple[bool, str]:
        """
        Evaluate whether a specific waiting mission is strictly safe to auto-resume.
        Enforces all Phase 5 & Phase 7 invariants:
        - Must not be in flight or already recovering
        - Must not be stopped or cancelled by user
        - Must have valid workspace directory
        - Must have valid, non-corrupted checkpoint
        - Must not have blocking ledger discrepancies
        - Must not have permanent auth/billing errors
        """
        if mission_id in self._recovering_missions:
            return False, "Mission is already actively recovering."

        if self.runtime_adapter is not None:
            if mission_id in getattr(self.runtime_adapter, "_active_tasks", {}):
                task = self.runtime_adapter._active_tasks[mission_id]
                if not task.done():
                    return False, "Mission is already actively executing in runtime adapter."

        db = self._get_db()
        if db is None:
            return False, "Database unavailable."

        row = db.get_mission(mission_id)
        if not row:
            return False, f"Mission '{mission_id}' not found in database."

        status_str = row.get("status")
        if status_str in ("COMPLETED", "CANCELLED", "ABORTED"):
            return False, f"Mission '{mission_id}' is in terminal state ({status_str})."

        attempt_num = row.get("attempt_number", 1) or 1
        if attempt_num > 5:
            return False, f"Mission '{mission_id}' exceeded max auto-resume attempts ({attempt_num} > 5)."

        metadata = row.get("metadata", {}) or {}
        if metadata.get("cancelled_by_user"):
            return False, "Mission was explicitly cancelled by user."

        error_json = row.get("error") or row.get("error_json") or metadata.get("error_json") or metadata.get("error") or {}
        if isinstance(error_json, str):
            try:
                error_json = json.loads(error_json)
            except Exception:
                error_json = {}
        err_cat = error_json.get("category", "")
        permanent_categories = {
            "AUTHENTICATION_FAILURE",
            "AUTHORIZATION_RESTRICTION",
            "BILLING_FAILURE",
            "INVALID_REQUEST",
            "UNSUPPORTED_MODEL",
        }
        if err_cat in permanent_categories:
            return False, f"Mission encountered non-recoverable provider error: {err_cat}"

        engine = self._get_recovery_engine(db)

        # 1. Validate original workspace exists and is accessible
        ws_path = row.get("workspace_path")
        if not ws_path:
            return False, "Mission has no recorded workspace path."

        ws_ok, _, ws_err = engine.validate_workspace(ws_path)
        if not ws_ok:
            # Block auto-resume safely without making terminal FAILED
            self._mark_mission_blocked(db, mission_id, f"Workspace unavailable: {ws_err}", wait_reason="WAITING_FOR_WORKSPACE", workspace_path=ws_path)
            return False, f"Original workspace inaccessible: {ws_err}"

        # 2. Validate latest checkpoint
        chk_id = row.get("latest_checkpoint_id")
        if chk_id:
            chk_ok, _, chk_err = engine.validate_checkpoint(chk_id)
            if not chk_ok:
                # Check for earlier valid checkpoint fallback
                earlier_chk_id = None
                try:
                    chk_row = db.get_checkpoint(chk_id)
                    parent_id = chk_row.get("parent_checkpoint_id") if chk_row else None
                    if parent_id:
                        p_ok, _, _ = engine.validate_checkpoint(parent_id)
                        if p_ok:
                            earlier_chk_id = parent_id
                except Exception:
                    pass

                if earlier_chk_id:
                    logger.info(f"NetworkRecoveryCoordinator: Fallback to earlier valid checkpoint {earlier_chk_id}")
                else:
                    self._mark_mission_blocked(db, mission_id, f"Corrupted checkpoint: {chk_err}", wait_reason="WAITING_FOR_CHECKPOINT", workspace_path=ws_path)
                    return False, f"Checkpoint validation failed: {chk_err}"

        # 3. Formulate resume plan and check discrepancies
        try:
            plan = engine.formulate_resume_plan(mission_id)
            if not plan.can_resume:
                return False, f"Resume plan formulation rejected: {plan.reason}"
        except Exception as plan_exc:
            return False, f"Error formulating resume plan: {plan_exc}"

        return True, "Eligible for auto-recovery."

    def _mark_mission_blocked(
        self, db: SQLiteDatabase, mission_id: str, reason: str, wait_reason: str = "RECOVERY_BLOCKED", workspace_path: str = ""
    ) -> None:
        """Mark mission as blocked for recovery without irreversible terminal status transition."""
        try:
            row = db.get_mission(mission_id)
            ws_path = workspace_path or (row.get("workspace_path", "") if row else "")
            meta = (row.get("metadata", {}) or {}) if row else {}
            meta["blocked_reason"] = reason
            meta["recoverable"] = True
            db.save_mission(
                mission_id=mission_id,
                workspace_path=ws_path,
                status="WAITING",
                wait_reason=wait_reason,
                execution_active=False,
                recovery_required=True,
                metadata=meta,
            )
            if self.event_bus is not None:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.MISSION_WAITING,
                    mission_id=mission_id,
                    payload={"blocked": True, "reason": reason, "wait_reason": wait_reason}
                ))
        except Exception as exc:
            logger.warning(f"NetworkRecoveryCoordinator: error marking mission {mission_id} blocked: {exc}")

    def _mark_mission_failed(self, db: SQLiteDatabase, mission_id: str, reason: str, workspace_path: str = "") -> None:
        """Mark mission as permanently failed when unrecoverable error occurs."""
        try:
            row = db.get_mission(mission_id)
            ws_path = workspace_path or (row.get("workspace_path", "") if row else "")
            db.save_mission(
                mission_id=mission_id,
                workspace_path=ws_path,
                status="FAILED",
                wait_reason="FAILED",
                execution_active=False,
                recovery_required=False,
            )
            if self.event_bus is not None:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.MISSION_FAILED,
                    mission_id=mission_id,
                    payload={"error": reason, "auto_recovery": False}
                ))
        except Exception as exc:
            logger.warning(f"NetworkRecoveryCoordinator: error marking mission {mission_id} failed: {exc}")

    async def auto_resume_mission(self, mission_id: str) -> Optional[str]:
        """
        Safely auto-resume an eligible waiting mission.
        Returns the new continuation run identity (e.g. run_{attempt}_{uuid}).
        """
        can_resume, reason = self.evaluate_auto_resume_eligibility(mission_id)
        if not can_resume:
            logger.warning(f"NetworkRecoveryCoordinator: auto-resume skipped for {mission_id}: {reason}")
            return None

        self._recovering_missions.add(mission_id)
        try:
            # Re-read database to guard against concurrent user Stop / cancellation
            db = self._get_db()
            if db:
                fresh_row = db.get_mission(mission_id)
                if fresh_row:
                    if fresh_row.get("status") in ("CANCELLED", "ABORTED", "COMPLETED"):
                        logger.info(f"NetworkRecoveryCoordinator: Mission {mission_id} stopped concurrently; aborting auto-resume.")
                        return None
                    meta = fresh_row.get("metadata", {}) or {}
                    if meta.get("cancelled_by_user"):
                        logger.info(f"NetworkRecoveryCoordinator: Mission {mission_id} cancelled by user; aborting auto-resume.")
                        return None

            logger.info(f"NetworkRecoveryCoordinator: Initiating auto-recovery for mission {mission_id}...")

            # Emit NETWORK_RESTORED event
            if self.event_bus is not None:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.NETWORK_RESTORED,
                    mission_id=mission_id,
                    payload={"reason": "Network/provider restored, auto-resuming execution"}
                ))

            if self.runtime_adapter is None:
                raise RuntimeError("RuntimeAdapter not configured for NetworkRecoveryCoordinator")

            new_run_id = await self.runtime_adapter.resume_interrupted_mission(mission_id)
            logger.info(
                f"NetworkRecoveryCoordinator: Mission {mission_id} successfully auto-resumed with run ID {new_run_id}."
            )
            return new_run_id
        except Exception as exc:
            logger.exception(f"NetworkRecoveryCoordinator: Auto-resume failed for mission {mission_id}: {exc}")
            return None
        finally:
            self._recovering_missions.discard(mission_id)

    async def recover_waiting_missions(self) -> List[str]:
        """
        Discover and resume all eligible waiting missions.
        Deduplicated and debounced under async lock.
        """
        async with self._lock:
            now = time.time()
            if (now - self._last_recovery_at) < self.debounce_seconds:
                logger.debug("NetworkRecoveryCoordinator: debounce active, skipping redundant recovery pass.")
                return []
            self._last_recovery_at = now

            waiting = self.find_eligible_waiting_missions()
            if not waiting:
                logger.debug("NetworkRecoveryCoordinator: No eligible waiting missions discovered.")
                return []

            logger.info(f"NetworkRecoveryCoordinator: Found {len(waiting)} waiting mission(s) to evaluate.")
            resumed = []
            for row in waiting:
                m_id = row["mission_id"]
                new_run_id = await self.auto_resume_mission(m_id)
                if new_run_id:
                    resumed.append(m_id)

            return resumed

    def _on_connectivity_changed(self, old_status: ConnectivityStatus, new_status: ConnectivityStatus) -> None:
        """Listener callback invoked by ConnectivityMonitor when status changes."""
        if new_status == ConnectivityStatus.ONLINE and old_status != ConnectivityStatus.ONLINE:
            logger.info(
                f"NetworkRecoveryCoordinator: Connectivity restored ({old_status.value} -> ONLINE). Scheduling recovery pass."
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.recover_waiting_missions())
            except RuntimeError:
                pass

    def _on_circuit_route_changed(self, route_key: str, new_state: CircuitState, old_state: Optional[CircuitState]) -> None:
        """Listener callback invoked by CircuitBreakerRegistry when route state changes."""
        if new_state == CircuitState.CLOSED and old_state != CircuitState.CLOSED:
            logger.info(
                f"NetworkRecoveryCoordinator: Provider route '{route_key}' restored to CLOSED. Scheduling auto-recovery pass."
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.recover_waiting_missions())
            except RuntimeError:
                pass

    def notify_provider_recovered(self, provider: str = "", model: str = "") -> None:
        """
        Directly notify coordinator that a provider/model route has recovered.
        Closes circuit breaker record and triggers automated recovery sweep.
        """
        logger.info(f"NetworkRecoveryCoordinator: Provider recovery notified ({provider}:{model}). Scheduling recovery pass.")
        if provider and model:
            circuit_breaker_registry.notify_route_recovered(provider, model)
        try:
            from core.adaptive_routing import get_adaptive_router
            get_adaptive_router().notify_provider_recovered(tier=1)
        except Exception as e:
            logger.debug(f"NetworkRecoveryCoordinator: error resetting adaptive router: {e}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.recover_waiting_missions())
        except RuntimeError:
            pass

    async def _check_provider_routes_loop(self) -> None:
        """Periodic background probe to detect provider recovery without requiring manual API calls."""
        while self._running:
            try:
                await asyncio.sleep(self.provider_probe_interval)
                waiting = self.find_eligible_waiting_missions()
                provider_waiting = [w for w in waiting if w.get("wait_reason") == "WAITING_FOR_PROVIDER"]
                if not provider_waiting:
                    continue

                # Check T1 provider health with 0 billable tokens, with debounce cooldown
                now = time.monotonic()
                if now - self._last_recovery_at < 60.0:
                    continue

                try:
                    from models.nvidia_client import get_shared_nvidia_client
                    from config.model_config import TIER1_PROVIDER, TIER1_MODEL
                    nv_client = get_shared_nvidia_client()
                    is_up = await nv_client.is_running(timeout=2.5)
                    if is_up:
                        logger.info(f"NetworkRecoveryCoordinator: Provider '{TIER1_PROVIDER}' responded healthy. Notifying recovery.")
                        self._last_recovery_at = now
                        self.notify_provider_recovered(TIER1_PROVIDER, TIER1_MODEL)
                except Exception as probe_err:
                    logger.debug(f"NetworkRecoveryCoordinator: provider probe check: {probe_err}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"NetworkRecoveryCoordinator: provider route loop exception: {e}")

    def start(self) -> None:
        """Register listeners on ConnectivityMonitor and CircuitBreakerRegistry, and start provider probe loop."""
        self._running = True
        if not self._listener_registered:
            self.monitor.add_listener(self._on_connectivity_changed)
            self._listener_registered = True
            logger.info("NetworkRecoveryCoordinator: registered listener on ConnectivityMonitor.")

        if not self._cb_listener_registered:
            circuit_breaker_registry.add_listener(self._on_circuit_route_changed)
            self._cb_listener_registered = True
            logger.info("NetworkRecoveryCoordinator: registered listener on CircuitBreakerRegistry.")

        if self._provider_probe_task is None or self._provider_probe_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._provider_probe_task = loop.create_task(self._check_provider_routes_loop())
            except RuntimeError:
                pass

    def stop(self) -> None:
        """Unregister listeners and stop background probe task."""
        self._running = False
        if self._listener_registered:
            self.monitor.remove_listener(self._on_connectivity_changed)
            self._listener_registered = False

        if self._cb_listener_registered:
            circuit_breaker_registry.remove_listener(self._on_circuit_route_changed)
            self._cb_listener_registered = False

        if self._provider_probe_task and not self._provider_probe_task.done():
            self._provider_probe_task.cancel()
            self._provider_probe_task = None
        logger.info("NetworkRecoveryCoordinator: unregistered listeners and stopped provider probe.")


# Singleton coordinator instance
shared_recovery_coordinator = NetworkRecoveryCoordinator()
