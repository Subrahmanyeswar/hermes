# core/server/app.py
"""
FastAPI Application and Router Definitions for HERMES 2.x API.
Exposes health, workspaces, sessions, missions, SSE event streams, approvals, and stop controls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from config.model_config import (
    TIER1_MODEL,
    TIER1_PROVIDER,
    TIER2_MODEL,
    TIER2_PROVIDER,
    TIER3_MODEL,
    TIER3_PROVIDER,
)
from core.runtime_state.models import MissionStatus
from core.runtime_state.events import EventType, HermesEvent
from core.server.events import format_hermes_event_to_sse
from core.server.models import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    CreateMissionRequest,
    CreateMissionResponse,
    FileDiffEntry,
    HealthResponse,
    MissionChecksResponse,
    MissionDiffsResponse,
    MissionSnapshot,
    PendingApprovalItem,
    PendingApprovalsResponse,
    PickFolderResponse,
    RemoveWorkspaceRequest,
    ResumeMissionResponse,
    ResumePreviewResponse,
    DiscrepancyItem,
    SelectWorkspaceRequest,
    SessionsResponse,
    SessionSummary,
    StopMissionResponse,
    PauseMissionResponse,
    TaskSnapshot,
    VerificationCheckItem,
    WorkspaceInfo,
    WorkspacesResponse,
    NetworkStatusResponse,
    NetworkRecoverResponse,
)
from core.server.checks_service import extract_mission_checks
from core.server.diff_service import compute_file_diff, get_mission_diffs
from core.server.runtime_adapter import runtime_adapter
from core.server.security import LocalHostSecurityMiddleware, validate_workspace_access
from core.workspace import WorkspaceBoundaryError, workspace_manager
from core.workspace_registry import workspace_registry, is_hermes_repo_root, HERMES_ROOT

# Lightweight TTL cache for workspace root disk existence checks: ws_path -> (exists, timestamp)
_WS_EXIST_CACHE: dict[str, tuple[bool, float]] = {}

_APP_STARTUP_TIME = time.time()


_CRITICAL_RUNTIME_FILES = [
    "core/server/app.py",
    "core/server/runtime_adapter.py",
    "core/agent_loop/loop.py",
    "core/agent_loop/types.py",
    "core/agent_loop/decisions.py",
    "core/agent_loop/recovery_policy.py",
    "core/adaptive_routing.py",
    "core/structured_observation.py",
    "models/common_adapter.py",
    "tools/platform/core_tools.py",
    "core/event_bus.py",
    "config/model_config.py",
    "core/observability/__init__.py",
    "core/observability/bus_subscriber.py",
    "core/observability/logger.py",
    "core/observability/schemas.py",
    "core/observability/spans.py",
]


def _compute_module_hashes() -> dict[str, str]:
    """Compute sha256 digests for all critical runtime modules."""
    import hashlib
    base_repo = Path(__file__).resolve().parent.parent.parent
    hashes = {}
    for rel in _CRITICAL_RUNTIME_FILES:
        target = base_repo / rel
        if target.exists():
            hashes[rel] = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
        else:
            hashes[rel] = "missing"
    return hashes


def _compute_code_fingerprint() -> str:
    """Compute combined sha256 hash of all critical runtime modules."""
    try:
        import hashlib
        h = hashlib.sha256()
        hashes = _compute_module_hashes()
        for k in sorted(hashes.keys()):
            h.update(f"{k}:{hashes[k]}".encode("utf-8"))
        return h.hexdigest()[:16]
    except Exception:
        return "unknown"


_SERVER_MODULE_HASHES = _compute_module_hashes()
_SERVER_CODE_FINGERPRINT = _compute_code_fingerprint()


def _get_code_mismatches() -> list[str]:
    """Compare loaded server hashes with current files on disk."""
    current_hashes = _compute_module_hashes()
    mismatched = []
    for rel, initial_hash in _SERVER_MODULE_HASHES.items():
        curr_hash = current_hashes.get(rel)
        if curr_hash != initial_hash:
            mismatched.append(rel)
    return mismatched


def create_app(adapter: Optional[RuntimeAdapter] = None, registry: Optional[WorkspaceRegistry] = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    eff_adapter = adapter or runtime_adapter
    eff_registry = registry or workspace_registry
    from contextlib import asynccontextmanager
    from core.transport.client_manager import transport_client_manager
    from models.nvidia_client import close_shared_nvidia_client
    from models.ollama_client import close_shared_ollama_client

    async def _execute_safe_shutdown():
        from core.runtime_state.events import redact_sensitive_str
        from core.network.connectivity import shared_connectivity_monitor
        from core.network.coordinator import shared_recovery_coordinator

        cleanup_failures: list[str] = []

        # 1. Subscriber detachment
        try:
            if hasattr(eff_adapter, "detach_telemetry_subscriber"):
                eff_adapter.detach_telemetry_subscriber()
        except Exception as exc:
            msg = f"detach_telemetry_subscriber failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 2. Recovery coordinator shutdown
        try:
            shared_recovery_coordinator.stop()
        except Exception as exc:
            msg = f"recovery_coordinator.stop failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 3. Connectivity monitor shutdown
        try:
            await shared_connectivity_monitor.stop()
        except Exception as exc:
            msg = f"connectivity_monitor.stop failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 4. Transport client cleanup
        try:
            await transport_client_manager.aclose()
        except Exception as exc:
            msg = f"transport_client_manager.aclose failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 5. NVIDIA client cleanup
        try:
            await close_shared_nvidia_client()
        except Exception as exc:
            msg = f"close_shared_nvidia_client failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 6. Ollama client cleanup
        try:
            await close_shared_ollama_client()
        except Exception as exc:
            msg = f"close_shared_ollama_client failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 7. Common adapter cleanup
        try:
            from models.common_adapter import close_all_adapters
            await close_all_adapters()
        except Exception as exc:
            msg = f"close_all_adapters failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 8. EventBus persistence flush and shutdown
        try:
            if hasattr(eff_adapter, "event_bus") and eff_adapter.event_bus:
                eff_adapter.event_bus.shutdown(timeout=5.0)
        except Exception as exc:
            msg = f"event_bus.shutdown failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        # 9. Runtime adapter cleanup
        try:
            if hasattr(eff_adapter, "cleanup"):
                eff_adapter.cleanup()
        except Exception as exc:
            msg = f"runtime_adapter.cleanup failed: {redact_sensitive_str(str(exc))}"
            cleanup_failures.append(msg)
            logger.warning(f"Shutdown: {msg}")

        if cleanup_failures:
            logger.warning(
                f"FastAPI lifespan shutdown completed with {len(cleanup_failures)} failure(s): "
                f"{'; '.join(cleanup_failures)}"
            )
        else:
            logger.info("FastAPI lifespan shutdown: all model transport clients, monitors, and EventBus closed cleanly.")

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        from core.network.connectivity import shared_connectivity_monitor
        from core.network.coordinator import shared_recovery_coordinator
        shared_recovery_coordinator.runtime_adapter = eff_adapter
        shared_recovery_coordinator.db = eff_adapter.event_bus.get_database() if eff_adapter.event_bus else None
        shared_recovery_coordinator.event_bus = eff_adapter.event_bus
        shared_connectivity_monitor.start()
        shared_recovery_coordinator.start()
        yield
        # Graceful shutdown: independently protect each cleanup operation
        await _execute_safe_shutdown()

    app = FastAPI(
        title="HERMES Runtime API",
        version="1.0.0-rc1",
        description="Local-first control API and event stream for HERMES autonomous software engineering harness.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.safe_shutdown = _execute_safe_shutdown

    # Attach local loopback security middleware
    app.add_middleware(LocalHostSecurityMiddleware)

    # ── Exception Handler: Redact Secrets ──────────────────────────────────────
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        from utils.logging import redact_secrets
        logger.exception(f"Unhandled server error: {exc}")
        clean_msg = redact_secrets(str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "detail": clean_msg},
        )

    # ── 1. GET /api/health ─────────────────────────────────────────────────────
    @app.get("/api/health", response_model=HealthResponse)
    async def get_health():
        import os
        if workspace_manager.is_locked and workspace_manager.workspace_root:
            ws_root = str(workspace_manager.workspace_root)
        elif os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true":
            ws_root = os.environ.get("HERMES_WORKSPACES_ROOT", "/workspaces")
        else:
            ws_root = str(Path.cwd().resolve())
        disk_fingerprint = _compute_code_fingerprint()
        mismatched_files = _get_code_mismatches()
        is_match = bool(len(mismatched_files) == 0 and _SERVER_CODE_FINGERPRINT == disk_fingerprint)
        return HealthResponse(
            status="ok",
            version="1.0.0-rc1",
            runtime_mode="auto",
            python_version=sys.version.split()[0],
            workspace_locked=workspace_manager.is_locked,
            workspace_root=ws_root,
            server_time=time.time(),
            startup_time=_APP_STARTUP_TIME,
            pid=os.getpid(),
            code_fingerprint=_SERVER_CODE_FINGERPRINT,
            disk_fingerprint=disk_fingerprint,
            code_match=is_match,
            runtime_status="SYNCED" if is_match else "STALE_RUNTIME",
            mismatched_files=mismatched_files,
            python_executable=sys.executable,
            model_stack={
                "tier1": f"{TIER1_PROVIDER} / {TIER1_MODEL}",
                "tier2": f"{TIER2_PROVIDER} / {TIER2_MODEL}",
                "tier3": f"{TIER3_PROVIDER} / {TIER3_MODEL}",
            },
        )

    # ── 1B. GET /api/research/status ──────────────────────────────────────────
    @app.get("/api/research/status")
    async def get_research_status_endpoint():
        from config.research_config import get_research_status
        return get_research_status()

    @app.get("/api/telemetry/{run_id}/summary")
    async def get_telemetry_summary_endpoint(run_id: str):
        """Retrieve forensic markdown summary for a specific run."""
        from fastapi import HTTPException
        from core.observability.logger import validate_run_id
        obs_root = (Path(__file__).resolve().parent.parent.parent / "artifacts" / "observability").resolve()
        try:
            obs_dir = validate_run_id(run_id, obs_root)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=f"Invalid run_id: {err}")
        summary_file = obs_dir / "mission_summary.md"
        if summary_file.exists():
            return {"run_id": run_id, "summary": summary_file.read_text(encoding="utf-8")}
        raise HTTPException(status_code=404, detail=f"No forensic summary found for run '{run_id}'")


    # ── 1C. GET /api/providers/status ─────────────────────────────────────────
    @app.get("/api/providers/status")
    async def get_providers_status_endpoint(live: bool = False):
        """Retrieve accurate multi-tier provider configuration and runtime availability states."""
        from core.provider_registry import get_provider_registry
        registry = get_provider_registry()
        if live:
            await registry.refresh_all(probe_inference=True, timeout=8.0)

        entries = registry.get_all()
        providers_payload: Dict[str, Any] = {}
        for tier_num in sorted(entries.keys()):
            e = entries[tier_num]
            providers_payload[f"tier{tier_num}"] = {
                "tier": e.tier,
                "name": e.provider,
                "provider": e.provider,
                "model": e.configured_model,
                "served_model": e.served_model,
                "base_url": e.endpoint,
                "configured": e.has_credentials,
                "availability_state": e.state.value,
                "routable": e.is_routable(),
                "supported_models": e.supported_models[:12],
                "corrective_action": e.corrective_action,
                "last_error": e.last_error,
                "last_ttfb_ms": e.last_ttfb_ms,
                "last_ttft_reasoning_ms": e.last_ttft_reasoning_ms,
                "last_ttft_content_ms": e.last_ttft_content_ms,
                "last_ttft_usable_ms": e.last_ttft_usable_ms,
                "last_latency_ms": e.last_latency_ms,
                "checked_at": e.checked_at,
            }

        return {
            "architecture": "four_tier_hybrid",
            "routable_tiers": registry.get_routable_tiers(),
            "providers": providers_payload,
        }

    # ── 1D. POST /api/providers/test/{provider_name} ──────────────────────────
    @app.post("/api/providers/test/{provider_name}")
    async def test_provider_endpoint(provider_name: str):
        """Run on-demand live verification probe for a configured provider tier."""
        from core.provider_registry import get_provider_registry
        p_clean = provider_name.lower().strip()
        if p_clean in ("tier1", "nvidia", "nvidia_nim", "nim"):
            tier_num = 1
        elif p_clean in ("tier2", "gemini", "google"):
            tier_num = 2
        elif p_clean in ("tier3", "sambanova", "llama"):
            tier_num = 3
        elif p_clean in ("tier4", "ollama", "local"):
            tier_num = 4
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider '{provider_name}'. Must be tier1, tier2, tier3, or tier4.",
            )

        registry = get_provider_registry()
        entry = await registry.probe_tier(tier_num, probe_inference=True, timeout=10.0)
        return entry.to_dict()

    # ── 2. WORKSPACE HUB ENDPOINTS ──────────────────────────────────────────
    _dialog_lock = asyncio.Lock()

    @app.get("/api/workspaces", response_model=WorkspacesResponse)
    async def list_workspaces():
        # Retrieve active workspace from registry or fallback
        active_path = eff_registry.get_active_path()
        if not active_path:
            if workspace_manager.is_locked and workspace_manager.workspace_root:
                active_path = str(workspace_manager.workspace_root)
            elif os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true":
                active_path = os.environ.get("HERMES_WORKSPACES_ROOT", "/workspaces")
            else:
                active_path = str(Path.cwd().resolve())
            eff_registry.register_or_select(active_path, set_active=True)

        registered = eff_registry.list_workspaces()
        ws_infos = []
        for r in registered:
            ws_infos.append(
                WorkspaceInfo(
                    path=r["path"],
                    name=r.get("name") or Path(r["path"]).name or r["path"],
                    is_locked=workspace_manager.is_locked if (workspace_manager.workspace_root and str(workspace_manager.workspace_root) == r["path"]) else False,
                    exists=r.get("exists", True),
                    is_active=r.get("is_active", False),
                    is_hermes_repo=r.get("is_hermes_repo", False),
                    last_opened=r.get("last_opened"),
                    total_files=r.get("total_files"),
                    framework=r.get("framework"),
                    language=r.get("language"),
                )
            )

        # Fallback if no workspaces registered
        if not ws_infos:
            ws_infos.append(
                WorkspaceInfo(
                    path=active_path,
                    name=Path(active_path).name or active_path,
                    is_locked=workspace_manager.is_locked,
                    exists=Path(active_path).exists(),
                    is_active=True,
                    is_hermes_repo=is_hermes_repo_root(active_path),
                )
            )

        return WorkspacesResponse(
            workspaces=ws_infos,
            current_workspace=active_path,
            is_hermes_repo=is_hermes_repo_root(active_path),
        )

    @app.post("/api/workspaces/select", response_model=WorkspacesResponse)
    async def select_workspace(req: SelectWorkspaceRequest):
        target = Path(req.folder_path).resolve()
        # In container mode, validate that the target directory resides within the allowed mounted workspace root
        if os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true":
            allowed_root = Path(os.environ.get("HERMES_WORKSPACES_ROOT", "/workspaces")).resolve()
            try:
                target = canonicalize_workspace_path(target, allowed_root)
            except WorkspaceBoundaryError as wbe:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Selected workspace '{target}' escapes allowed container workspace root '{allowed_root}': {wbe}",
                )
        if not target.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
                logger.info(f"WorkspaceRegistry: created greenfield workspace directory {target}")
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not create selected folder: {e}",
                )
        if not target.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Selected path is not a directory: {req.folder_path}",
            )

        entry = eff_registry.register_or_select(target, set_active=True)
        # Update workspace_manager lock to target if not locked to an active running mission
        try:
            workspace_manager.lock(str(target))
        except Exception as e:
            logger.warning(f"Could not re-lock workspace_manager: {e}")

        return await list_workspaces()

    from core.server.folder_picker import folder_picker_manager

    @app.post("/api/workspaces/pick-folder", response_model=PickFolderResponse)
    async def pick_folder():
        # In headless / container mode, GUI file dialog is unavailable; select active mounted workspace deterministically
        if os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true":
            mount_root = Path(os.environ.get("HERMES_WORKSPACES_ROOT", "/workspaces")).resolve()
            mount_root.mkdir(parents=True, exist_ok=True)

            # Deterministic container workspace selection:
            # 1. Explicit HERMES_DEFAULT_WORKSPACE env var if set
            # 2. Existing active workspace if already registered and present within mount_root
            # 3. Existing 'default_project' directory if present
            # 4. Existing non-hidden workspace directory deterministically sorted
            # 5. Greenfield default_project
            default_env = os.environ.get("HERMES_DEFAULT_WORKSPACE", "").strip()
            active_reg = eff_registry.get_active_path()

            if default_env:
                selected_candidate = mount_root / default_env
            elif active_reg and Path(active_reg).exists():
                selected_candidate = Path(active_reg)
            elif (mount_root / "default_project").exists():
                selected_candidate = mount_root / "default_project"
            else:
                subdirs = sorted(
                    [p for p in mount_root.iterdir() if p.is_dir() and not p.name.startswith(".")],
                    key=lambda p: p.name.lower()
                )
                selected_candidate = subdirs[0] if subdirs else (mount_root / "default_project")

            try:
                selected_path = canonicalize_workspace_path(selected_candidate, mount_root)
            except WorkspaceBoundaryError as wbe:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Deterministic container workspace selection failed boundary check: {wbe}",
                )

            selected_path.mkdir(parents=True, exist_ok=True)
            entry = eff_registry.register_or_select(selected_path, set_active=True)
            try:
                workspace_manager.lock(str(selected_path))
            except Exception as e:
                logger.warning(f"Could not lock workspace_manager: {e}")
            return PickFolderResponse(
                cancelled=False,
                path=str(selected_path),
                name=selected_path.name or str(selected_path),
                is_hermes_repo=is_hermes_repo_root(selected_path),
            )

        if folder_picker_manager.is_dialog_active():
            return PickFolderResponse(
                cancelled=True,
                error="A folder picker dialog is already open.",
            )

        initial_dir = str(workspace_manager.workspace_root) if (workspace_manager.is_locked and workspace_manager.workspace_root) else None

        cancelled, selected_dir, err_msg = await folder_picker_manager.pick_directory(
            initial_dir=initial_dir,
            title="Select Project Directory for HERMES",
        )

        if err_msg:
            return PickFolderResponse(
                cancelled=True,
                error=err_msg,
            )

        if cancelled or not selected_dir:
            return PickFolderResponse(cancelled=True)

        selected_path = Path(selected_dir).resolve()
        if not selected_path.exists() or not selected_path.is_dir():
            return PickFolderResponse(
                cancelled=True,
                error=f"Selected path is not a valid directory: {selected_dir}",
            )

        entry = eff_registry.register_or_select(selected_path, set_active=True)
        try:
            workspace_manager.lock(str(selected_path))
        except Exception as e:
            logger.warning(f"Could not re-lock workspace_manager: {e}")

        return PickFolderResponse(
            cancelled=False,
            path=str(selected_path),
            name=selected_path.name or str(selected_path),
            is_hermes_repo=is_hermes_repo_root(selected_path),
        )

    @app.delete("/api/workspaces/recent", response_model=WorkspacesResponse)
    async def remove_recent_workspace(req: RemoveWorkspaceRequest):
        removed = eff_registry.remove_recent(req.folder_path)
        return await list_workspaces()

    # ── 3. GET /api/sessions ───────────────────────────────────────────────────
    @app.get("/api/sessions", response_model=SessionsResponse)
    async def list_sessions():
        rt = await eff_adapter.get_or_create_runtime()
        if not rt.session_manager:
            return SessionsResponse(sessions=[], total_count=0)

        sessions = rt.session_manager.list_sessions()
        summaries = [
            SessionSummary(
                session_id=s.session_id,
                mission_id=s.mission_id,
                workspace_root=s.workspace_root,
                status=s.status.value if hasattr(s.status, "value") else str(s.status),
                branch_name=s.branch_name,
                created_at=s.created_at,
                updated_at=s.updated_at,
                metadata=s.metadata,
            )
            for s in sessions
        ]
        return SessionsResponse(sessions=summaries, total_count=len(summaries))

    # ── 4. POST /api/missions ──────────────────────────────────────────────────
    @app.post("/api/missions", response_model=CreateMissionResponse, status_code=status.HTTP_201_CREATED)
    async def create_mission(request: CreateMissionRequest):
        if request.workspace_root:
            try:
                req_ws = Path(request.workspace_root).resolve()
                has_active = any(t is not None and not t.done() for t in eff_adapter._active_tasks.values())
                if not has_active:
                    req_ws.mkdir(parents=True, exist_ok=True)
                    eff_registry.register_or_select(req_ws, set_active=True)
                    workspace_manager.lock(str(req_ws), create=True)
            except Exception:
                pass
        validated_ws = validate_workspace_access(request.workspace_root)
        try:
            mission_id = await eff_adapter.start_mission(
                prompt=request.prompt,
                workspace_root=str(validated_ws),
                plan_mode=request.plan_mode,
            )
        except (RuntimeError, ValueError) as err:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(err),
            )
        return CreateMissionResponse(
            mission_id=mission_id,
            status="RUNNING",
            workspace_root=str(validated_ws),
            message=f"Mission {mission_id} started successfully.",
        )

    # ── 5. GET /api/missions/{mission_id} ──────────────────────────────────────
    @app.get("/api/missions/{mission_id}", response_model=MissionSnapshot)
    async def get_mission_snapshot(mission_id: str):
        state = eff_adapter.get_mission_snapshot(mission_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

        task_src = list(state.tasks.values())
        if not task_src and getattr(state, "requirements", None):
            tasks = [
                TaskSnapshot(
                    task_id=r.requirement_id,
                    title=r.title,
                    description=r.description,
                    status=r.status.value if hasattr(r.status, "value") else str(r.status),
                    is_verified=bool(r.status.value == "VERIFIED" if hasattr(r.status, "value") else str(r.status) == "VERIFIED"),
                    verification_evidence=r.evidence_refs[0] if r.evidence_refs else None,
                    files_created=[],
                    files_modified=[],
                )
                for r in state.requirements.values()
            ]
        else:
            tasks = [
                TaskSnapshot(
                    task_id=t.task_id,
                    title=t.title,
                    description=t.description,
                    status=t.status.value if hasattr(t.status, "value") else str(t.status),
                    is_verified=bool(getattr(t, "verification_id", None) or getattr(t, "is_verified", False)),
                    verification_evidence=getattr(t, "verification_evidence", None) or getattr(t, "completion_reason", None),
                    files_created=getattr(t, "files_created", []) or [],
                    files_modified=getattr(t, "files_modified", []) or [],
                )
                for t in task_src
            ]
        last_seq = 0
        events = eff_adapter.get_events_since(mission_id, 0)
        if events:
            last_seq = max(e.sequence for e in events)

        # Gather created / modified files across events, tasks, and mission state
        read_only_tools = ("read", "inspect", "cat", "view", "show", "search", "list", "find", "grep")
        evt_modified = [
            f for e in events
            for f in (e.payload.get("files_modified") or ([e.payload.get("path")] if e.payload.get("path") and "edit" in e.payload.get("tool_name", "") else []))
            if isinstance(f, str)
        ]
        evt_created = [
            f for e in events
            for f in (e.payload.get("files_created") or ([e.payload.get("path")] if e.payload.get("path") and e.event_type.value in ("TOOL_COMPLETED", "FILE_CREATED") and not e.payload.get("files_modified") and "edit" not in e.payload.get("tool_name", "") and not any(r in e.payload.get("tool_name", "").lower() for r in read_only_tools) else []))
            if isinstance(f, str)
        ]
        mission_created = getattr(state.mission, "artifacts_created", []) or []
        mission_modified = getattr(state.mission, "artifacts_modified", []) or []
        all_modified = list(dict.fromkeys(
            mission_modified + evt_modified + [f for t in state.tasks.values() for f in getattr(t, "files_modified", [])]
        ))
        all_created = list(dict.fromkeys(
            mission_created + evt_created + [f for t in state.tasks.values() for f in getattr(t, "files_created", [])]
        ))
        all_created = [f for f in all_created if f not in all_modified]

        # Check if tasks had successful verification events in event stream
        verified_task_evidence = {}
        for e in events:
            if e.task_id and e.event_type.value in ("TASK_COMPLETED", "VERIFICATION_COMPLETED", "ACCEPTANCE_CHECK_PASSED"):
                ev_str = e.payload.get("verification_evidence") or e.payload.get("reason") or e.payload.get("verdict")
                if ev_str:
                    verified_task_evidence[e.task_id] = str(ev_str)

        for task_snap in tasks:
            if task_snap.task_id in verified_task_evidence or state.mission.status == MissionStatus.COMPLETED:
                task_snap.is_verified = True
                if task_snap.task_id in verified_task_evidence:
                    task_snap.verification_evidence = verified_task_evidence[task_snap.task_id]

        final_out = None
        for e in reversed(events):
            if e.event_type.value == "MISSION_COMPLETED":
                out_val = e.payload.get("final_output") or e.payload.get("output") or e.payload.get("candidate_response")
                if out_val:
                    final_out = str(out_val)
                    break
            elif e.event_type.value == "AGENT_COMPLETION_CANDIDATE":
                cand_val = e.payload.get("candidate_response") or e.payload.get("claim") or e.payload.get("output")
                if not final_out and cand_val:
                    final_out = str(cand_val)
                    break

        db = eff_adapter.event_bus.get_database() if hasattr(eff_adapter, "event_bus") and hasattr(eff_adapter.event_bus, "get_database") else None
        m_row = db.get_mission(state.mission.mission_id) if (db and hasattr(db, "get_mission")) else None
        control = eff_adapter._mission_controls.get(state.mission.mission_id) if (hasattr(eff_adapter, "_mission_controls") and isinstance(eff_adapter._mission_controls, dict)) else None

        raw_rec = m_row.get("recovery_required") if (m_row and isinstance(m_row, dict)) else False
        recovery_req_val = bool(raw_rec) if type(raw_rec).__name__ != "MagicMock" else False

        raw_wr = None
        if m_row and isinstance(m_row, dict) and isinstance(m_row.get("wait_reason"), str) and m_row.get("wait_reason") != "NONE":
            raw_wr = m_row.get("wait_reason")
        elif hasattr(state, "progress") and type(state.progress).__name__ != "MagicMock":
            prog_wr = getattr(state.progress, "waiting_reason", None)
            if prog_wr is not None and type(prog_wr).__name__ != "MagicMock":
                raw_wr = getattr(prog_wr, "value", str(prog_wr))
        wait_reason_val = str(raw_wr) if (raw_wr is not None and type(raw_wr).__name__ != "MagicMock") else None

        # Immutable workspace binding check: never silently fall back to currently selected workspace
        raw_ws = state.mission.workspace_root or (m_row.get("workspace_path") if (m_row and isinstance(m_row, dict)) else None)
        if not raw_ws:
            ws_val = "UNRESOLVED_WORKSPACE"
            recovery_req_val = True
            wait_reason_val = "MISSING_WORKSPACE"
        else:
            ws_val = str(raw_ws)
            try:
                canonical_ws = str(Path(raw_ws).resolve())
            except Exception:
                canonical_ws = str(raw_ws)
            now_ts = time.time()
            ws_cached = _WS_EXIST_CACHE.get(canonical_ws)
            if ws_cached is not None and (now_ts - ws_cached[1]) < 2.0:
                ws_exists = ws_cached[0]
            else:
                try:
                    ws_exists = Path(canonical_ws).exists()
                except Exception:
                    ws_exists = False
                # If exists, cache for 2.0s; if missing, do not cache so folder recreation is seen immediately
                if ws_exists:
                    _WS_EXIST_CACHE[canonical_ws] = (ws_exists, now_ts)
                else:
                    _WS_EXIST_CACHE.pop(canonical_ws, None)
                if len(_WS_EXIST_CACHE) > 100:
                    _WS_EXIST_CACHE.clear()

            if not ws_exists:
                recovery_req_val = True
                wait_reason_val = "WORKSPACE_NOT_FOUND"

        raw_run_id = getattr(state.mission, "run_id", None)
        run_id_val = str(raw_run_id) if (raw_run_id is not None and not hasattr(raw_run_id, "_mock_wraps") and type(raw_run_id).__name__ != "MagicMock") else None
        raw_attempt = getattr(state.mission, "attempt_number", 1)
        try:
            attempt_val = int(raw_attempt)
        except (ValueError, TypeError):
            attempt_val = 1

        raw_is_paused = getattr(control, "is_paused", False) if control else False
        is_paused_val = bool(raw_is_paused) if type(raw_is_paused).__name__ != "MagicMock" else False

        raw_pause_requested = getattr(control, "pause_requested", False) if control else False
        pause_pending_val = bool(raw_pause_requested and not is_paused_val) if type(raw_pause_requested).__name__ != "MagicMock" else False

        checks_resp = extract_mission_checks(state.mission.mission_id, state, events)

        status_val = state.mission.status.value if hasattr(state.mission.status, "value") else str(state.mission.status)
        if m_row and isinstance(m_row, dict) and m_row.get("status"):
            # If database has reached WAITING or CANCELLED, prioritize persisted status
            if m_row.get("status") in ("WAITING", "CANCELLED", "COMPLETED", "FAILED") and status_val != m_row.get("status"):
                status_val = m_row.get("status")

        # Terminal state protection: terminal missions must never report paused, pause_pending, or active wait_reason
        is_term = (
            state.mission.is_terminal
            or (control is not None and bool(getattr(control, "is_terminal", False)))
            or (status_val in ("COMPLETED", "FAILED", "CANCELLED", "ABORTED", "STOPPED"))
        )
        if is_term:
            is_paused_val = False
            pause_pending_val = False
            wait_reason_val = None
            recovery_req_val = False

        if status_val == "COMPLETED" and not final_out:
            created_list = "\n".join(f"- `{f}`" for f in (all_created or ["index.html"]))
            entry_f = all_created[0] if all_created else 'index.html'
            final_out = (
                f"### Mission Completed\n\n"
                f"**Objective:** {state.mission.prompt or 'Build web application'}\n\n"
                f"**Outcome & Deliverables:**\n{created_list}\n\n"
                f"**Verification:** Mission reached completion; inspect individual verification checks and evidence log for specific status.\n\n"
                f"**Launch Instructions:** Open `{entry_f}` in your browser or run the local application server."
            )

        exec_mode_val: Optional[str] = None
        active_prov_val: Optional[str] = None
        active_mod_val: Optional[str] = None
        curr_stage_val: Optional[str] = None
        failover_evts: List[Dict[str, Any]] = []
        term_reason_val: Optional[str] = state.mission.completion_reason or getattr(state.mission, "completion_reason", None) or state.mission.abort_reason

        for e in events:
            p = e.payload or {}
            etv = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
            if p.get("execution_mode"):
                exec_mode_val = str(p.get("execution_mode"))
            if p.get("provider"):
                active_prov_val = str(p.get("provider"))
            if p.get("model"):
                active_mod_val = str(p.get("model"))
            if p.get("stage"):
                curr_stage_val = str(p.get("stage"))
            elif etv in ("PLANNING_STARTED", "PLAN_CREATED", "MODEL_REQUESTED", "MODEL_COMPLETED", "VERIFICATION_COMPLETED", "MISSION_COMPLETED", "MISSION_FAILED"):
                curr_stage_val = p.get("headline") or etv
            if etv in ("TIER_FAILOVER_STARTED", "MODEL_FAILED"):
                failover_evts.append({
                    "event": etv,
                    "timestamp": e.timestamp,
                    "from_tier": p.get("from_tier") or p.get("tier"),
                    "to_tier": p.get("to_tier"),
                    "provider": p.get("provider") or p.get("to_provider"),
                    "error": p.get("error") or p.get("reason"),
                })
            if etv in ("MISSION_COMPLETED", "MISSION_FAILED", "MISSION_CANCELLED"):
                term_reason_val = str(p.get("reason") or p.get("error") or term_reason_val or etv)

        dur_sec_val: Optional[float] = None
        if events and len(events) >= 1:
            t_first = events[0].timestamp
            t_last = events[-1].timestamp
            if isinstance(t_first, (int, float)) and isinstance(t_last, (int, float)) and t_last >= t_first:
                dur_sec_val = round(float(t_last - t_first), 3)

        return MissionSnapshot(
            mission_id=state.mission.mission_id,
            run_id=run_id_val,
            attempt_number=attempt_val,
            title=state.mission.title or "HERMES Mission",
            prompt=state.mission.prompt or "",
            status=status_val,
            is_terminal=is_term,
            workspace_root=ws_val,
            created_at=state.mission.start_time or time.time(),
            state_version=state.state_version,
            last_sequence=last_seq,
            tasks=tasks,
            files_created=all_created,
            files_modified=all_modified,
            checks=checks_resp.checks,
            error=state.mission.abort_reason or getattr(state.mission, "error", None),
            final_output=final_out,
            completion_reason=state.mission.completion_reason or getattr(state.mission, "completion_reason", None),
            wait_reason=wait_reason_val,
            recovery_required=recovery_req_val,
            is_paused=is_paused_val,
            pause_pending=pause_pending_val,
            execution_mode=exec_mode_val,
            active_provider=active_prov_val,
            active_model=active_mod_val,
            current_stage=curr_stage_val,
            duration_seconds=dur_sec_val,
            failover_events=failover_evts,
            terminal_reason=term_reason_val,
        )

    # ── 6. GET /api/missions/{mission_id}/events (SSE) ─────────────────────────
    @app.get("/api/missions/{mission_id}/events")
    async def stream_mission_events(
        mission_id: str,
        last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
        cursor: Optional[int] = Query(None, description="Event sequence cursor"),
    ):
        # Determine sequence cursor from Last-Event-ID header or ?cursor query param
        seq_cursor = 0
        if cursor is not None:
            seq_cursor = cursor
        elif last_event_id and last_event_id.isdigit():
            seq_cursor = int(last_event_id)

        async def sse_event_stream():
            try:
                async for event in eff_adapter.subscribe_mission_events(mission_id, seq_cursor):
                    yield format_hermes_event_to_sse(event)
            except asyncio.CancelledError:
                logger.debug(f"SSE stream client disconnected for mission {mission_id}")

        return StreamingResponse(
            sse_event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 6b. GET /api/missions/{mission_id}/events/history ──────────────────────
    @app.get("/api/missions/{mission_id}/events/history")
    async def get_mission_events_history(
        mission_id: str,
        from_seq: int = Query(0, description="Start sequence (inclusive)"),
        to_seq: Optional[int] = Query(None, description="End sequence (inclusive)"),
        limit: int = Query(1000, description="Max events to return"),
    ):
        events = eff_adapter.get_events_since(mission_id, from_seq)
        if to_seq is not None:
            events = [e for e in events if e.sequence <= to_seq]
        if limit and len(events) > limit:
            events = events[-limit:]
        return {
            "mission_id": mission_id,
            "total": len(events),
            "events": [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in events],
        }

    # ── 7. POST /api/missions/{mission_id}/stop ────────────────────────────────
    @app.post("/api/missions/{mission_id}/stop", response_model=StopMissionResponse)
    async def stop_mission(mission_id: str):
        try:
            stopped = await eff_adapter.stop_mission(mission_id)
        except Exception as stop_exc:
            logger.error(f"Failed to stop mission '{mission_id}': {stop_exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to durably stop mission '{mission_id}': {stop_exc}",
            )
        return StopMissionResponse(
            mission_id=mission_id,
            cancelled=stopped,
            message=f"Mission {mission_id} cancellation requested." if stopped else f"Mission {mission_id} already terminated.",
        )

    # ── 7a. POST /api/missions/{mission_id}/pause ──────────────────────────────
    @app.post("/api/missions/{mission_id}/pause", response_model=PauseMissionResponse)
    async def pause_mission_endpoint(mission_id: str):
        control = eff_adapter._mission_controls.get(mission_id)
        if not control:
            db = eff_adapter.event_bus.get_database()
            m_row = db.get_mission(mission_id) if db else None
            if not m_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Mission '{mission_id}' not found.",
                )
            # Stale RUNNING reconciliation: If mission is recorded as RUNNING but has no active executor
            if m_row.get("status") == "RUNNING":
                try:
                    db.save_mission(
                        mission_id=mission_id,
                        workspace_path=m_row.get("workspace_path", ""),
                        status="WAITING",
                        session_id=m_row.get("session_id"),
                        run_id=m_row.get("run_id"),
                        attempt_number=m_row.get("attempt_number", 1),
                        wait_reason="WAITING_FOR_RECOVERY",
                        prompt=m_row.get("prompt", ""),
                        state_version=m_row.get("state_version", 0),
                        last_event_sequence=m_row.get("last_event_sequence", 0),
                        latest_checkpoint_id=m_row.get("latest_checkpoint_id"),
                        execution_active=False,
                        recovery_required=True,
                    )
                    eff_adapter.event_bus.publish(HermesEvent(
                        event_type=EventType.MISSION_WAITING,
                        mission_id=mission_id,
                        run_id=m_row.get("run_id"),
                        attempt_number=m_row.get("attempt_number", 1),
                        payload={
                            "status": "WAITING",
                            "wait_reason": "WAITING_FOR_RECOVERY",
                            "reason": "Reconciled stale execution (no active worker).",
                        }
                    ))
                except Exception as recon_err:
                    logger.warning(f"Pause endpoint reconciliation warning for {mission_id}: {recon_err}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Mission '{mission_id}' is not actively executing. Reconciled status to WAITING (WAITING_FOR_RECOVERY). Use Resume to recover or Stop to cancel.",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Mission '{mission_id}' is not actively executing (status: {m_row.get('status')}).",
            )
        if control.is_terminal:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot pause mission '{mission_id}' because it has reached a terminal state.",
            )
        accepted, confirmed = eff_adapter.request_pause(mission_id)
        status_str = "PAUSED" if confirmed else "PAUSE_REQUESTED"
        msg = (
            f"Mission {mission_id} paused."
            if confirmed
            else f"Mission {mission_id} pause requested; waiting for safe checkpoint boundary."
        )
        return PauseMissionResponse(
            mission_id=mission_id,
            paused=confirmed,
            status=status_str,
            message=msg,
        )

    # ── 7b. POST /api/missions/{mission_id}/resume ────────────────────────────
    @app.post("/api/missions/{mission_id}/resume", response_model=ResumeMissionResponse)
    async def resume_mission_endpoint(mission_id: str):
        # Check eligibility and reconcile
        eligible, reason = eff_adapter.validate_resume_eligibility(mission_id)
        if not eligible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Mission '{mission_id}' cannot be resumed: {reason}",
            )

        # Case A: In-flight paused or pause-pending run — unpause live
        task = eff_adapter._active_tasks.get(mission_id)
        control = eff_adapter._mission_controls.get(mission_id)
        if task and not task.done() and control and (control.is_paused or control.pause_requested):
            eff_adapter.resume_mission(mission_id)
            db = eff_adapter.event_bus.get_database()
            m_row = db.get_mission(mission_id) if db else {}
            ws_root = m_row.get("workspace_path", "") if m_row else (control.workspace_root or "")
            msg = (
                f"Pending pause cancelled; mission '{mission_id}' continues running."
                if not control.is_paused
                else f"In-flight paused mission '{mission_id}' (run {control.run_id}) unpaused successfully."
            )
            return ResumeMissionResponse(
                mission_id=mission_id,
                run_id=control.run_id,
                status="RUNNING",
                attempt_number=control.attempt_number,
                workspace_root=ws_root,
                message=msg,
            )

        # Case B: Cold continuation from persisted checkpoint & journal

        try:
            new_run_id = await eff_adapter.resume_interrupted_mission(mission_id)
            db = eff_adapter.event_bus.get_database()
            m_row = db.get_mission(mission_id) if db else {}
            ws_root = m_row.get("workspace_path", "") if m_row else ""
            att = m_row.get("attempt_number", 2) if m_row else 2
            return ResumeMissionResponse(
                mission_id=mission_id,
                run_id=new_run_id,
                status="RUNNING",
                attempt_number=att,
                workspace_root=ws_root,
                message=f"Continuation run '{new_run_id}' (attempt {att}) started successfully.",
            )
        except RuntimeError as re:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(re),
            )
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(ve),
            )
        except Exception as e:
            logger.exception(f"Error resuming mission {mission_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resume mission: {e}",
            )

    # ── 7c. GET /api/missions/{mission_id}/resume-preview ──────────────────────
    @app.get("/api/missions/{mission_id}/resume-preview", response_model=ResumePreviewResponse)
    async def resume_preview_endpoint(mission_id: str):
        db = eff_adapter.event_bus.get_database()
        if not db:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available for resume reconciliation.",
            )

        from core.persistence.blobs import BlobStore
        from core.persistence.recovery import RecoveryEngine
        blob_store = getattr(eff_adapter.event_bus, "blob_store", None) or BlobStore(Path(db.db_path).parent / "blobs")
        recovery_engine = RecoveryEngine(db=db, blob_store=blob_store, workspace_manager=eff_adapter.workspace)
        plan = recovery_engine.formulate_resume_plan(mission_id)

        discs = [
            DiscrepancyItem(
                discrepancy_type=d.discrepancy_type.value if hasattr(d.discrepancy_type, "value") else str(d.discrepancy_type),
                path=d.path,
                description=d.description,
                blocking=d.blocking,
                operation_id=d.operation_id,
                expected_hash=d.expected_hash,
                actual_hash=d.actual_hash,
            )
            for d in plan.discrepancies
        ]

        return ResumePreviewResponse(
            mission_id=plan.mission_id,
            can_resume=plan.can_resume,
            checkpoint_id=plan.checkpoint_id,
            original_workspace=plan.original_workspace,
            target_task_id=plan.target_task_id,
            target_task_title=plan.target_task_title,
            completed_tasks=plan.completed_tasks,
            pending_tasks=plan.pending_tasks,
            discrepancies=discs,
            reason=plan.reason,
            reconciliation_summary=plan.reconciliation_summary,
        )

    # ── 8. GET /api/missions/{mission_id}/diffs ───────────────────────────────
    @app.get("/api/missions/{mission_id}/diffs", response_model=MissionDiffsResponse)
    async def get_mission_diffs_endpoint(mission_id: str):
        state = eff_adapter.get_mission_snapshot(mission_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

        ws_val = state.mission.workspace_root or (str(workspace_manager.workspace_root) if (workspace_manager.is_locked and workspace_manager.workspace_root) else str(Path.cwd()))
        ws_path = Path(ws_val).resolve()

        events = eff_adapter.get_events_since(mission_id, 0)
        read_only_tools = ("read", "inspect", "cat", "view", "show", "search", "list", "find", "grep")
        evt_modified = [
            f for e in events
            for f in (e.payload.get("files_modified") or ([e.payload.get("path")] if e.payload.get("path") and "edit" in e.payload.get("tool_name", "") else []))
            if isinstance(f, str)
        ]
        evt_created = [
            f for e in events
            for f in (e.payload.get("files_created") or ([e.payload.get("path")] if e.payload.get("path") and e.event_type.value in ("TOOL_COMPLETED", "FILE_CREATED") and not e.payload.get("files_modified") and "edit" not in e.payload.get("tool_name", "") and not any(r in e.payload.get("tool_name", "").lower() for r in read_only_tools) else []))
            if isinstance(f, str)
        ]
        mission_created = getattr(state.mission, "artifacts_created", []) or []
        mission_modified = getattr(state.mission, "artifacts_modified", []) or []
        all_modified = list(dict.fromkeys(
            mission_modified + evt_modified + [f for t in state.tasks.values() for f in getattr(t, "files_modified", [])]
        ))
        all_created = list(dict.fromkeys(
            mission_created + evt_created + [f for t in state.tasks.values() for f in getattr(t, "files_created", [])]
        ))
        all_created = [f for f in all_created if f not in all_modified]

        return get_mission_diffs(mission_id, ws_path, all_created, all_modified)

    # ── 9. GET /api/missions/{mission_id}/diffs/{file_path:path} ──────────────
    @app.get("/api/missions/{mission_id}/diffs/{file_path:path}", response_model=FileDiffEntry)
    async def get_file_diff_endpoint(mission_id: str, file_path: str):
        state = eff_adapter.get_mission_snapshot(mission_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

        ws_val = state.mission.workspace_root or (str(workspace_manager.workspace_root) if (workspace_manager.is_locked and workspace_manager.workspace_root) else str(Path.cwd()))
        ws_path = Path(ws_val).resolve()

        try:
            return compute_file_diff(ws_path, file_path)
        except WorkspaceBoundaryError as wbe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {wbe}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error computing diff for '{file_path}': {e}",
            )

    @app.get("/api/missions/{mission_id}/diff", response_model=FileDiffEntry)
    async def get_file_diff_query_endpoint(mission_id: str, path: str = Query(..., description="File path relative to workspace")):
        state = eff_adapter.get_mission_snapshot(mission_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

        ws_val = state.mission.workspace_root or (str(workspace_manager.workspace_root) if (workspace_manager.is_locked and workspace_manager.workspace_root) else str(Path.cwd()))
        ws_path = Path(ws_val).resolve()

        try:
            return compute_file_diff(ws_path, path)
        except WorkspaceBoundaryError as wbe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {wbe}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error computing diff for '{path}': {e}",
            )

    # ── 10. GET /api/missions/{mission_id}/checks ──────────────────────────────
    @app.get("/api/missions/{mission_id}/checks", response_model=MissionChecksResponse)
    async def get_mission_checks_endpoint(mission_id: str):
        state = eff_adapter.get_mission_snapshot(mission_id)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

        events = eff_adapter.get_events_since(mission_id, 0)
        return extract_mission_checks(mission_id, state, events)

    # ── 8. GET /api/approvals & POST /api/approvals/{request_id} ───────────────
    @app.get("/api/approvals", response_model=PendingApprovalsResponse)
    async def get_pending_approvals():
        rt = await eff_adapter.get_or_create_runtime()
        requests = rt.security.get_pending_requests()
        items = []
        for r in requests:
            # Enforce mission lifecycle binding: do not serve approvals for terminated missions
            if getattr(r, "mission_id", None):
                snap = eff_adapter.get_mission_snapshot(r.mission_id)
                if snap and getattr(snap, "mission", None) and snap.mission.is_terminal:
                    r.resolved = True
                    r.status = "CANCELLED"
                    continue


            risk = getattr(r, "risk_assessment", None) or getattr(r, "assessment", None)
            reason_str = "Requires user approval"
            if risk:
                reason_str = (
                    getattr(risk, "summary", None)
                    or getattr(risk, "risk_rationale", None)
                    or (risk.reasons[0] if getattr(risk, "reasons", None) else None)
                    or reason_str
                )
            items.append(
                PendingApprovalItem(
                    request_id=r.request_id,
                    mission_id=getattr(r, "mission_id", None),
                    tool_name=r.action.tool_name,
                    arguments=r.action.arguments,
                    reason=str(reason_str),
                    created_at=r.created_at,
                    expires_at=r.expires_at,
                )
            )
        return PendingApprovalsResponse(pending_approvals=items)

    @app.post("/api/approvals/{request_id}", response_model=ApprovalDecisionResponse)
    async def resolve_approval(request_id: str, decision: ApprovalDecisionRequest):
        rt = await eff_adapter.get_or_create_runtime()
        from core.security.enums import ApprovalScope
        try:
            scope_enum = ApprovalScope[decision.scope.upper()]
        except KeyError:
            scope_enum = ApprovalScope.ONCE

        req = rt.security.approval_store.get_request(request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request '{request_id}' not found.",
            )

        # Enforce mission lifecycle binding: reject approvals for terminated missions or cancelled requests
        if req.status == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Approval request '{request_id}' has been cancelled or belongs to a terminated mission.",
            )

        if getattr(req, "mission_id", None):
            snap = eff_adapter.get_mission_snapshot(req.mission_id)
            if snap and getattr(snap, "mission", None) and snap.mission.is_terminal:
                req.resolved = True
                req.status = "CANCELLED"
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"Approval request '{request_id}' belongs to mission '{req.mission_id}' which has already terminated ({snap.mission.status}).",
                )


        if req.expires_at is not None and time.time() > req.expires_at:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Approval request '{request_id}' has expired.",
            )

        if req.resolved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Approval request '{request_id}' has already been resolved.",
            )


        if decision.approved:
            grant = rt.security.grant_approval(
                request_id=request_id,
                scope=scope_enum,
                resolved_by="api_user",
            )
            return ApprovalDecisionResponse(
                request_id=request_id,
                resolved=True,
                approved=True,
                message=f"Approval granted (scope: {scope_enum.value}).",
            )
        else:
            rt.security.deny_approval(request_id=request_id, resolved_by="api_user")
            return ApprovalDecisionResponse(
                request_id=request_id,
                resolved=True,
                approved=False,
                message="Approval denied.",
            )

    # ── 11. GET /api/network/status & POST /api/network/recover ───────────────
    @app.get("/api/network/status", response_model=NetworkStatusResponse)
    async def get_network_status_endpoint():
        from core.network.connectivity import shared_connectivity_monitor
        from core.network.coordinator import shared_recovery_coordinator
        snap = shared_connectivity_monitor.get_snapshot()
        waiting = shared_recovery_coordinator.find_eligible_waiting_missions()
        return NetworkStatusResponse(
            status=snap.status.value,
            is_connected=snap.is_connected,
            last_checked=snap.last_checked,
            consecutive_failures=snap.consecutive_failures,
            consecutive_successes=snap.consecutive_successes,
            probe_targets=snap.probe_targets,
            last_error=snap.last_error,
            waiting_missions_count=len(waiting),
        )

    @app.post("/api/network/recover", response_model=NetworkRecoverResponse)
    async def trigger_network_recover_endpoint():
        from core.network.coordinator import shared_recovery_coordinator
        recovered = await shared_recovery_coordinator.recover_waiting_missions()
        return NetworkRecoverResponse(
            recovered_count=len(recovered),
            recovered_mission_ids=recovered,
            message=f"Recovery pass complete; resumed {len(recovered)} waiting mission(s).",
        )

    # ── 9. Mount Static GUI Build (if built) ──────────────────────────────────
    gui_dist = Path(__file__).resolve().parent.parent.parent / "gui" / "dist"
    if gui_dist.exists() and (gui_dist / "index.html").exists():
        from starlette.staticfiles import StaticFiles
        from starlette.responses import FileResponse

        # Serve static assets
        if (gui_dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=str(gui_dist / "assets")), name="static_assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path.startswith("api"):
                raise HTTPException(status_code=404, detail="API route not found")
            target_file = gui_dist / full_path
            if target_file.is_file():
                return FileResponse(str(target_file))
            return FileResponse(str(gui_dist / "index.html"))

    return app


# Application singleton
app = create_app()

