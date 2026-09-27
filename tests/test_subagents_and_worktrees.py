# tests/test_subagents_and_worktrees.py
"""
Comprehensive Test Suite for HERMES 2.x Subagents, Worktrees, and Background Execution.

Validates:
1. Subagent Policy Engine & Permission Ceilings (Explorer, Reviewer, Tester, Implementer)
2. Non-recursive delegation & escalation rejection
3. Fresh Context Window isolation (zero parent transcript bleed)
4. Git Worktree Sandboxing, Conflict Detection, and Non-destructive User Safety
5. Background OS Process & Async Execution with log streaming
6. Cancellation Controller (Cooperative tokens & Process tree kill)
7. Resource Governor (Bounded concurrency semaphore, Turn/Tool/Token/Byte limits, Stall watchdog)
8. Subagent Handoff Boundedness & Artifact Externalization
9. State Reducer Pure Reductions & Terminal Protection for Subagents, Worktrees, and Jobs
10. Startup Orphan Reconciler
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

from core.runtime_state.events import EventType, HermesEvent
from core.event_bus import EventBus
from core.runtime_state.store import StateStore, ExecutionStateStore
from core.runtime_state.reducer import StateReducer
from core.runtime_state.models import (
    HermesRuntimeState,
    AgentType,
    SubagentStatus,
    JobKind,
    JobStatus,
    JobLifecycle,
    WorktreeStatus,
    WorktreeIntegrationPolicy,
    SubagentToolPolicy,
    SubagentBudget,
    AgentResourceUsage,
    SubagentResult,
    SubagentHandoff,
)
from core.subagents.policy import (
    SubagentPolicyEngine,
    READ_ONLY_EXPLORATION_TOOLS,
    REVIEW_TOOLS,
    TEST_TOOLS,
    IMPLEMENTATION_TOOLS,
)
from core.subagents.context import SubagentContextBuilder
from core.subagents.worktree import WorktreeManager
from core.subagents.cancellation import (
    CancellationController,
    CancellationToken,
    SubagentCancelledException,
)
from core.subagents.governor import (
    ResourceGovernor,
    BudgetExceededException,
)
from core.subagents.background import BackgroundJobManager
from core.subagents.handoff import HandoffManager
from core.subagents.manager import SubagentManager
from core.subagents.reconciler import SubagentReconciler


# ── 1. Policy & Ceiling Tests ────────────────────────────────────────────────

def test_subagent_role_presets():
    """Verify default policies for standard roles match least-privilege principles."""
    exp_pol, exp_bud = SubagentPolicyEngine.get_preset_policy(AgentType.EXPLORER)
    assert exp_pol.read_only is True
    assert exp_pol.can_mutate is False
    assert exp_pol.can_shell is False
    assert exp_pol.can_delegate is False
    assert "fs.write" in exp_pol.denied_tools

    rev_pol, _ = SubagentPolicyEngine.get_preset_policy(AgentType.REVIEWER)
    assert rev_pol.read_only is True
    assert rev_pol.can_mutate is False

    test_pol, _ = SubagentPolicyEngine.get_preset_policy(AgentType.TESTER)
    assert test_pol.read_only is False
    assert test_pol.can_mutate is True
    assert test_pol.can_shell is True
    assert test_pol.can_delegate is False

    imp_pol, _ = SubagentPolicyEngine.get_preset_policy(AgentType.IMPLEMENTER)
    assert imp_pol.read_only is False
    assert imp_pol.can_mutate is True
    assert imp_pol.can_shell is True
    assert imp_pol.can_delegate is False


def test_permission_ceiling_enforcement():
    """Verify child cannot escalate beyond parent permissions."""
    parent_policy = SubagentToolPolicy(
        allowed_tools=["fs.read", "search.grep"],
        denied_tools=["shell.bash", "fs.write"],
        read_only=True,
        can_mutate=False,
        can_shell=False,
        can_delegate=False,
    )

    # Attempting to give child implementer superpowers
    requested_child = SubagentToolPolicy(
        allowed_tools=["fs.read", "fs.write", "shell.bash", "task.delegate"],
        read_only=False,
        can_mutate=True,
        can_shell=True,
        can_delegate=True,
    )

    clamped = SubagentPolicyEngine.enforce_ceiling(
        child_policy=requested_child,
        parent_policy=parent_policy,
        max_depth=1,
        current_depth=1,
    )

    assert clamped.read_only is True
    assert clamped.can_mutate is False
    assert clamped.can_shell is False
    assert clamped.can_delegate is False
    assert "shell.bash" in clamped.denied_tools
    assert "task.delegate" in clamped.denied_tools
    assert "fs.write" not in clamped.allowed_tools


def test_tool_access_validation():
    """Verify policy rejects unauthorized tool calls."""
    policy = SubagentToolPolicy(
        allowed_tools=["fs.read", "search.glob"],
        denied_tools=["fs.write", "shell.bash"],
        read_only=True,
        can_mutate=False,
    )

    ok, _ = policy.is_tool_allowed("fs.read")
    assert ok is True

    ok, reason = policy.is_tool_allowed("fs.write")
    assert ok is False
    assert "prohibited" in reason.lower() or "denied" in reason.lower()

    ok, reason = policy.is_tool_allowed("task.delegate")
    assert ok is False
    assert "recursive delegation" in reason.lower()


# ── 2. Context Builder Isolation Tests ───────────────────────────────────────

def test_subagent_context_fresh_window():
    """Verify subagent context is completely isolated and never includes parent transcript."""
    handoff = SubagentHandoff(
        task_id="task_123",
        agent_id="sub_456",
        goal="Investigate memory leak in cache",
        requirements=["REQ-1: Identify culprit", "REQ-2: Suggest fix"],
        scope_paths=["core/cache.py"],
        constraints=["Do not modify production files"],
        allowed_tools=["fs.read", "search.grep"],
        expected_output="Detailed root cause analysis",
    )

    pol, _ = SubagentPolicyEngine.get_preset_policy(AgentType.EXPLORER)
    prompt_ctx = SubagentContextBuilder.build_context(
        handoff=handoff,
        role=AgentType.EXPLORER,
        tool_policy=pol,
        rules=["Rule 1: Always check docstrings"],
    )

    # Transcript isolation checks
    assert "parent transcript" not in prompt_ctx.system_prompt.lower()
    assert "Investigate memory leak" in prompt_ctx.initial_user_prompt
    assert "REQ-1: Identify culprit" in prompt_ctx.initial_user_prompt
    assert "core/cache.py" in prompt_ctx.initial_user_prompt
    assert "Rule 1: Always check docstrings" in prompt_ctx.system_prompt
    assert prompt_ctx.allowed_tools == pol.allowed_tools


# ── 3. Git Worktree Sandboxing Tests ─────────────────────────────────────────

def test_worktree_creation_and_conflict_detection(tmp_path):
    """Test git worktree creation, change detection, and conflict detection."""
    # Initialize a temporary git repository
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@hermes.org"], cwd=str(tmp_path), capture_output=True, check=True)

    base_file = tmp_path / "hello.py"
    base_file.write_text("print('base')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(tmp_path), capture_output=True, check=True)

    wm = WorktreeManager(tmp_path)
    assert wm.is_git_available() is True

    # 1. Create worktree
    wt_record = wm.create_worktree(agent_id="agent_1", task_id="task_mut_1")
    wt_path = Path(wt_record.path)
    assert wt_path.exists()
    assert (wt_path / "hello.py").exists()

    # 2. Modify file in worktree
    (wt_path / "hello.py").write_text("print('subagent change')\n", encoding="utf-8")
    modified = wm.list_modified_files(wt_record)
    assert "hello.py" in modified

    # 3. Modify same file in parent workspace (trigger conflict)
    base_file.write_text("print('parent conflict')\n", encoding="utf-8")
    has_conflict, conflicts = wm.detect_conflicts(wt_record)
    assert has_conflict is True
    assert "hello.py" in conflicts

    # 4. Integrate worktree (should report conflict safely)
    int_res = wm.integrate_worktree(wt_record, policy=WorktreeIntegrationPolicy.PATCH_ONLY)
    assert int_res["conflict"] is True

    # 5. Cleanup worktree
    cleaned = wm.cleanup_worktree(wt_record)
    assert cleaned is True
    assert not wt_path.exists()


def test_user_uncommitted_changes_preserved(tmp_path):
    """Verify creating a worktree leaves user's unstaged edits untouched."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@hermes.org"], cwd=str(tmp_path), capture_output=True, check=True)

    f = tmp_path / "important.txt"
    f.write_text("v1", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "v1 commit"], cwd=str(tmp_path), capture_output=True, check=True)

    # User makes dirty edits
    f.write_text("v1 DIRTY UNCOMMITTED BY USER", encoding="utf-8")

    wm = WorktreeManager(tmp_path)
    wt = wm.create_worktree(agent_id="agent_2", task_id="task_safe")
    
    # Check parent workspace: uncommitted changes MUST be intact
    assert f.read_text(encoding="utf-8") == "v1 DIRTY UNCOMMITTED BY USER"
    
    wm.cleanup_worktree(wt)
    assert f.read_text(encoding="utf-8") == "v1 DIRTY UNCOMMITTED BY USER"


