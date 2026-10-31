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
import uuid
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

# Security Platform integration (Prompt 13)
from core.security.gate import SecurityGate
from core.security.enums import PermissionOutcome as SecPermissionOutcome, ContentTrust

_IGNORED_SCAN_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "venv", ".venv", "__pycache__",
    ".cache", ".next", ".nuxt", "dist", "build", "coverage", ".idea", ".vscode"
}


def _scan_workspace_files(ws_root: Path, max_files: int = 5000) -> Set[str]:
    """
    Fast workspace file scanner that prunes vendor, venv, and VCS directories.
    Runs in bounded time to never block the asyncio event loop.
    """
    if not ws_root.exists() or not ws_root.is_dir():
        return set()
    found = set()
    root_str = str(ws_root)
    for dirpath, dirnames, filenames in os.walk(root_str):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_SCAN_DIRS and not d.startswith(".")]
        for fn in filenames:
            found.add(os.path.join(dirpath, fn))
            if len(found) >= max_files:
                return found
    return found


def format_tool_headline(
    tool_name: str,
    args: Dict[str, Any],
    is_completed: bool = False,
    success: bool = True,
    obs: Optional[Any] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Format Antigravity-style human-readable headlines and diff stats for tool operations.
    Examples:
      - Ran inspect git branch commit and status
      - Analyzed app.py #L1-50
      - Created index.html +120 -0
      - Modified styles.css +15 -3
      - Searched files 'src/**/*.ts'
      - Searched text 'function render'
      - Browser evaluation http://127.0.0.1:8765
    """
    name = (tool_name or "").lower()
    path = args.get("path") or args.get("file_path") or args.get("target_path") or args.get("file") or ""
    basename = Path(path).name if path else ""
    diff_stat: Optional[Dict[str, Any]] = None

    if "shell" in name or "bash" in name or "command" in name or "powershell" in name:
        cmd = args.get("command") or args.get("cmd") or ""
        cmd_first = cmd.strip().split("\n")[0][:65] if cmd else ""
        headline = f"Ran {cmd_first}" if cmd_first else f"Ran {tool_name}"
        return headline, diff_stat

    if "read" in name or "view" in name or "cat" in name:
        start = args.get("start_line") or args.get("start")
        end = args.get("end_line") or args.get("end")
        line_range = f" #L{start}-{end}" if (start and end) else ""
        headline = f"Analyzed {basename}{line_range}" if basename else f"Analyzed {tool_name}"
        return headline, diff_stat

    if "write" in name or "create" in name:
        content = args.get("content") or args.get("text") or ""
        line_count = len(content.splitlines()) if content else 0
        is_new = True
        if obs and getattr(obs, "metadata", None):
            prior_hash = obs.metadata.get("prior_hash")
            if prior_hash:
                is_new = False
        if is_new:
            diff_stat = {"added": line_count, "deleted": 0, "is_new": True}
            headline = f"Created {basename} +{line_count} -0" if basename else "Created file"
        else:
            diff_stat = {"added": line_count, "deleted": 0, "is_new": False}
            headline = f"Modified {basename} +{line_count} -0" if basename else "Modified file"
        return headline, diff_stat

    if "edit" in name or "replace" in name or "patch" in name:
        old_str = args.get("old_str") or args.get("target") or ""
        new_str = args.get("new_str") or args.get("replacement") or ""
        added = len(new_str.splitlines()) if new_str else 0
        deleted = len(old_str.splitlines()) if old_str else 0
        diff_stat = {"added": added, "deleted": deleted, "is_new": False}
        headline = f"Modified {basename} +{added} -{deleted}" if basename else "Modified file"
        return headline, diff_stat

    if "glob" in name:
        pattern = args.get("pattern") or ""
        headline = f"Searched files '{pattern}'" if pattern else "Searched files"
        return headline, diff_stat

    if "grep" in name:
        pattern = args.get("pattern") or ""
        headline = f"Searched text '{pattern[:40]}'" if pattern else "Searched text"
        return headline, diff_stat

    if "list" in name or "ls" in name or "dir" in name:
        target = basename or (path if path else "workspace")
        headline = f"Listed {target}"
        return headline, diff_stat

    if "browser" in name or "preview" in name or "navigate" in name:
        url = args.get("url") or ""
        headline = f"Browser evaluation {url[:40]}" if url else "Browser evaluation"
        return headline, diff_stat

    if "web_search" in name or name == "search_web":
        query = args.get("query") or ""
        provider = (obs and getattr(obs, "metadata", None) and obs.metadata.get("provider")) or ""
        prov_str = f" via {provider}" if provider else ""
        headline = f"Searched web for '{query[:45]}'{prov_str}" if query else "Searched web"
        return headline, diff_stat

    if "web_fetch" in name or name == "fetch_web":
        url = args.get("url") or ""
        headline = f"Fetched {url[:50]}" if url else "Fetched web page"
        return headline, diff_stat

    if "web_crawl" in name or name == "crawl_web":
        start_url = args.get("start_url") or ""
        pages = (obs and getattr(obs, "metadata", None) and obs.metadata.get("pages_count")) or ""
        p_str = f" ({pages} pages)" if pages else ""
        headline = f"Crawled {start_url[:40]}{p_str}" if start_url else "Crawled web pages"
        return headline, diff_stat

    if "image_search" in name or name == "search_images":
        query = args.get("query") or ""
        cnt = obs and getattr(obs, "metadata", None) and obs.metadata.get("count")
        cnt_str = f"{cnt} " if cnt is not None else ""
        headline = f"Found {cnt_str}images for '{query[:35]}'" if (is_completed and query) else (f"Searching images for '{query[:35]}'" if query else "Searched images")
        return headline, diff_stat

    if "download_image" in name or name == "fetch_image":
        meta = (obs and getattr(obs, "metadata", None)) or {}
        filename = meta.get("filename") or args.get("filename") or ""
        dims = f" ({meta.get('width')}x{meta.get('height')})" if (meta.get("width") and meta.get("height")) else ""
        headline = f"Downloaded {filename}{dims}" if filename else "Downloaded image asset"
        return headline, diff_stat

    if "deep_web_research" in name or name == "deep_research":
        topic = args.get("topic") or ""
        sources = obs and getattr(obs, "metadata", None) and obs.metadata.get("sources_count")
        s_str = f" ({sources} sources)" if sources else ""
        headline = f"Researched '{topic[:40]}'{s_str}" if topic else "Completed deep web research"
        return headline, diff_stat

    headline = f"Executed {tool_name}"
    return headline, diff_stat


class HarnessPolicy:
    """
    Evaluates proposed actions against security rules, permissions,
    workspace boundaries, and parameter schemas using canonical ToolPlatform.
    """

    def __init__(self, mode: str = "auto", security_gate: Optional[SecurityGate] = None) -> None:
        self.mode = mode if (isinstance(mode, str) and mode in ("auto", "plan", "safe")) else "auto"
        self._permission_policy = PermissionPolicy(mode=self.mode)
        self.security_gate = security_gate or SecurityGate()

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

        # ── 4. Canonical Prompt 13 SecurityGate Enforcement ─────────────────
        sec_decision, _ = self.security_gate.evaluate_action(
            tool_name=canonical_name,
            arguments=validated_args,
            session_id=getattr(action, "session_id", None),
            mission_id=action.mission_id,
            task_id=action.task_id,
        )
        if sec_decision.outcome == SecPermissionOutcome.DENY:
            alt = f" Suggestion: {sec_decision.suggested_alternative}" if sec_decision.suggested_alternative else ""
            return False, f"Security Policy Denied ({sec_decision.reason_code.value}): {sec_decision.reason}.{alt}", spec.implementation_cls, {}
        elif sec_decision.outcome == SecPermissionOutcome.ASK and self.mode in ("plan", "safe"):
            return False, f"Security Authorization Required ({sec_decision.required_scope.value}): {sec_decision.reason}", spec.implementation_cls, {}

        return True, "Allowed", spec.implementation_cls, validated_args


class ActionExecutor:
    """
    Coordinates harness evaluation, event emission, physical tool execution,
    output shaping, and observation generation.
    """

    def __init__(
        self,
        mode: str = "auto",
        security_gate: Optional[SecurityGate] = None,
        event_bus_instance: Optional[Any] = None,
    ) -> None:
        self.security_gate = security_gate or SecurityGate()
        self.policy = HarnessPolicy(mode=mode, security_gate=self.security_gate)
        self._custom_bus = event_bus_instance
        self.event_bus = event_bus_instance or event_bus

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

        # Resolve effective event bus (supporting unittest monkeypatching of core.agent_loop.actions.event_bus)
        eff_bus = self._custom_bus or event_bus

        # Publish ACTION_REQUESTED event
        eff_bus.publish(HermesEvent(
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
            logger.warning(f"ActionExecutor: Action '{canonical_name}' denied: {reason}")
            self.event_bus.publish(HermesEvent(
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
        eff_bus.publish(HermesEvent(
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

        # ── Phase 3: Write-Ahead Intent, Actual Execution, Durable Outcome Protocol ──
        from core.persistence.models import OperationStatus, ToolPersistenceError, OperationAlreadyCommittedError
        from tools.platform.file_identity import file_identity_cache

        operation_id = action.action_id or f"op_{action.tool_call_id or uuid.uuid4().hex[:10]}"
        ws_root = Path(workspace.root_str) if (workspace and workspace.is_locked) else Path.cwd()
        ws_root_str = str(ws_root.resolve())

        # Determine target path and capture prior hash if applicable
        target_path_str: Optional[str] = (
            validated_params.get("path")
            or validated_params.get("file_path")
            or validated_params.get("target_path")
            or validated_params.get("file")
        )
        resolved_target: Optional[Path] = None
        prior_hash: Optional[str] = None
        if target_path_str:
            try:
                resolved_target = (ws_root / target_path_str).resolve()
                if resolved_target.exists() and resolved_target.is_file():
                    ident = file_identity_cache.get(resolved_target)
                    if ident:
                        prior_hash = ident.content_hash
                    else:
                        import hashlib
                        prior_hash = hashlib.sha256(resolved_target.read_bytes()).hexdigest()
            except Exception:
                pass

        from core.idempotency import compute_logical_action_id, tool_execution_ledger
        logical_id = compute_logical_action_id(
            mission_id=action.mission_id,
            turn_id=action.turn_id,
            canonical_tool=canonical_name,
            arguments=validated_params,
        )

        # 0. Check idempotency ledger for prior completion across provider failovers
        cached_obs = tool_execution_ledger.get_cached_result(logical_id)
        if cached_obs is not None:
            logger.info(
                f"ActionExecutor: [IDEMPOTENCY] Replay of completed logical action '{logical_id}' "
                f"({canonical_name}) detected. Reusing cached outcome without re-executing."
            )
            eff_bus.publish(HermesEvent(
                event_type=EventType.TOOL_COMPLETED,
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                tool_call_id=action.tool_call_id or logical_id,
                severity=EventSeverity.INFO,
                payload={
                    "operation_id": logical_id,
                    "action_id": action.action_id,
                    "tool_name": canonical_name,
                    "idempotent_replay": True,
                    "success": cached_obs.success,
                    "output_preview": (cached_obs.summary or cached_obs.content or "")[:200],
                }
            ))
            return Observation(
                observation_id=f"obs_cached_{uuid.uuid4().hex[:6]}",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
                source_type=cached_obs.source_type,
                source_id=cached_obs.source_id,
                success=cached_obs.success,
                summary=cached_obs.summary,
                content=cached_obs.content,
                exit_code=cached_obs.exit_code,
                metadata={"idempotent_cached": True, "logical_id": logical_id, **(getattr(cached_obs, "metadata", {}) or {})},
            )

        tool_execution_ledger.mark_pending(
            logical_id=logical_id,
            mission_id=action.mission_id,
            turn_id=action.turn_id,
            tool_name=canonical_name,
            arguments=validated_params,
        )

        # 1. Duplicate dispatch check against persistent database
        db = eff_bus.get_database()
        if db is not None:
            existing_op = db.get_tool_operation(operation_id)
            if existing_op:
                existing_st = existing_op.get("status")
                logger.warning(f"ActionExecutor: duplicate operation_id '{operation_id}' detected with status '{existing_st}'")
                if existing_st in ("RESULT_COMMITTED", "COMPLETED"):
                    cached_summary = existing_op.get("output_summary") or f"Operation '{operation_id}' already completed."
                    cached_exit = existing_op.get("exit_code", 0)
                    action.status = ActionStatus.SUCCESS if cached_exit == 0 else ActionStatus.FAILED
                    return Observation(
                        observation_id=f"obs_cached_{operation_id[:8]}",
                        mission_id=action.mission_id,
                        task_id=action.task_id,
                        turn_id=action.turn_id,
                        action_id=action.action_id,
                        source_type="execution",
                        source_id=canonical_name,
                        timestamp=time.time(),
                        success=(cached_exit == 0),
                        summary=cached_summary,
                        content=cached_summary,
                        exit_code=cached_exit,
                        metadata={"idempotent_cached": True, "operation_id": operation_id, "status": existing_st},
                    )
                return ObservationBuilder.from_harness_rejection(
                    tool_name=canonical_name,
                    reason=f"DUPLICATE_OPERATION: Operation '{operation_id}' already committed with status '{existing_st}'. Replay prevented.",
                    mission_id=action.mission_id,
                    action_id=action.action_id,
                    rejection_type="DUPLICATE_OPERATION",
                )

        # 1b. Check if mission has already been aborted/cancelled before committing intent
        state_store = eff_bus.get_state(action.mission_id)
        if state_store is not None:
            snap = state_store.get_snapshot()
            if snap.mission.is_terminal:
                logger.warning(
                    f"ActionExecutor: mission '{action.mission_id}' is already in terminal state "
                    f"'{snap.mission.status.value}'. Aborting tool execution for '{canonical_name}'."
                )
                action.status = ActionStatus.CANCELLED
                return ObservationBuilder.from_harness_rejection(
                    tool_name=canonical_name,
                    reason=f"MISSION_TERMINAL: Mission '{action.mission_id}' is already terminal ({snap.mission.status.value}). Action aborted.",
                    mission_id=action.mission_id,
                    task_id=action.task_id,
                    turn_id=action.turn_id,
                    action_id=action.action_id,
                    rejection_type="MISSION_ABORTED",
                )

        # 2. Write-Ahead Intent: Commit TOOL_REQUESTED / TOOL_STARTED durably BEFORE execution
        try:
            start_headline, start_diff = format_tool_headline(canonical_name, validated_params, is_completed=False)
            intent_event = eff_bus.publish_durable(HermesEvent(
                event_type=EventType.TOOL_STARTED,
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                tool_call_id=action.tool_call_id or operation_id,
                payload={
                    "operation_id": operation_id,
                    "action_id": action.action_id,
                    "tool_name": canonical_name,
                    "target_path": target_path_str,
                    "workspace_root": ws_root_str,
                    "arguments_summary": str(validated_params)[:200],
                    "arguments": validated_params,
                    "prior_hash": prior_hash,
                    "headline": start_headline,
                    "diff_stat": start_diff,
                }
            ))
            intent_seq = intent_event.sequence

            if db is not None:
                db.record_tool_intent(
                    operation_id=operation_id,
                    mission_id=action.mission_id,
                    tool_name=canonical_name,
                    intent_seq=intent_seq,
                    task_id=action.task_id,
                    turn_id=action.turn_id,
                    run_id=getattr(action, "run_id", None),
                    session_id=getattr(action, "session_id", None),
                    target_path=target_path_str,
                    workspace_root=ws_root_str,
                    arguments_summary=str(validated_params)[:200],
                    arguments=validated_params,
                    prior_hash=prior_hash,
                )
        except Exception as intent_commit_exc:
            action.status = ActionStatus.FAILED
            action.error = f"DURABLE_INTENT_COMMIT_FAILED: {intent_commit_exc}"
            logger.error(f"ActionExecutor: durable intent commit failed for '{canonical_name}': {intent_commit_exc}")
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name,
                reason=f"WRITE_AHEAD_BARRIER_FAILED: Tool intent could not be committed to disk. Physical execution aborted. Error: {intent_commit_exc}",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
                rejection_type="PERSISTENCE_BARRIER_ERROR",
            )

        # 3. Physical Tool Execution
        if tool_class is None:
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name,
                reason=f"No executable class bound for {canonical_name}",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
            )

        # Inject operation identity & workspace metadata into tool parameters
        if isinstance(validated_params, dict):
            validated_params["_operation_id"] = operation_id
            validated_params["_mission_id"] = action.mission_id
            if workspace is not None:
                validated_params["_workspace"] = workspace
                validated_params["workspace"] = workspace

        # 2b. Re-verify terminal state immediately before physical tool execution
        if state_store is not None and state_store.get_snapshot().mission.is_terminal:
            logger.warning(
                f"ActionExecutor: mission '{action.mission_id}' became terminal before physical execution of '{canonical_name}'. Aborting."
            )
            action.status = ActionStatus.CANCELLED
            if db is not None:
                try:
                    db.update_operation_status(
                        operation_id=operation_id,
                        status=OperationStatus.CANCELLED,
                        error_message="Action cancelled before physical execution",
                    )
                except Exception:
                    pass
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name,
                reason=f"MISSION_TERMINAL: Mission '{action.mission_id}' became terminal. Physical execution aborted.",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
                rejection_type="MISSION_ABORTED",
            )

        # Fast, selective workspace file differential tracking
        is_shell_or_batch = any(kw in canonical_name.lower() for kw in ("shell", "bash", "command", "powershell", "terminal"))
        is_file_mutator = any(kw in canonical_name.lower() for kw in ("write", "edit", "patch", "create", "delete", "remove"))
        if is_shell_or_batch:
            files_before = _scan_workspace_files(ws_root)
        elif is_file_mutator and resolved_target:
            files_before = {str(resolved_target)} if (resolved_target.exists() and resolved_target.is_file()) else set()
        else:
            files_before = set()

        tool_instance = tool_class()
        t_start = time.monotonic()
        action.status = ActionStatus.EXECUTING
        execution_occurred = False
        tool_execution_ledger.record_execution_start(logical_id)

        try:
            input_model = getattr(tool_class, "Input", getattr(tool_class, "input_model", None))
            if input_model is not None and isinstance(validated_params, dict):
                try:
                    tool_input = input_model(**validated_params)
                except Exception:
                    tool_input = validated_params
            else:
                tool_input = validated_params

            execution_occurred = True
            from tools.shell_tools import CURRENT_MISSION_ID
            mid_token = CURRENT_MISSION_ID.set(action.mission_id)
            try:
                if asyncio.iscoroutinefunction(tool_instance.execute):
                    tool_result = await tool_instance.execute(tool_input)
                else:
                    tool_result = await asyncio.to_thread(tool_instance.execute, tool_input)
            finally:
                CURRENT_MISSION_ID.reset(mid_token)

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

        if is_shell_or_batch:
            files_after = _scan_workspace_files(ws_root)
        elif is_file_mutator and resolved_target:
            files_after = {str(resolved_target)} if (resolved_target.exists() and resolved_target.is_file()) else set()
        else:
            files_after = set()

        # 3b. Late-result fencing: verify mission was not cancelled during physical execution
        if state_store is not None and state_store.get_snapshot().mission.is_terminal:
            logger.warning(
                f"ActionExecutor: mission '{action.mission_id}' became terminal during physical execution of '{canonical_name}'. Discarding result."
            )
            action.status = ActionStatus.CANCELLED
            if db is not None:
                try:
                    db.update_operation_status(
                        operation_id=operation_id,
                        status=OperationStatus.CANCELLED,
                        error_message="Action completed after mission became terminal; result discarded",
                    )
                except Exception:
                    pass
            return ObservationBuilder.from_harness_rejection(
                tool_name=canonical_name,
                reason=f"MISSION_TERMINAL: Mission '{action.mission_id}' became terminal during execution. Result discarded.",
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                action_id=action.action_id,
                rejection_type="MISSION_ABORTED",
            )

        # Capture post-operation hash
        post_hash: Optional[str] = None
        if resolved_target and resolved_target.exists() and resolved_target.is_file():
            ident = file_identity_cache.get(resolved_target)
            if ident:
                post_hash = ident.content_hash
            else:
                import hashlib
                post_hash = hashlib.sha256(resolved_target.read_bytes()).hexdigest()

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

        # Prompt 13 Untrusted Content Screening
        if obs.content:
            sanitized_content, _ = self.security_gate.screen_observation(
                raw_output=obs.content,
                trust_level=ContentTrust.UNTRUSTED_EXTERNAL,
                source_id=f"tool_{canonical_name}",
            )
            obs.content = sanitized_content

        is_success = obs.success
        if is_success:
            tool_execution_ledger.mark_completed(logical_id, obs)
        else:
            tool_execution_ledger.mark_failed(logical_id, str(obs.error_message or "failed"))
        action.status = ActionStatus.SUCCEEDED if is_success else ActionStatus.FAILED
        op_status = OperationStatus.RESULT_COMMITTED if is_success else OperationStatus.FAILED
        side_effects_map = {
            "files_created": list(files_after - files_before) if is_success else [],
            "files_deleted": list(files_before - files_after) if is_success else [],
            "prior_hash": prior_hash,
            "post_hash": post_hash if is_success else prior_hash,
        }

        # 4. Durably Commit Operation Result
        try:
            comp_headline, comp_diff = format_tool_headline(canonical_name, validated_params, is_completed=True, success=is_success, obs=obs)
            preview_text = (obs.summary or obs.content or "")[:350].strip()
            result_event = eff_bus.publish_durable(HermesEvent(
                event_type=EventType.TOOL_COMPLETED if is_success else EventType.TOOL_FAILED,
                mission_id=action.mission_id,
                task_id=action.task_id,
                turn_id=action.turn_id,
                tool_call_id=action.tool_call_id or operation_id,
                severity=EventSeverity.INFO if is_success else EventSeverity.ERROR,
                payload={
                    "operation_id": operation_id,
                    "action_id": action.action_id,
                    "tool_name": canonical_name,
                    "target_path": target_path_str,
                    "exit_code": obs.exit_code,
                    "duration": duration,
                    "duration_ms": int(duration * 1000),
                    "success": is_success,
                    "error": obs.error_message,
                    "prior_hash": prior_hash,
                    "post_hash": post_hash,
                    "side_effects": side_effects_map,
                    "full_output_ref": obs.full_result_ref,
                    "details": getattr(tool_result, "details", {}) or {},
                    "headline": comp_headline,
                    "diff_stat": comp_diff,
                    "output_preview": preview_text,
                    "metadata": getattr(obs, "metadata", {}) or {},
                },
            ))
            result_seq = result_event.sequence

            # Emit specialized domain event for UI / timeline parity
            special_ev_map = {
                "web_search": EventType.WEB_SEARCH_COMPLETED,
                "web_fetch": EventType.WEB_FETCH_COMPLETED,
                "web_crawl": EventType.WEB_CRAWL_COMPLETED,
                "image_search": EventType.IMAGE_SEARCH_COMPLETED,
                "download_image": EventType.IMAGE_DOWNLOAD_COMPLETED,
                "deep_web_research": EventType.RESEARCH_BUNDLE_COMPLETED,
            }
            if canonical_name in special_ev_map:
                try:
                    eff_bus.publish(HermesEvent(
                        event_type=special_ev_map[canonical_name],
                        mission_id=action.mission_id,
                        task_id=action.task_id,
                        turn_id=action.turn_id,
                        tool_call_id=action.tool_call_id or operation_id,
                        severity=EventSeverity.INFO if is_success else EventSeverity.ERROR,
                        payload={
                            "operation_id": operation_id,
                            "tool_name": canonical_name,
                            "success": is_success,
                            "duration_ms": int(duration * 1000),
                            "headline": comp_headline,
                            "metadata": getattr(obs, "metadata", {}) or {},
                        }
                    ))
                except Exception:
                    pass

            if db is not None:
                db.record_tool_result(
                    operation_id=operation_id,
                    result_seq=result_seq,
                    status=op_status,
                    exit_code=obs.exit_code or 0,
                    post_hash=post_hash,
                    output_summary=obs.summary,
                    error_message=obs.error_message,
                    duration_seconds=duration,
                    side_effects=side_effects_map,
                )
        except Exception as result_commit_exc:
            # UNCERTAIN OUTCOME PROTOCOL:
            # Operation was executed, but its result could not be durably recorded.
            logger.critical(
                f"ActionExecutor: CRITICAL: Result commit failed for executed tool '{canonical_name}' "
                f"(operation_id='{operation_id}'): {result_commit_exc}. Marking OUTCOME_UNKNOWN."
            )
            if db is not None:
                try:
                    db.update_operation_status(
                        operation_id=operation_id,
                        status=OperationStatus.OUTCOME_UNKNOWN,
                        error_message=f"OUTCOME_UNKNOWN: Physical side effects occurred but result commit failed: {result_commit_exc}",
                    )
                except Exception:
                    pass

            obs.success = False
            obs.exit_code = 1
            obs.error_type = "OUTCOME_UNKNOWN"
            obs.error_message = (
                f"OUTCOME_UNKNOWN (REQUIRES_RECONCILIATION): Tool '{canonical_name}' was executed, "
                f"but its result could not be durably recorded ({result_commit_exc}). "
                f"Do NOT retry this operation blindly without reconciling the filesystem."
            )
            obs.summary = f"Operation '{operation_id}' outcome is uncertain. Reconciliation required."
            return obs

        # 5. Publish Observation event after durable commit is established
        eff_bus.publish(HermesEvent(
            event_type=EventType.OBSERVATION_CREATED,
            mission_id=action.mission_id,
            task_id=action.task_id,
            turn_id=action.turn_id,
            payload={
                "observation_id": obs.observation_id,
                "action_id": action.action_id,
                "operation_id": operation_id,
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

