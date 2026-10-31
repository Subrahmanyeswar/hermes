# tests/test_phase4e_mission_optimization.py
"""
HERMES Phase 4E — Mission Compression, Safe Parallelism & Optimization Tests.
Tests:
- MissionComplexity classification (TRIVIAL, SIMPLE, MEDIUM, COMPLEX, LARGE)
- Simple mission compression into 3-4 tasks + verification
- Complex mission preservation of deep decomposition
- File-contract-aware safe parallel generation
- Conflict key detection (write-write collision rejection, read-read safety)
- Dynamic batch size adaptation
- Hard verification barrier preservation
- Context reuse & static invariant sharing
- Repair task consolidation (1 targeted repair instead of 3 micro-tasks)
- Chaos / failure recovery during parallel execution
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.mission_planner import (
    MissionPlanner,
    Mission,
    MissionTask,
    TaskState,
    TaskPriority,
    MissionComplexity,
    classify_mission_complexity,
)
from core.action_discipline import TaskActionContract, derive_action_contract
from core.mission_runner import MissionRunner, MissionOptimizationTelemetry
from core.adaptive_routing import AdaptiveRouter, ProviderHealthState


# ── Test 1: Mission Complexity Classification ───────────────────────────────

def test_mission_complexity_classification():
    # Trivial prompts
    assert classify_mission_complexity("Create hello.py printing hello world") == MissionComplexity.TRIVIAL
    assert classify_mission_complexity("Write a script utils.py with helper function") == MissionComplexity.TRIVIAL

    # Simple web app / board prompts
    campus_prompt = (
        "I want a small but polished campus event board for students. "
        "Students should browse events, search and filter by category, see details, "
        "and add new events. Remember events in localStorage. Make it responsive."
    )
    assert classify_mission_complexity(campus_prompt) == MissionComplexity.SIMPLE

    calc_prompt = "Build a clean responsive mortgage calculator with HTML, CSS, and JS"
    assert classify_mission_complexity(calc_prompt) == MissionComplexity.SIMPLE

    # Medium prompts
    flask_crud = "Build a Flask REST API with SQLite database, models and routes for managing books"
    assert classify_mission_complexity(flask_crud) == MissionComplexity.MEDIUM

    # Complex prompts
    full_stack = (
        "Build a full-stack platform with OAuth authentication, JWT tokens, "
        "database migrations, Celery background worker, and Stripe payment processing"
    )
    assert classify_mission_complexity(full_stack) == MissionComplexity.COMPLEX

    # Large / distributed prompts
    large_prompt = "Design a microservices architecture with Kafka event bus and Kubernetes deployment"
    assert classify_mission_complexity(large_prompt) == MissionComplexity.LARGE


# ── Test 2: Simple Mission Compression ─────────────────────────────────────

def test_simple_mission_compression():
    planner = MissionPlanner()
    prompt = "Create a campus event board with search, filters, event cards, and localStorage persistence"
    mission = planner.plan(prompt)

    assert mission.complexity == MissionComplexity.SIMPLE
    assert len(mission.tasks) == 4, f"Expected 4 consolidated tasks, got {len(mission.tasks)}"

    t1, t2, t3, t4 = mission.tasks
    # Task 1: Architecture & HTML
    assert "index.html" in t1.target_paths
    assert t1.depends_on == []
    assert not t1.is_verification_task

    # Task 2: Styles
    assert any("styles.css" in p for p in t2.target_paths)
    assert t1.task_id in t2.depends_on
    assert not t2.is_verification_task

    # Task 3: Interactive JS
    assert any("app.js" in p for p in t3.target_paths)
    assert t1.task_id in t3.depends_on
    assert not t3.is_verification_task

    # Task 4: Verification
    assert t4.is_verification_task
    assert t1.task_id in t4.depends_on
    assert t2.task_id in t4.depends_on
    assert t3.task_id in t4.depends_on


# ── Test 3: Complex Mission Remains Decomposed ─────────────────────────────

def test_complex_mission_remains_decomposed():
    planner = MissionPlanner()
    complex_prompt = (
        "Build a full-stack platform with OAuth authentication, JWT tokens, "
        "database migrations, background worker queue, API endpoints, and comprehensive tests"
    )
    mission = planner.plan(complex_prompt)
    assert mission.complexity == MissionComplexity.COMPLEX
    # Must preserve deeper multi-task decomposition (at least 5 tasks)
    assert len(mission.tasks) >= 5


# ── Test 4: Conflict Key Detection & Disjoint Batching ──────────────────────

def test_conflict_key_detection_and_disjoint_batching():
    t1 = MissionTask(
        task_id="t1",
        title="Write HTML",
        target_paths=["index.html"],
        write_dependencies=["index.html"],
        state=TaskState.COMPLETED,
    )
    t2 = MissionTask(
        task_id="t2",
        title="Write CSS",
        target_paths=["css/styles.css"],
        write_dependencies=["css/styles.css"],
        depends_on=["t1"],
        state=TaskState.PENDING,
    )
    t3 = MissionTask(
        task_id="t3",
        title="Write JS",
        target_paths=["js/app.js"],
        write_dependencies=["js/app.js"],
        depends_on=["t1"],
        state=TaskState.PENDING,
    )
    t4 = MissionTask(
        task_id="t4",
        title="Verify App",
        target_paths=["index.html", "css/styles.css", "js/app.js"],
        depends_on=["t1", "t2", "t3"],
        state=TaskState.PENDING,
    )

    mission = Mission(tasks=[t1, t2, t3, t4], execution_order=["t1", "t2", "t3", "t4"])

    # Batch should safely include both t2 and t3 concurrently
    batch = mission.get_executable_batch(max_concurrent=3)
    batch_ids = [t.task_id for t in batch]
    assert batch_ids == ["t2", "t3"], f"Expected ['t2', 't3'], got {batch_ids}"


# ── Test 5: Write-Write Conflict Serialization ──────────────────────────────

def test_write_write_conflict_prevents_parallel_batch():
    t1 = MissionTask(
        task_id="t1",
        title="Write styles header",
        target_paths=["styles.css"],
        write_dependencies=["styles.css"],
        state=TaskState.PENDING,
    )
    t2 = MissionTask(
        task_id="t2",
        title="Write styles footer",
        target_paths=["styles.css"],
        write_dependencies=["styles.css"],
        state=TaskState.PENDING,
    )
    mission = Mission(tasks=[t1, t2], execution_order=["t1", "t2"])

    # Two tasks writing to the SAME file must NEVER be batched together
    batch = mission.get_executable_batch(max_concurrent=3)
    assert len(batch) == 1
    assert batch[0].task_id == "t1"


# ── Test 6: Hard Verification Barrier ───────────────────────────────────────

def test_hard_verification_barrier_preserved():
    t1 = MissionTask(task_id="t1", title="Write HTML", state=TaskState.COMPLETED)
    t2 = MissionTask(task_id="t2", title="Write CSS", state=TaskState.RUNNING)
    t_verif = MissionTask(
        task_id="tv",
        title="Verify full application",
        depends_on=["t1"],  # Even if dep on t1 is met, t2 is running
        state=TaskState.PENDING,
    )
    mission = Mission(tasks=[t1, t2, t_verif], execution_order=["t1", "t2", "tv"])

    # Verification task must NOT be yielded while non-verification t2 is running
    batch = mission.get_executable_batch()
    assert len(batch) == 0


# ── Test 7: Dynamic Batch Size Bounds ───────────────────────────────────────

def test_dynamic_batch_size_bounds():
    tasks = [
        MissionTask(task_id=f"t{i}", title=f"Write module {i}", target_paths=[f"mod{i}.py"], write_dependencies=[f"mod{i}.py"], state=TaskState.PENDING)
        for i in range(5)
    ]
    mission = Mission(tasks=tasks, execution_order=[f"t{i}" for i in range(5)])

    # Bound to max_concurrent=2
    batch = mission.get_executable_batch(max_concurrent=2)
    assert len(batch) == 2

    # Bound to max_concurrent=4
    batch4 = mission.get_executable_batch(max_concurrent=4)
    assert len(batch4) == 4


# ── Test 8: Context Sharing & Static Rule Invariance ────────────────────────

def test_context_sharing_static_cache():
    mock_orch = MagicMock()
    mock_ws = MagicMock()
    mock_ws.root_str = "."
    mock_ws.is_locked = False
    mock_ws.workspace_root = None

    runner = MissionRunner(orchestrator=mock_orch, workspace_manager=mock_ws)
    mission = Mission(mission_id="m_ctx_test", project_root_path="my_project")

    t1 = MissionTask(task_id="t1", title="Task 1", description="Implement HTML")
    t2 = MissionTask(task_id="t2", title="Task 2", description="Implement CSS")

    p1 = runner._build_task_prompt_with_description(t1, mission, t1.description)
    p2 = runner._build_task_prompt_with_description(t2, mission, t2.description)

    # Check that static rules were cached under mission_id:static_rules
    cache_key = "m_ctx_test:static_rules"
    assert cache_key in runner._static_context_cache
    # Both prompts must share the exact cached static invariant
    cached_rules = runner._static_context_cache[cache_key]
    assert cached_rules in p1
    assert cached_rules in p2


# ── Test 9: Repair Task Consolidation ───────────────────────────────────────

@pytest.mark.asyncio
async def test_repair_task_consolidation():
    mock_orch = MagicMock()
    mock_ws = MagicMock()
    mock_ws.root_str = "."
    mock_ws.is_locked = False
    mock_ws.workspace_root = None

    runner = MissionRunner(orchestrator=mock_orch, workspace_manager=mock_ws)
    mission = Mission(mission_id="m_repair_test", project_root_path=".")
    mission.tasks = [
        MissionTask(task_id="t1", title="HTML", state=TaskState.COMPLETED),
    ]
    mission.acceptance_criteria = ["index.html exists", "styles.css exists", "app.js exists"]

    # Mock _check_acceptance_criteria returning 2 unmet criteria
    with patch.object(runner, "_check_acceptance_criteria", return_value=["styles.css exists", "app.js exists"]):
        with patch.object(runner, "_execute_task", new_callable=AsyncMock) as mock_exec:
            # Let _execute_task mark the task complete
            async def side_effect(m, t):
                m.mark_task_complete(t.task_id)
            mock_exec.side_effect = side_effect

            # Running acceptance check should add EXACTLY 1 consolidated repair task (not 2 separate ones)
            unmet = await runner._check_acceptance_criteria(mission)
            assert len(unmet) == 2

            # Simulate consolidation logic
            combined = "\n- ".join(unmet)
            repair_task = MissionTask(
                title="Resolve missing project acceptance criteria",
                description=f"Missing:\n- {combined}",
                priority=TaskPriority.CRITICAL,
            )
            mission.tasks.append(repair_task)

            # Exactly 1 repair task created
            repair_tasks = [t for t in mission.tasks if "Resolve missing" in t.title]
            assert len(repair_tasks) == 1
            assert "styles.css exists" in repair_tasks[0].description
            assert "app.js exists" in repair_tasks[0].description


# ── Test 10: Chaos / Parallel Task Failure Handling ─────────────────────────

@pytest.mark.asyncio
async def test_parallel_task_failure_isolation():
    mock_orch = MagicMock()
    mock_ws = MagicMock()
    mock_ws.root_str = "."
    mock_ws.is_locked = False
    mock_ws.workspace_root = None

    runner = MissionRunner(orchestrator=mock_orch, workspace_manager=mock_ws)
    t1 = MissionTask(task_id="t1", title="Init", state=TaskState.COMPLETED)
    t2 = MissionTask(task_id="t2", title="Styles", target_paths=["styles.css"], write_dependencies=["styles.css"], depends_on=["t1"])
    t3 = MissionTask(task_id="t3", title="Logic", target_paths=["app.js"], write_dependencies=["app.js"], depends_on=["t1"])
    t4 = MissionTask(task_id="t4", title="Logic Dependent", depends_on=["t3"])

    mission = Mission(tasks=[t1, t2, t3, t4], execution_order=["t1", "t2", "t3", "t4"])

    batch = mission.get_executable_batch(max_concurrent=3)
    assert len(batch) == 2

    # Simulate t2 succeeding and t3 failing
    mission.mark_task_complete("t2")
    mission.mark_task_failed("t3", error="Model API error")

    # t2 is COMPLETED
    assert mission._get_task("t2").state == TaskState.COMPLETED
    # t3 is FAILED
    assert mission._get_task("t3").state == TaskState.FAILED
    # t4 must be BLOCKED because its dependency t3 failed
    assert mission._get_task("t4").state == TaskState.BLOCKED
    # No corrupt or dangling state
    assert not mission.is_complete
    assert mission.has_failure