# ── 4. Background Execution & Processes ──────────────────────────────────────

@pytest.mark.asyncio
async def test_background_process_execution(tmp_path):
    """Test running an OS background process, streaming output, and awaiting."""
    bg_mgr = BackgroundJobManager(tmp_path)

    # Run Python one-liner to print to stdout and exit
    code = "import time, sys; sys.stdout.write('step 1\\n'); sys.stdout.flush(); time.sleep(0.1); sys.stdout.write('step 2\\n'); sys.stdout.flush()"
    cmd = [sys.executable, "-c", code]

    record = bg_mgr.start_process_job(
        job_id="job_proc_1",
        owner_agent_id="sub_test",
        task_id="t_bg_1",
        command=cmd,
        kind=JobKind.SHELL,
    )

    assert record.pid is not None
    assert record.status == JobStatus.RUNNING

    # Await completion
    finished_rec = await bg_mgr.await_job("job_proc_1", timeout=5.0)
    assert finished_rec.status == JobStatus.SUCCEEDED
    assert finished_rec.exit_code == 0

    # Verify stdout was streamed to disk
    output = bg_mgr.get_job_output("job_proc_1")
    assert "step 1" in output
    assert "step 2" in output


@pytest.mark.asyncio
async def test_background_async_subagent_job(tmp_path):
    """Test running an asynchronous coroutine as a background job."""
    bg_mgr = BackgroundJobManager(tmp_path)

    async def _dummy_worker():
        await asyncio.sleep(0.05)
        return "Done"

    record = bg_mgr.start_async_subagent_job(
        job_id="job_async_1",
        owner_agent_id="agent_main",
        task_id="task_bg_coro",
        coro=_dummy_worker(),
    )

    assert record.status == JobStatus.RUNNING
    finished = await bg_mgr.await_job("job_async_1", timeout=2.0)
    assert finished.status == JobStatus.SUCCEEDED


