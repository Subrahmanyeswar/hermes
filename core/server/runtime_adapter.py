# core/server/runtime_adapter.py
"""
Runtime Adapter bridging the local FastAPI server with the canonical HERMES runtime.
Manages running missions, event pub/sub dispatching, event replay, and cancellations.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from loguru import logger

from core.event_bus import EventBus, event_bus as global_event_bus
from core.runtime_factory import ApplicationRuntime, ApplicationRuntimeFactory, SurfaceMode
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionStatus, MissionControlContext
from core.runtime_state.store import StateStore, state_store as global_state_store
from core.workspace import WorkspaceManager, workspace_manager as global_workspace


class RuntimeAdapter:
    """
    Adapter between FastAPI HTTP/SSE server and canonical HERMES runtime services.
    Thread-safe, non-blocking, and isolated per mission.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        workspace_manager: Optional[WorkspaceManager] = None,
    ):
        self.event_bus = event_bus or global_event_bus
        self.workspace = workspace_manager or global_workspace

        self._active_runtimes: Dict[str, ApplicationRuntime] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._abort_events: Dict[str, asyncio.Event] = {}
        self._mission_controls: Dict[str, MissionControlContext] = {}

        # Mission-isolated event queues for live SSE streams: mission_id -> Set[asyncio.Queue]
        self._mission_subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

        # Subscribe this adapter to the global event bus
        self.event_bus.subscribe(self._on_runtime_event)

        # Restore persisted missions on backend startup
        self.restore_persisted_missions()

    def is_worker_alive(self, m: Union[dict, str]) -> bool:
        """
        Determine whether a mission recorded as RUNNING has an actually living worker.
        Differentiates:
        1. Live in-memory task in current process.
        2. Verified live process (PID).
        3. Dead/absent process.
        """
        import os
        if isinstance(m, str):
            db = self.event_bus.get_database()
            m_dict = db.get_mission(m) if db else None
            m_id = m
            m = m_dict or {"mission_id": m}
        else:
            m_id = m.get("mission_id")

        if not m_id:
            return False

        # 1. Check in-memory task
        task = self._active_tasks.get(m_id)
        if task is not None and not task.done():
            return True

        # 2. Check metadata PID
        meta = m.get("metadata") or {}
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except Exception:
                meta = {}
        worker_pid = meta.get("worker_pid")
        if not worker_pid:
            return False

        try:
            worker_pid = int(worker_pid)
        except (ValueError, TypeError):
            return False

        if worker_pid == os.getpid():
            # Assigned to current process, but current process has no active task for it
            return False

        # Check if external process is running
        try:
            import psutil
            if not psutil.pid_exists(worker_pid):
                return False
            p = psutil.Process(worker_pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return False
            cmd = " ".join(p.cmdline()).lower()
            if "hermes" in cmd or "python" in cmd:
                return True
        except Exception:
            return False

        return False

    def restore_persisted_missions(self) -> None:
        """
        Inspect canonical database on startup, rehydrate authoritative StateStore,
        and mark interrupted active missions as non-executing (execution_active = False,
        recovery_required = True). Does NOT launch duplicate background tasks.
        """
        db = self.event_bus.get_database()
        if not db:
            return

        try:
            from core.persistence.serializer import deserialize_runtime_state
            persisted_missions = db.list_missions()
            for m in persisted_missions:
                m_id = m.get("mission_id")
                if not m_id:
                    continue

                # If mission was marked active before restart, mark execution_active=False
                curr_status = m.get("status", "")
                is_terminal = curr_status in ("COMPLETED", "CANCELLED", "ABORTED")
                is_paused = (curr_status == "PAUSED")
                curr_meta = m.get("metadata", {}) or {}

                if m.get("execution_active"):
                    # Inspect if worker is genuinely alive before reconciling
                    if self.is_worker_alive(m):
                        logger.info(f"RuntimeAdapter: verified live worker for mission '{m_id}' (PID {curr_meta.get('worker_pid')}); not marking orphaned.")
                        continue

                    # The backend process that owned this execution is dead.
                    # Do not preserve a stale RUNNING status.
                    new_status = "WAITING" if not is_terminal and not is_paused else curr_status
                    orig_wait_reason = m.get("wait_reason", "NONE")
                    new_wait_reason = orig_wait_reason if orig_wait_reason in ("WAITING_FOR_NETWORK", "WAITING_FOR_PROVIDER") else ("WAITING_FOR_RECOVERY" if not is_terminal and not is_paused else orig_wait_reason)
                    new_recovery_req = not is_terminal and not is_paused
                    new_meta = {**curr_meta, "interrupted_by_restart": True, "reconciled_orphan": True}

                    db.save_mission(
                        mission_id=m_id,
                        workspace_path=m.get("workspace_path", ""),
                        status=new_status,
                        session_id=m.get("session_id"),
                        run_id=m.get("run_id"),
                        attempt_number=m.get("attempt_number", 1),
                        wait_reason=new_wait_reason,
                        prompt=m.get("prompt", ""),
                        state_version=m.get("state_version", 0),
                        last_event_sequence=m.get("last_event_sequence", 0),
                        latest_checkpoint_id=m.get("latest_checkpoint_id"),
                        execution_active=False,
                        recovery_required=new_recovery_req,
                        metadata=new_meta,
                    )

                # Phase 3: Inspect tool operations for unmatched/interrupted intents
                try:
                    from core.persistence.models import OperationStatus
                    interrupted_ops = db.list_tool_operations(m_id)
                    for op in interrupted_ops:
                        op_st = op.get("status")
                        if op_st in (OperationStatus.INTENT_COMMITTED.value, OperationStatus.EXECUTING.value):
                            logger.warning(
                                f"RuntimeAdapter: marking interrupted tool operation '{op.get('operation_id')}' "
                                f"in mission '{m_id}' as OUTCOME_UNKNOWN (REQUIRES_RECONCILIATION)"
                            )
                            db.update_operation_status(
                                operation_id=op["operation_id"],
                                status=OperationStatus.OUTCOME_UNKNOWN,
                                error_message="INTERRUPTED_BY_RESTART: Tool intent committed before backend shutdown but no definitive result recorded. REQUIRES_RECONCILIATION.",
                            )
                except Exception as op_recon_exc:
                    logger.warning(f"RuntimeAdapter: tool operation reconciliation warning for {m_id}: {op_recon_exc}")

                # Rehydrate StateStore from latest snapshot if not already active
                if self.event_bus.get_state(m_id) is None:
                    snap_row = db.get_snapshot(m_id)
                    if snap_row and snap_row.get("snapshot"):
                        try:
                            state = deserialize_runtime_state(snap_row["snapshot"])
                            # Replay any subsequent events from the journal
                            tail_events = self.event_bus.replay(m_id, from_seq=state.last_event_sequence + 1)
                            store = self.event_bus.get_or_create_state(m_id)
                            store.replay(tail_events, initial_state=state)
                        except Exception as deser_exc:
                            logger.warning(f"RuntimeAdapter: could not deserialize snapshot for {m_id}: {deser_exc}")
        except Exception as e:
            logger.warning(f"RuntimeAdapter: state restoration inspection warning: {e}")

    def _on_runtime_event(self, event: HermesEvent) -> None:
        """Callback from canonical EventBus when an event is published."""
        mission_id = event.mission_id

        if not mission_id:
            return

        if event.event_type.value in ("MISSION_COMPLETED", "MISSION_FAILED", "MISSION_CANCELLED"):
            # Automatically invalidate any pending approvals bound to this terminal mission
            for rt in self._active_runtimes.values():
                try:
                    rt.security.approval_store.cancel_requests_for_mission(
                        mission_id, reason=f"Mission entered terminal state: {event.event_type.value}"
                    )
                except Exception:
                    pass

        if event.event_type.value == "MISSION_PAUSED":
            ctrl = self._mission_controls.get(mission_id)
            if ctrl and hasattr(ctrl, "confirm_pause"):
                ctrl.confirm_pause()
        elif event.event_type.value == "MISSION_RESUMED":
            ctrl = self._mission_controls.get(mission_id)
            if ctrl and hasattr(ctrl, "resume"):
                ctrl.resume()

        queues = list(self._mission_subscribers.get(mission_id, []))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow client protection: discard oldest or skip to prevent loop blocking
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
            except Exception:
                pass

    async def get_or_create_runtime(
        self,
        workspace_root: Optional[Path | str] = None,
        session_id: Optional[str] = None,
    ) -> ApplicationRuntime:
        """Create or return an ApplicationRuntime configured for the workspace."""
        ws = Path(workspace_root or (self.workspace.root_str if self.workspace.is_locked else Path.cwd())).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        cache_key = str(ws)
        if cache_key in self._active_runtimes:
            return self._active_runtimes[cache_key]

        rt = ApplicationRuntimeFactory.create_runtime(
            mode=SurfaceMode.HEADLESS,
            workspace_root=ws,
            session_id=session_id,
            debug=False,
        )
        self._active_runtimes[cache_key] = rt
        return rt

    async def start_mission(
        self,
        prompt: str,
        workspace_root: Optional[str] = None,
        plan_mode: bool = False,
    ) -> str:
        """
        Launch a mission in background task using canonical runtime.
        Returns mission_id immediately.
        """
        async with self._lock:
            # Task 2.1: Single-Mission Mutual Exclusion
            # Reject if any mission is actively running in memory
            for active_id, active_task in list(self._active_tasks.items()):
                if active_task is not None and not active_task.done():
                    raise RuntimeError(
                        f"Cannot start new mission: mission '{active_id}' is actively executing (single-mission policy)."
                    )
            # Also check if database records an active execution with a verified live worker
            db = self.event_bus.get_database()
            if db:
                for m in db.list_missions():
                    if m.get("execution_active") and m.get("status") == "RUNNING":
                        if self.is_worker_alive(m):
                            raise RuntimeError(
                                f"Cannot start new mission: mission '{m.get('mission_id')}' is actively executing (single-mission policy)."
                            )

            rt = await self.get_or_create_runtime(workspace_root=workspace_root)
            if self.workspace:
                try:
                    self.workspace.lock(str(rt.workspace_root))
                except Exception as lock_err:
                    logger.warning(f"RuntimeAdapter: workspace lock warning: {lock_err}")
            os.environ["HERMES_WORKSPACE_ROOT"] = str(rt.workspace_root)
            abort_evt = asyncio.Event()
            pause_evt = asyncio.Event()
            pause_evt.set()  # Initial state: running (not paused)

            # Generate stable mission ID and initial run ID
            import uuid
            mission_id = f"m_{uuid.uuid4().hex[:8]}"
            run_id = f"run_1_{uuid.uuid4().hex[:8]}"
            attempt_number = 1

            control = MissionControlContext(
                mission_id=mission_id,
                run_id=run_id,
                attempt_number=attempt_number,
                abort_event=abort_evt,
                pause_event=pause_evt,
                workspace_root=str(rt.workspace_root),
            )

            self._active_runtimes[mission_id] = rt
            self._abort_events[mission_id] = abort_evt
            self._mission_controls[mission_id] = control

            # Initialize authoritative state store for this mission if not present
            self.event_bus.get_or_create_state(mission_id)

            # Spawn background execution task
            task = asyncio.create_task(
                self._run_mission_background(rt, mission_id, prompt, plan_mode, control)
            )
            self._active_tasks[mission_id] = task

            return mission_id

    async def _run_mission_background(
        self,
        runtime: ApplicationRuntime,
        mission_id: str,
        prompt: str,
        plan_mode: bool,
        control: Optional[MissionControlContext] = None,
    ) -> None:
        """Background coroutine running the canonical mission."""
        try:
            from core.mission_planner import Mission
            from core.agent_loop.loop import AgentLoop

            run_id = control.run_id if control else f"run_1_{mission_id}"
            attempt_number = control.attempt_number if control else 1
            abort_evt = control.abort_event if control else self._abort_events.get(mission_id)
            pause_evt = control.pause_event if control else None

            mission = Mission(
                mission_id=mission_id,
                run_id=run_id,
                attempt_number=attempt_number,
                user_prompt=prompt,
                workspace_root=str(runtime.workspace_root),
                abort_event=abort_evt,
            )
            if pause_evt is not None:
                setattr(mission, "pause_event", pause_evt)
            if plan_mode:
                setattr(mission, "plan_mode", True)

            # Publish MISSION_CREATED with run identity
            self.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_CREATED,
                mission_id=mission_id,
                run_id=run_id,
                attempt_number=attempt_number,
                payload={
                    "prompt": prompt,
                    "workspace_root": str(runtime.workspace_root),
                    "plan_mode": plan_mode,
                    "run_id": run_id,
                    "attempt_number": attempt_number,
                }
            ))

            # Record canonical mission in database with execution_active = True
            db = self.event_bus.get_database()
            if db:
                try:
                    import os
                    db.save_mission(
                        mission_id=mission_id,
                        workspace_path=str(runtime.workspace_root),
                        status="RUNNING",
                        session_id=None,
                        run_id=run_id,
                        attempt_number=attempt_number,
                        wait_reason="WORKING",
                        prompt=prompt,
                        execution_active=True,
                        recovery_required=False,
                        metadata={"worker_pid": os.getpid(), "plan_mode": plan_mode},
                    )
                except Exception as db_exc:
                    logger.warning(f"RuntimeAdapter: initial mission record save failed: {db_exc}")

            # Instantiate an isolated, scoped AgentLoop for this mission run
            # to guarantee execution control isolation and prevent cross-mission mutation.
            chk_engine = getattr(runtime, "session_manager", None)
            chk_engine = getattr(chk_engine, "checkpoint_engine", None) if chk_engine else None
            ws_mgr = (
                getattr(runtime, "workspace_manager", None)
                or getattr(runtime, "workspace", None)
                or self.workspace
            )
            from core.agent_loop.types import AgentLoopConfig
            loop_instance = AgentLoop(
                orchestrator=runtime.orchestrator,
                workspace_manager=ws_mgr,
                event_bus_instance=self.event_bus,
                state_store_instance=self.event_bus.get_state(mission_id),
                abort_event=abort_evt,
                checkpoint_engine=chk_engine,
                config=AgentLoopConfig(),
            )
            if pause_evt is not None:
                setattr(loop_instance, "pause_event", pause_evt)
            if control is not None:
                setattr(mission, "control", control)
                setattr(loop_instance, "control", control)

            await loop_instance.run(mission)

        except asyncio.CancelledError:
            logger.info(f"RuntimeAdapter: Mission {mission_id} cancelled.")
            if control:
                control.mark_terminal()
            try:
                from tools.shell_tools import terminate_active_subprocesses
                terminate_active_subprocesses(mission_id=mission_id)
            except Exception:
                pass
            self.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_CANCELLED,
                mission_id=mission_id,
                run_id=control.run_id if control else None,
                attempt_number=control.attempt_number if control else 1,
                payload={"reason": "Cancelled by user via API"}
            ))
        except Exception as e:
            store = self.event_bus.get_state(mission_id)
            snap = store.get_snapshot() if store else None
            is_cancelled = bool((control and control.is_cancelled) or (snap and snap.mission.status == MissionStatus.CANCELLED))
            if is_cancelled:
                logger.info(f"RuntimeAdapter: Mission {mission_id} exception swallowed due to active cancellation: {e}")
            elif snap and snap.mission.status == MissionStatus.WAITING:
                logger.info(f"RuntimeAdapter: Mission {mission_id} transitioned into WAITING state.")
            else:
                logger.exception(f"RuntimeAdapter: Mission {mission_id} exception: {e}")
                if control:
                    control.mark_terminal()
                try:
                    from tools.shell_tools import terminate_active_subprocesses
                    terminate_active_subprocesses(mission_id=mission_id)
                except Exception:
                    pass
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.MISSION_FAILED,
                    mission_id=mission_id,
                    run_id=control.run_id if control else None,
                    attempt_number=control.attempt_number if control else 1,
                    payload={"error": str(e)}
                ))
        finally:
            store = self.event_bus.get_state(mission_id)
            final_snapshot = store.get_snapshot() if store else None
            is_waiting = bool(final_snapshot and final_snapshot.mission.status == MissionStatus.WAITING)
            is_cancelled = bool((control and control.is_cancelled) or (final_snapshot and final_snapshot.mission.status == MissionStatus.CANCELLED))

            if control and not is_waiting:
                control.mark_terminal()

            # Clean up active tasks map
            async with self._lock:
                self._active_tasks.pop(mission_id, None)

            # Persist status and latest snapshot to canonical database
            db = self.event_bus.get_database()
            if db:
                try:
                    if is_cancelled:
                        status_str = "CANCELLED"
                    else:
                        status_str = final_snapshot.mission.status.value if final_snapshot else ("WAITING" if is_waiting else "FAILED")
                    if status_str in ("RUNNING", "CREATED") and not is_waiting and not is_cancelled:
                        status_str = "FAILED"
                        logger.warning(
                            f"RuntimeAdapter: background task ended while status was '{final_snapshot.mission.status.value if final_snapshot else 'UNKNOWN'}'. Reconciling to FAILED."
                        )
                        err_msg = "Agent loop terminated unexpectedly without reaching a terminal state."
                        self.event_bus.publish(HermesEvent(
                            event_type=EventType.MISSION_FAILED,
                            mission_id=mission_id,
                            run_id=control.run_id if control else None,
                            attempt_number=control.attempt_number if control else 1,
                            payload={"error": err_msg}
                        ))
                        store = self.event_bus.get_state(mission_id)
                        final_snapshot = store.get_snapshot() if store else None
                    wait_reason_str = final_snapshot.progress.waiting_reason.value if final_snapshot and hasattr(final_snapshot.progress.waiting_reason, "value") else ("WAITING_FOR_NETWORK" if is_waiting else "NONE")
                    from core.persistence.serializer import serialize_runtime_state
                    if final_snapshot:
                        snap_dict, s_hash = serialize_runtime_state(final_snapshot)
                        db.save_snapshot(
                            mission_id=mission_id,
                            workspace_path=str(runtime.workspace_root),
                            status=status_str,
                            snapshot_dict=snap_dict,
                            state_hash=s_hash,
                            run_id=control.run_id if control else None,
                            attempt_number=control.attempt_number if control else 1,
                            state_version=final_snapshot.state_version,
                            last_event_sequence=final_snapshot.last_event_sequence,
                        )
                    db.save_mission(
                        mission_id=mission_id,
                        workspace_path=str(runtime.workspace_root),
                        status=status_str,
                        session_id=None,
                        run_id=control.run_id if control else None,
                        attempt_number=control.attempt_number if control else 1,
                        wait_reason=wait_reason_str,
                        prompt=prompt,
                        state_version=final_snapshot.state_version if final_snapshot else 0,
                        last_event_sequence=final_snapshot.last_event_sequence if final_snapshot else 0,
                        execution_active=False,
                        recovery_required=is_waiting,
                    )
                except Exception as final_save_exc:
                    logger.warning(f"RuntimeAdapter: mission persistence warning: {final_save_exc}")

    async def stop_mission(self, mission_id: str, timeout: float = 5.0) -> bool:
        """Cancel an active or stale running mission through authoritative abort event, task cancellation, and persistent update."""
        async with self._lock:
            # Immediately invalidate any pending approvals for this mission
            for rt in self._active_runtimes.values():
                try:
                    rt.security.approval_store.cancel_requests_for_mission(
                        mission_id, reason="Mission cancelled by user via API"
                    )
                except Exception:
                    pass

            control = self._mission_controls.get(mission_id)
            if control:
                control.cancel()

            abort_evt = self._abort_events.get(mission_id)
            if abort_evt:
                abort_evt.set()

            # Terminate any running child/worker subprocesses owned by this mission
            try:
                from tools.shell_tools import terminate_active_subprocesses
                terminate_active_subprocesses(mission_id=mission_id)
            except Exception:
                pass

            task_was_active = False
            task = self._active_tasks.get(mission_id)
            if task and not task.done():
                task_was_active = True
                task.cancel()
                if control:
                    control.mark_terminal()

            # If not actively executing in memory (or executor already terminated),
            # check the authoritative StateStore or Database
            db = self.event_bus.get_database()
            m_row = db.get_mission(mission_id) if db else None

            # Check if state store is available in memory
            store = self.event_bus.get_state(mission_id)
            if not task_was_active:
                if store:
                    st = store.get_snapshot()
                    if st.mission.is_terminal:
                        return False  # Already cleanly terminated
                elif m_row:
                    m_st = m_row.get("status", "")
                    if m_st in ("COMPLETED", "FAILED", "CANCELLED", "ABORTED"):
                        return False  # Already terminal in database
                else:
                    return False  # Mission does not exist

            # Immediately update in-memory state store snapshot to CANCELLED
            if store:
                try:
                    from core.runtime_state.models import MissionStatus, WaitReason
                    snap = store.get_snapshot()
                    snap.mission.status = MissionStatus.CANCELLED
                    snap.mission.cancelled = True
                    snap.progress.waiting_reason = WaitReason.CANCELLED
                except Exception:
                    pass

            # Publish authoritative cancellation event durably to write-ahead journal immediately
            run_id = control.run_id if control else (m_row.get("run_id") if m_row else None)
            attempt_number = control.attempt_number if control else (m_row.get("attempt_number", 1) if m_row else 1)
            self.event_bus.publish_durable(HermesEvent(
                event_type=EventType.MISSION_CANCELLED,
                mission_id=mission_id,
                run_id=run_id,
                attempt_number=attempt_number,
                payload={"reason": "Stop requested via API"}
            ))

            if control:
                control.mark_terminal()

            # Guarantee durable persistence to missions and snapshots tables immediately
            if db and m_row:
                ws_path = m_row.get("workspace_path") or str(Path.cwd())
                updated_store = self.event_bus.get_state(mission_id)
                latest_snap = updated_store.get_snapshot() if updated_store else None
                s_ver = (latest_snap.state_version if latest_snap else m_row.get("state_version", 0)) + 1
                l_seq = latest_snap.last_event_sequence if latest_snap else m_row.get("last_event_sequence", 0)

                # Capture durable checkpoint for Stop if CheckpointEngine is available
                latest_chk_id = None
                rt = self._active_runtimes.get(mission_id)
                chk_engine = getattr(rt, "session_manager", None)
                chk_engine = getattr(chk_engine, "checkpoint_engine", None) if chk_engine else None
                if chk_engine and latest_snap:
                    try:
                        from core.persistence.models import CheckpointReason, CheckpointTrigger
                        chk_manifest = chk_engine.create_checkpoint(
                            session_id=m_row.get("session_id") or f"sess_{mission_id}",
                            mission_id=mission_id,
                            runtime_state=latest_snap,
                            reason=CheckpointReason.MANUAL,
                            trigger=CheckpointTrigger.USER,
                            metadata={"stop_reason": "Cancelled by user via API"},
                        )
                        latest_chk_id = chk_manifest.checkpoint_id
                    except Exception as chk_exc:
                        logger.warning(f"RuntimeAdapter: stop checkpoint creation warning: {chk_exc}")

                if latest_snap:
                    from core.persistence.serializer import serialize_runtime_state
                    snap_dict, s_hash = serialize_runtime_state(latest_snap)
                    db.save_snapshot(
                        mission_id=mission_id,
                        workspace_path=ws_path,
                        status="CANCELLED",
                        snapshot_dict=snap_dict,
                        state_hash=s_hash,
                        run_id=run_id,
                        attempt_number=attempt_number,
                        state_version=s_ver,
                        last_event_sequence=l_seq,
                    )

                db.save_mission(
                    mission_id=mission_id,
                    workspace_path=ws_path,
                    status="CANCELLED",
                    session_id=m_row.get("session_id"),
                    run_id=run_id,
                    attempt_number=attempt_number,
                    wait_reason="NONE",
                    prompt=m_row.get("prompt", ""),
                    state_version=s_ver,
                    last_event_sequence=l_seq,
                    latest_checkpoint_id=latest_chk_id or m_row.get("latest_checkpoint_id"),
                    execution_active=False,
                    recovery_required=False,
                )

            # Fast bounded wait on task cleanup to not block HTTP response
            if task and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

            return True

    def request_cancellation(self, mission_id: str) -> bool:
        """Signal cancellation for a mission without blocking."""
        control = self._mission_controls.get(mission_id)
        if control:
            control.cancel()
        abort_evt = self._abort_events.get(mission_id)
        if abort_evt:
            abort_evt.set()
            return True
        return False

    def request_pause(self, mission_id: str) -> tuple[bool, bool]:
        """Request pause for an active mission.
        
        Returns:
            (accepted, confirmed)
            - If in-flight task is actively running: marks pause_requested, clears pause_event,
              returns (True, False). Safe boundary in AgentLoop will confirm and emit MISSION_PAUSED.
            - If no active task or task already completed/not running: confirms immediately,
              emits MISSION_PAUSED, returns (True, True).
        """
        control = self._mission_controls.get(mission_id)
        if not control or control.is_terminal:
            return False, False

        # Idempotency: if already confirmed paused
        if control.is_paused:
            return True, True

        task = self._active_tasks.get(mission_id)
        if task and not task.done():
            # In-flight task is executing: signal pause, wait for safe checkpoint boundary
            control.request_pause()
            return True, False
        else:
            # Not executing actively or already at boundary: confirm immediately
            control.request_pause()
            control.confirm_pause()
            self.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_PAUSED,
                mission_id=mission_id,
                run_id=control.run_id,
                attempt_number=control.attempt_number,
                payload={"mission_id": mission_id, "reason": "Paused by user via API"}
            ))
            return True, True

    def resume_mission(self, mission_id: str) -> bool:
        """Signal resume for an in-flight paused or pause-pending mission."""
        control = self._mission_controls.get(mission_id)
        if control and not control.is_terminal and (control.is_paused or control.pause_requested):
            was_confirmed_paused = control.is_paused
            control.resume()
            if was_confirmed_paused:
                self.event_bus.publish(HermesEvent(
                    event_type=EventType.MISSION_RESUMED,
                    mission_id=mission_id,
                    run_id=control.run_id,
                    attempt_number=control.attempt_number,
                    payload={"mission_id": mission_id, "reason": "Resumed by user via API"}
                ))
            return True
        return False

    def validate_resume_eligibility(self, mission_id: str) -> tuple[bool, str]:
        """
        Validate whether a mission is eligible for live unpause or cold resume.
        Supports:
        1. Live unpausing of an in-flight paused run.
        2. Cold durable resume of an interrupted / cancelled / failed mission from persistent state.
        """
        task = self._active_tasks.get(mission_id)
        if task and not task.done():
            control = self._mission_controls.get(mission_id)
            if control:
                if control.is_terminal:
                    return False, "Cannot resume a mission that has already reached a terminal state"
                if not (control.is_paused or control.pause_requested):
                    return False, "Mission is not currently in a paused state"
                return True, "Mission is eligible for resume"
            return False, f"Mission '{mission_id}' is currently actively running."

        # Check database for persistent recovery feasibility
        db = self.event_bus.get_database()
        mission_row = db.get_mission(mission_id) if db else None
        if not mission_row:
            control = self._mission_controls.get(mission_id)
            if control and control.is_terminal:
                return False, "Cannot resume a mission that has already reached a terminal state"
            return False, "Mission control context not found in active session; durable checkpoint recovery deferred to Phase 2/3"

        # If previous task is done, pop stale in-flight control context
        self._mission_controls.pop(mission_id, None)

        from core.persistence.blobs import BlobStore
        from core.persistence.recovery import RecoveryEngine
        blob_store = getattr(self.event_bus, "blob_store", None) or BlobStore(Path(db.db_path).parent / "blobs")
        recovery_engine = RecoveryEngine(db=db, blob_store=blob_store, workspace_manager=self.workspace)
        plan = recovery_engine.formulate_resume_plan(mission_id)

        if not plan.can_resume:
            return False, plan.reason

        return True, plan.reason

    async def resume_interrupted_mission(self, mission_id: str) -> str:
        """
        Resume an interrupted, cancelled, or stopped mission from the first safe unfinished task.
        Creates a new continuation run (run_id = f"run_{next_attempt}_{uuid.hex[:8]}", attempt_number = prev + 1).
        Does NOT resurrect old terminal run IDs or clear old abort events.
        Enforces idempotency and workspace binding.
        """
        async with self._lock:
            # 1. Concurrency guard: single-mission execution policy
            for active_id, active_task in list(self._active_tasks.items()):
                if active_id != mission_id and active_task is not None and not active_task.done():
                    raise RuntimeError(
                        f"Cannot resume mission '{mission_id}': another mission '{active_id}' is actively executing (single-mission policy)."
                    )
            task = self._active_tasks.get(mission_id)
            if task and not task.done():
                raise RuntimeError(f"Mission '{mission_id}' is already actively executing.")

            db = self.event_bus.get_database()
            if not db:
                raise RuntimeError("Database not available for durable mission recovery.")

            from core.persistence.blobs import BlobStore
            from core.persistence.recovery import RecoveryEngine
            blob_store = getattr(self.event_bus, "blob_store", None) or BlobStore(Path(db.db_path).parent / "blobs")
            recovery_engine = RecoveryEngine(db=db, blob_store=blob_store, workspace_manager=self.workspace)
            plan = recovery_engine.formulate_resume_plan(mission_id)

            if not plan.can_resume:
                raise ValueError(f"Cannot resume mission '{mission_id}': {plan.reason}")

            # 2. Workspace binding: lock workspace to original workspace
            orig_ws = Path(plan.original_workspace).resolve()
            try:
                self.workspace.lock(str(orig_ws))
            except Exception as lock_err:
                logger.warning(f"RuntimeAdapter: workspace lock warning: {lock_err}")

            rt = await self.get_or_create_runtime(workspace_root=orig_ws)

            # 3. Determine next run identity
            mission_row = db.get_mission(mission_id)
            prev_attempt = mission_row.get("attempt_number", 1) if mission_row else 1
            next_attempt = prev_attempt + 1
            import uuid
            new_run_id = f"run_{next_attempt}_{uuid.uuid4().hex[:8]}"

            abort_evt = asyncio.Event()
            pause_evt = asyncio.Event()
            pause_evt.set()

            control = MissionControlContext(
                mission_id=mission_id,
                run_id=new_run_id,
                attempt_number=next_attempt,
                abort_event=abort_evt,
                pause_event=pause_evt,
                workspace_root=str(orig_ws),
            )

            self._active_runtimes[mission_id] = rt
            self._abort_events[mission_id] = abort_evt
            self._mission_controls[mission_id] = control

            # 4. Update canonical mission record in database
            prompt = mission_row.get("prompt", "") if mission_row else ""
            db.save_mission(
                mission_id=mission_id,
                workspace_path=str(orig_ws),
                status="RUNNING",
                session_id=mission_row.get("session_id") if mission_row else None,
                run_id=new_run_id,
                attempt_number=next_attempt,
                wait_reason="WORKING",
                prompt=prompt,
                execution_active=True,
                recovery_required=False,
                metadata={"worker_pid": os.getpid(), "resumed": True},
            )

            # 5. Emit MISSION_RESUMED event with continuation identity
            self.event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_RESUMED,
                mission_id=mission_id,
                run_id=new_run_id,
                attempt_number=next_attempt,
                payload={
                    "mission_id": mission_id,
                    "run_id": new_run_id,
                    "attempt_number": next_attempt,
                    "workspace_root": str(orig_ws),
                    "target_task_id": plan.target_task_id,
                    "target_task_title": plan.target_task_title,
                    "completed_tasks": plan.completed_tasks,
                }
            ))

            # 6. Spawn continuation background task
            plan_mode = bool(mission_row.get("metadata", {}).get("plan_mode", False)) if mission_row else False
            cont_task = asyncio.create_task(
                self._run_mission_background(rt, mission_id, prompt, plan_mode, control)
            )
            self._active_tasks[mission_id] = cont_task

            return new_run_id

    def get_mission_snapshot(self, mission_id: str) -> Optional[HermesRuntimeState]:
        """Fetch authoritative snapshot from StateStore or fall back to database."""
        store = self.event_bus.get_state(mission_id)
        if store:
            return store.get_snapshot()

        # Database fallback if not currently in memory
        db = self.event_bus.get_database()
        if db:
            snap_row = db.get_snapshot(mission_id)
            if snap_row and snap_row.get("snapshot"):
                from core.persistence.serializer import deserialize_runtime_state
                try:
                    state = deserialize_runtime_state(snap_row["snapshot"])
                    # Rehydrate memory state store
                    tail_events = self.event_bus.replay(mission_id, from_seq=state.last_event_sequence + 1)
                    store = self.event_bus.get_or_create_state(mission_id)
                    return store.replay(tail_events, initial_state=state)
                except Exception as deser_exc:
                    logger.warning(f"RuntimeAdapter: get_mission_snapshot deserialization failed: {deser_exc}")

            # Replay from durable journal if no snapshot row exists
            events = self.event_bus.replay(mission_id, from_seq=0)
            if events:
                try:
                    store = self.event_bus.get_or_create_state(mission_id)
                    return store.replay(events)
                except Exception as replay_exc:
                    logger.warning(f"RuntimeAdapter: get_mission_snapshot journal replay failed: {replay_exc}")

        return None

    def get_events_since(self, mission_id: str, last_sequence: int = 0) -> List[HermesEvent]:
        """Retrieve replayed events from EventBus (or DB journal) after the given sequence cursor."""
        all_events = self.event_bus.replay(mission_id, from_seq=last_sequence + 1)
        if last_sequence <= 0:
            return all_events
        return [e for e in all_events if e.sequence > last_sequence]

    async def subscribe_mission_events(
        self,
        mission_id: str,
        last_sequence: int = 0,
    ) -> AsyncGenerator[HermesEvent, None]:
        """
        Async generator yielding historical events followed by live events for SSE.
        Handles client disconnect gracefully.
        """
        queue: asyncio.Queue[HermesEvent] = asyncio.Queue(maxsize=1000)

        # 1. Register live queue under lock
        async with self._lock:
            if mission_id not in self._mission_subscribers:
                self._mission_subscribers[mission_id] = set()
            self._mission_subscribers[mission_id].add(queue)

        try:
            # 2. Replay historical events past cursor
            historical = self.get_events_since(mission_id, last_sequence)
            highest_yielded_seq = last_sequence

            for evt in historical:
                if evt.sequence > highest_yielded_seq:
                    highest_yielded_seq = evt.sequence
                    yield evt

            # 3. Stream live events
            while True:
                try:
                    # Timeout periodically to check liveness / yield control
                    evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                    if evt.sequence > highest_yielded_seq:
                        highest_yielded_seq = evt.sequence
                        yield evt
                except asyncio.TimeoutError:
                    # Send periodic keepalive event
                    yield HermesEvent(
                        event_type=EventType.HEARTBEAT,
                        mission_id=mission_id,
                        payload={"time": asyncio.get_event_loop().time()}
                    )
        finally:
            # Clean up queue subscription on disconnect
            async with self._lock:
                subs = self._mission_subscribers.get(mission_id)
                if subs and queue in subs:
                    subs.remove(queue)
                    if not subs:
                        self._mission_subscribers.pop(mission_id, None)


# Global singleton adapter
runtime_adapter = RuntimeAdapter()
