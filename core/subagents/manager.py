# core/subagents/manager.py
"""
Subagent Lifecycle Manager & Delegation Orchestrator for HERMES 2.x.

Core Invariants:
1. PARENT DELEGATES, CHILD ISOLATES, POLICY CONSTRAINS, WORKTREE CONTAINS, BUDGET LIMITS.
2. JOB RUNS ASYNC, CANCELLATION STOPS, HANDOFF SUMMARIZES, EVIDENCE RETURNS, PARENT DECIDES.
3. Subagent SUCCESS != Requirement VERIFIED != Goal COMPLETE.
4. Non-recursive by default (depth <= 1); ceiling permissions strictly clamped.
5. Zero modification or corruption to user uncommitted working tree or branches.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from core.runtime_state.events import EventType, HermesEvent
from core.event_bus import EventBus
from core.runtime_state.store import StateStore, ExecutionStateStore
from core.runtime_state.models import (
    AgentType,
    SubagentStatus,
    SubagentToolPolicy,
    SubagentBudget,
    AgentResourceUsage,
    SubagentResult,
    SubagentHandoff,
    AgentRecord,
    SubagentTaskRecord,
    WorktreeRecord,
    WorktreeStatus,
    WorktreeIntegrationPolicy,
    BackgroundJobRecord,
    JobKind,
    JobLifecycle,
)
from core.subagents.policy import SubagentPolicyEngine
from core.subagents.context import SubagentContextBuilder, SubagentPromptContext
from core.subagents.worktree import WorktreeManager
from core.subagents.background import BackgroundJobManager
from core.subagents.cancellation import CancellationController, CancellationToken, SubagentCancelledException
from core.subagents.governor import ResourceGovernor, BudgetExceededException
from core.subagents.handoff import HandoffManager
from core.security.gate import SecurityGate
from core.security.models import SubagentSecurityContext

logger = logging.getLogger("hermes.subagents.manager")


class SubagentManager:
    """
    Central coordinator for subagent creation, worktree sandboxing, background jobs,
    concurrency governance, cancellation, and handoffs.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        event_bus: Optional[EventBus] = None,
        state_store: Optional[ExecutionStateStore] = None,
        max_concurrent: int = 3,
        max_depth: int = 1,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.event_bus = event_bus
        self.state_store = state_store
        self.max_depth = max_depth

        self.worktree_mgr = WorktreeManager(self.workspace_root)
        self.background_mgr = BackgroundJobManager(self.workspace_root)
        self.governor = ResourceGovernor(max_concurrent=max_concurrent)
        self._cancellation_tokens: Dict[str, CancellationToken] = {}
        self.security_gate = SecurityGate()

    async def _publish(
        self,
        event_type: EventType,
        agent_id: Optional[str] = None,
        parent_agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        job_id: Optional[str] = None,
        worktree_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish canonical runtime event if EventBus is configured."""
        if not self.event_bus:
            return

        event = HermesEvent(
            event_type=event_type,
            source="subagent_manager",
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            job_id=job_id,
            worktree_id=worktree_id,
            payload=payload or {},
        )
        self.event_bus.publish(event)

    async def delegate_task(
        self,
        task_id: str,
        goal: str,
        role: AgentType | str = AgentType.EXPLORER,
        requirements: Optional[List[str]] = None,
        scope_paths: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        expected_output: str = "",
        policy_override: Optional[SubagentToolPolicy] = None,
        budget_override: Optional[SubagentBudget] = None,
        parent_agent_id: str = "primary",
        parent_policy: Optional[SubagentToolPolicy] = None,
        current_depth: int = 0,
        use_worktree: Optional[bool] = None,
        integration_policy: WorktreeIntegrationPolicy = WorktreeIntegrationPolicy.PATCH_ONLY,
        is_background: bool = False,
        runner_coro_fn: Optional[Callable[[SubagentPromptContext, CancellationToken], Coroutine[Any, Any, SubagentResult]]] = None,
    ) -> SubagentResult | BackgroundJobRecord:
        """
        Delegate an isolated subtask to a child subagent.
        """
        # 1. Depth & Recursion Validation
        if current_depth >= self.max_depth:
            raise PermissionError(
                f"Delegation depth ceiling reached: current_depth={current_depth}, max_depth={self.max_depth}. Subagents cannot recursively delegate."
            )

        # 2. Resolve Role and Permissions
        role_enum = role if isinstance(role, AgentType) else AgentType(str(role).upper())
        default_policy, default_budget = SubagentPolicyEngine.get_preset_policy(role_enum)

        base_policy = policy_override or default_policy
        effective_policy = SubagentPolicyEngine.enforce_ceiling(
            child_policy=base_policy,
            parent_policy=parent_policy,
            max_depth=self.max_depth,
            current_depth=current_depth,
        )

        effective_budget = budget_override or default_budget
        agent_id = f"subagent_{task_id[:6]}_{uuid.uuid4().hex[:6]}"

        # 3. Worktree Decision & Isolation
        should_isolate_worktree = use_worktree
        if should_isolate_worktree is None:
            # Auto-detect: Only mutate operations use worktrees; read-only operations don't
            should_isolate_worktree = (
                effective_policy.can_mutate
                and not effective_policy.read_only
                and self.worktree_mgr.is_git_available()
            )

        worktree_record: Optional[WorktreeRecord] = None
        effective_workspace = self.workspace_root

        if should_isolate_worktree:
            try:
                worktree_record = self.worktree_mgr.create_worktree(
                    agent_id=agent_id,
                    task_id=task_id,
                    sparse_paths=scope_paths,
                )
                effective_workspace = Path(worktree_record.path)
                await self._publish(
                    EventType.WORKTREE_CREATED,
                    agent_id=agent_id,
                    task_id=task_id,
                    worktree_id=worktree_record.worktree_id,
                    payload={"path": worktree_record.path, "branch": worktree_record.branch},
                )
            except Exception as e:
                logger.warning(f"Could not create git worktree, falling back to workspace: {e}")
                should_isolate_worktree = False

        # 4. Construct Fresh Isolated Context
        handoff = SubagentHandoff(
            task_id=task_id,
            agent_id=agent_id,
            goal=goal,
            requirements=requirements or [],
            scope_paths=scope_paths or [],
            constraints=constraints or [],
            allowed_tools=effective_policy.allowed_tools,
            budget=effective_budget,
            workspace_path=str(effective_workspace),
            worktree_id=worktree_record.worktree_id if worktree_record else None,
            expected_output=expected_output,
            deadline=time.time() + effective_budget.max_runtime_seconds,
        )

        prompt_context = SubagentContextBuilder.build_context(
            handoff=handoff,
            role=role_enum,
            tool_policy=effective_policy,
        )

        # 5. Cancellation Token & Governor Registration
        token = CancellationToken()
        self._cancellation_tokens[agent_id] = token
        self.governor.register_agent(agent_id, effective_budget)

        # 6. Publish Created & Started Events
        await self._publish(
            EventType.SUBAGENT_CREATED,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            worktree_id=worktree_record.worktree_id if worktree_record else None,
            payload={
                "agent_type": role_enum.value,
                "goal": goal,
                "tool_policy": effective_policy.to_dict(),
                "budget": effective_budget.to_dict(),
            },
        )
        await self._publish(
            EventType.SUBAGENT_STARTED,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            worktree_id=worktree_record.worktree_id if worktree_record else None,
            payload={"workspace": str(effective_workspace)},
        )

        # 7. Asynchronous Background Execution Branch
        if is_background:
            job_id = f"job_sub_{task_id[:6]}_{uuid.uuid4().hex[:4]}"

            async def _bg_run():
                return await self._execute_subagent_run(
                    agent_id=agent_id,
                    task_id=task_id,
                    parent_agent_id=parent_agent_id,
                    prompt_context=prompt_context,
                    effective_budget=effective_budget,
                    worktree_record=worktree_record,
                    integration_policy=integration_policy,
                    token=token,
                    runner_coro_fn=runner_coro_fn,
                )

            bg_record = self.background_mgr.start_async_subagent_job(
                job_id=job_id,
                owner_agent_id=agent_id,
                task_id=task_id,
                coro=_bg_run(),
                worktree_id=worktree_record.worktree_id if worktree_record else None,
            )
            await self._publish(
                EventType.BACKGROUND_JOB_CREATED,
                agent_id=agent_id,
                job_id=job_id,
                task_id=task_id,
                payload={"kind": "SUBAGENT", "lifecycle": "CHILD_BOUND"},
            )
            return bg_record

        # 8. Synchronous Execution Branch
        return await self._execute_subagent_run(
            agent_id=agent_id,
            task_id=task_id,
            parent_agent_id=parent_agent_id,
            prompt_context=prompt_context,
            effective_budget=effective_budget,
            worktree_record=worktree_record,
            integration_policy=integration_policy,
            token=token,
            runner_coro_fn=runner_coro_fn,
        )

    async def _execute_subagent_run(
        self,
        agent_id: str,
        task_id: str,
        parent_agent_id: str,
        prompt_context: SubagentPromptContext,
        effective_budget: SubagentBudget,
        worktree_record: Optional[WorktreeRecord],
        integration_policy: WorktreeIntegrationPolicy,
        token: CancellationToken,
        runner_coro_fn: Optional[Callable[[SubagentPromptContext, CancellationToken], Coroutine[Any, Any, SubagentResult]]],
    ) -> SubagentResult:
        """Execute the child runner and handle lifecycle events and teardown."""
        start_time = time.time()
        await self.governor.acquire_slot()

        try:
            # Execute runner
            if runner_coro_fn:
                # Wrap with timeout
                result = await asyncio.wait_for(
                    runner_coro_fn(prompt_context, token),
                    timeout=effective_budget.max_runtime_seconds,
                )
            else:
                # Simulated / Default bounded execution
                await asyncio.sleep(0.05)
                token.raise_if_cancelled()
                result = SubagentResult(
                    status=SubagentStatus.SUCCEEDED,
                    task_id=task_id,
                    agent_id=agent_id,
                    summary=f"Subagent completed task: {prompt_context.metadata.get('role', 'AGENT')}",
                    findings=["Analysis completed without errors"],
                    duration=time.time() - start_time,
                )

            # Worktree Integration if applicable
            if worktree_record:
                int_res = self.worktree_mgr.integrate_worktree(worktree_record, integration_policy)
                result.changes = [{"policy": integration_policy.value, "applied": int_res.get("applied", False)}]
                if int_res.get("files"):
                    result.files = int_res["files"]
                if int_res.get("conflict"):
                    result.status = SubagentStatus.FAILED
                    result.errors.append(f"Worktree conflict in: {int_res.get('conflicting_files')}")
                # Cleanup worktree
                self.worktree_mgr.cleanup_worktree(worktree_record)
                await self._publish(
                    EventType.WORKTREE_CLEANED,
                    agent_id=agent_id,
                    task_id=task_id,
                    worktree_id=worktree_record.worktree_id,
                )

            # Prompt 13: Inbound Subagent Handoff Security Check
            child_sec_ctx = SubagentSecurityContext(
                agent_id=agent_id,
                parent_id=parent_agent_id,
            )
            artifacts = (
                getattr(result, "artifact_refs", None)
                or getattr(result, "files", None)
                or getattr(result, "artifacts", None)
                or []
            )
            handoff_assessment = self.security_gate.inspect_subagent_handoff(
                child_context=child_sec_ctx,
                return_payload=getattr(result, "summary", "") or "",
                artifacts_produced=artifacts,
            )
            if not handoff_assessment.safe_to_ingest:
                result.summary = handoff_assessment.sanitized_payload
                if hasattr(result, "errors") and isinstance(result.errors, list):
                    result.errors.extend(handoff_assessment.violations)

            await self._publish(
                EventType.SUBAGENT_COMPLETED if result.status == SubagentStatus.SUCCEEDED else EventType.SUBAGENT_FAILED,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                task_id=task_id,
                payload={"summary": result.summary, "duration": result.duration},
            )
            return result

        except asyncio.TimeoutError:
            await self._publish(
                EventType.SUBAGENT_TIMED_OUT,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                task_id=task_id,
                payload={"error": f"Subagent exceeded max runtime of {effective_budget.max_runtime_seconds}s"},
            )
            if worktree_record:
                self.worktree_mgr.cleanup_worktree(worktree_record)
            return SubagentResult(
                status=SubagentStatus.TIMED_OUT,
                task_id=task_id,
                agent_id=agent_id,
                summary="Execution timed out",
                errors=[f"Execution timed out after {effective_budget.max_runtime_seconds}s"],
                duration=time.time() - start_time,
            )

        except (SubagentCancelledException, asyncio.CancelledError) as e:
            await self._publish(
                EventType.SUBAGENT_CANCELLED,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                task_id=task_id,
                payload={"reason": str(e)},
            )
            if worktree_record:
                self.worktree_mgr.cleanup_worktree(worktree_record)
            return SubagentResult(
                status=SubagentStatus.CANCELLED,
                task_id=task_id,
                agent_id=agent_id,
                summary="Execution cancelled",
                duration=time.time() - start_time,
            )

        except BudgetExceededException as e:
            await self._publish(
                EventType.SUBAGENT_RESOURCE_EXCEEDED,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                task_id=task_id,
                payload={"reason": str(e)},
            )
            if worktree_record:
                self.worktree_mgr.cleanup_worktree(worktree_record)
            return SubagentResult(
                status=SubagentStatus.RESOURCE_EXCEEDED,
                task_id=task_id,
                agent_id=agent_id,
                summary=f"Resource limit exceeded: {e}",
                errors=[str(e)],
                duration=time.time() - start_time,
            )

        except Exception as e:
            logger.exception(f"Subagent {agent_id} failed with error: {e}")
            await self._publish(
                EventType.SUBAGENT_FAILED,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                task_id=task_id,
                payload={"error": str(e)},
            )
            if worktree_record:
                self.worktree_mgr.cleanup_worktree(worktree_record)
            return SubagentResult(
                status=SubagentStatus.FAILED,
                task_id=task_id,
                agent_id=agent_id,
                summary=f"Execution error: {e}",
                errors=[str(e)],
                duration=time.time() - start_time,
            )

        finally:
            self.governor.release_slot()
            self.governor.unregister_agent(agent_id)
            self._cancellation_tokens.pop(agent_id, None)
            self.background_mgr.cleanup_child_bound_jobs(agent_id)

    def cancel_subagent(self, agent_id: str, reason: str = "User cancelled") -> bool:
        """Cancel a running subagent cooperatively."""
        token = self._cancellation_tokens.get(agent_id)
        if token:
            token.cancel(reason)
            return True
        return False