# ── 5. Cancellation Controller Tests ─────────────────────────────────────────

def test_cancellation_token_cooperative():
    """Verify cooperative cancellation token and callbacks."""
    token = CancellationToken()
    assert token.is_cancelled is False

    triggered = []
    token.register(lambda r: triggered.append(r))

    token.cancel("User aborted")
    assert token.is_cancelled is True
    assert token.reason == "User aborted"
    assert triggered == ["User aborted"]

    with pytest.raises(SubagentCancelledException):
        token.raise_if_cancelled()


def test_process_tree_termination():
    """Verify killing an OS process tree using CancellationController."""
    code = "import time; time.sleep(10)"
    proc = subprocess.Popen([sys.executable, "-c", code])
    pid = proc.pid
    assert proc.poll() is None

    # Kill process tree
    killed = CancellationController.kill_process_tree(pid, grace_period_seconds=0.5)
    assert killed is True

    # Process should be terminated
    time.sleep(0.2)
    assert proc.poll() is not None


# ── 6. Resource Governor Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resource_governor_concurrency():
    """Verify semaphore limits concurrent active subagents to bounded limit."""
    gov = ResourceGovernor(max_concurrent=2)
    assert gov.active_count == 0

    await gov.acquire_slot()
    await gov.acquire_slot()

    # Third acquire should block or wait
    acquired_third = False

    async def _try_third():
        nonlocal acquired_third
        await gov.acquire_slot()
        acquired_third = True

    task = asyncio.create_task(_try_third())
    await asyncio.sleep(0.05)
    assert acquired_third is False

    gov.release_slot()
    await asyncio.sleep(0.05)
    assert acquired_third is True
    task.cancel()


def test_resource_governor_budget_exceeded():
    """Verify governor raises BudgetExceededException when limits are crossed."""
    gov = ResourceGovernor()
    budget = SubagentBudget(max_turns=3, max_tool_calls=5)
    gov.register_agent("agent_lim", budget)

    gov.record_turn("agent_lim")
    gov.record_turn("agent_lim")
    gov.record_turn("agent_lim")

    # Exceeding 3 turns
    with pytest.raises(BudgetExceededException) as excinfo:
        gov.record_turn("agent_lim")
    assert "max_turns" in str(excinfo.value)


# ── 7. Handoff Boundedness & Artifact Externalization ────────────────────────

def test_handoff_manager_observation_and_externalization(tmp_path):
    """Verify handoff formats clean observations and externalizes oversized outputs."""
    result = SubagentResult(
        status=SubagentStatus.SUCCEEDED,
        task_id="t_handoff_1",
        agent_id="sub_h1",
        summary="Analysis complete",
        findings=["Found memory leak in lru_cache", "TTL expired prematurely"],
        files=["cache.py"],
        next_recommendation="Apply fix in core/cache.py",
    )

    obs = HandoffManager.format_observation(
        result=result,
        turn_id="turn_1",
        workspace_root=tmp_path,
        max_bytes=10_000,
    )

    assert obs.success is True
    assert "Analysis complete" in obs.content
    assert "Found memory leak" in obs.content
    assert "core/cache.py" in obs.content

    # Now test with very small max_bytes to trigger externalization
    large_result = SubagentResult(
        status=SubagentStatus.SUCCEEDED,
        task_id="t_large",
        agent_id="sub_large",
        summary="Large result" + ("x" * 2000),
    )

    obs_ext = HandoffManager.format_observation(
        result=large_result,
        turn_id="turn_2",
        workspace_root=tmp_path,
        max_bytes=500,
    )

    assert "TRUNCATED — Full subagent payload externalized" in obs_ext.content
    art_file = tmp_path / ".hermes" / "artifacts" / "subagent_sub_large_result.json"
    assert art_file.exists()


# ── 8. State Reducer Pure Reductions Tests ────────────────────────────────────

def test_subagent_and_job_pure_state_reduction():
    """Verify pure reductions for Section 15-18 events and terminal state protection."""
    state = HermesRuntimeState.create_empty("test_mission")
    assert len(state.agents) == 0
    assert len(state.background_jobs) == 0
    assert len(state.worktrees) == 0

    # 1. SUBAGENT_CREATED
    ev_create = HermesEvent(
        event_type=EventType.SUBAGENT_CREATED,
        source="manager",
        agent_id="sub_001",
        task_id="task_sub_1",
        payload={
            "agent_type": "EXPLORER",
            "budget": {"max_turns": 10},
        },
    )
    state = StateReducer.reduce(state, ev_create)
    assert "sub_001" in state.agents
    assert state.agents["sub_001"].status == SubagentStatus.CREATED
    assert "task_sub_1" in state.subagent_tasks

    # 2. SUBAGENT_STARTED
    ev_start = HermesEvent(
        event_type=EventType.SUBAGENT_STARTED,
        source="manager",
        agent_id="sub_001",
        task_id="task_sub_1",
    )
    state = StateReducer.reduce(state, ev_start)
    assert state.agents["sub_001"].status == SubagentStatus.RUNNING

    # 3. SUBAGENT_COMPLETED (Terminal)
    ev_comp = HermesEvent(
        event_type=EventType.SUBAGENT_COMPLETED,
        source="manager",
        agent_id="sub_001",
        task_id="task_sub_1",
    )
    state = StateReducer.reduce(state, ev_comp)
    assert state.agents["sub_001"].status == SubagentStatus.SUCCEEDED

    # Late out-of-order SUBAGENT_STARTED event cannot resurrect terminal agent
    state = StateReducer.reduce(state, ev_start)
    assert state.agents["sub_001"].status == SubagentStatus.SUCCEEDED

    # 4. BACKGROUND_JOB_CREATED & STARTED & COMPLETED
    ev_job_c = HermesEvent(
        event_type=EventType.BACKGROUND_JOB_CREATED,
        source="bg",
        job_id="job_001",
        payload={"kind": "SHELL"},
    )
    state = StateReducer.reduce(state, ev_job_c)
    assert "job_001" in state.background_jobs

    ev_job_comp = HermesEvent(
        event_type=EventType.BACKGROUND_JOB_COMPLETED,
        source="bg",
        job_id="job_001",
        payload={"exit_code": 0},
    )
    state = StateReducer.reduce(state, ev_job_comp)
    assert state.background_jobs["job_001"].status == JobStatus.SUCCEEDED

    # 5. WORKTREE_CREATED & CLEANED
    ev_wt_c = HermesEvent(
        event_type=EventType.WORKTREE_CREATED,
        source="wt",
        worktree_id="wt_001",
        payload={"path": "/tmp/wt1", "branch": "hermes-wt-1"},
    )
    state = StateReducer.reduce(state, ev_wt_c)
    assert "wt_001" in state.worktrees
    assert state.worktrees["wt_001"].status == WorktreeStatus.CREATED

    ev_wt_cl = HermesEvent(
        event_type=EventType.WORKTREE_CLEANED,
        source="wt",
        worktree_id="wt_001",
    )
    state = StateReducer.reduce(state, ev_wt_cl)
    assert state.worktrees["wt_001"].status == WorktreeStatus.CLEANED


# ── 9. Subagent Manager Full Delegation Integration Test ─────────────────────

@pytest.mark.asyncio
async def test_subagent_manager_full_delegation(tmp_path):
    """Test full delegation workflow through SubagentManager."""
    bus = EventBus()
    state_store = bus.get_or_create_state("delegation_mission")
    manager = SubagentManager(
        workspace_root=tmp_path,
        event_bus=bus,
        state_store=state_store,
        max_concurrent=3,
        max_depth=1,
    )

    # Custom runner returning high-signal findings
    async def _custom_runner(ctx, token):
        await asyncio.sleep(0.05)
        return SubagentResult(
            status=SubagentStatus.SUCCEEDED,
            task_id=ctx.metadata["task_id"],
            agent_id=ctx.metadata["agent_id"],
            summary="Refactored database query to use parameterized statements",
            findings=["Found SQL injection in query()", "Replaced with bind params"],
            files=["db.py"],
            next_recommendation="Run unit tests",
        )

    result = await manager.delegate_task(
        task_id="t_del_full",
        goal="Audit database queries",
        role=AgentType.REVIEWER,
        runner_coro_fn=_custom_runner,
    )

    assert isinstance(result, SubagentResult)
    assert result.status == SubagentStatus.SUCCEEDED
    assert "SQL injection" in result.findings[0]

    # Verify Core Invariant: Subagent SUCCESS != Goal COMPLETE
    current_state = state_store.get_state()
    from core.runtime_state.models import GoalStatus
    assert current_state.goal.status != GoalStatus.COMPLETED


# ── 10. Startup Reconciler Test ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_reconciler_orphaned_jobs_and_subagents(tmp_path):
    """Test reconciler detects abandoned subagents and dead process jobs upon restart."""
    bus = EventBus()
    store = bus.get_or_create_state("rec_mission")

    # Seed state with non-terminal agent and job with non-existent PID (999999)
    bus.publish(HermesEvent(
        event_type=EventType.SUBAGENT_CREATED,
        mission_id="rec_mission",
        source="test",
        agent_id="dead_agent",
        task_id="t_dead",
    ))
    bus.publish(HermesEvent(
        event_type=EventType.SUBAGENT_STARTED,
        mission_id="rec_mission",
        source="test",
        agent_id="dead_agent",
        task_id="t_dead",
    ))
    bus.publish(HermesEvent(
        event_type=EventType.BACKGROUND_JOB_CREATED,
        mission_id="rec_mission",
        source="test",
        job_id="dead_job",
        payload={"pid": 999999},
    ))
    bus.publish(HermesEvent(
        event_type=EventType.BACKGROUND_JOB_STARTED,
        mission_id="rec_mission",
        source="test",
        job_id="dead_job",
        payload={"pid": 999999},
    ))

    reconciler = SubagentReconciler(
        workspace_root=tmp_path,
        state_store=store,
        event_bus=bus,
    )

    report = await reconciler.reconcile()
    assert report["orphaned_subagents"] == 1
    assert report["orphaned_jobs"] == 1

    # Verify transitions in state
    state = store.get_state()
    assert state.agents["dead_agent"].status == SubagentStatus.FAILED
    assert state.background_jobs["dead_job"].status == JobStatus.ORPHANED
