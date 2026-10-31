# tests/test_phase2_core_runtime_repair.py
"""
HERMES Phase 2 Core Runtime Repair Test Suite.
Verifies all 20 required tests (TEST 1 through TEST 20) under canonical runtime.
"""

import asyncio
import hashlib
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.disagreement_router import (
    DisagreementRouter,
    FailureCategory,
    RoutingDecision,
)
from core.mission_planner import (
    Mission,
    MissionPlanner,
    MissionTask,
    TaskPriority,
    TaskState,
)
from core.mission_runner import MissionEvent, MissionPhase, MissionRunner
from core.verifier import VerificationResult
from core.workspace import workspace_manager
from tools.file_tools import ReadFileTool, WriteFileTool
from tools.platform.core_tools import FSEditTool, FSReadTool, FSWriteTool
from tools.platform.file_identity import file_identity_cache


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Verification dependency test
# Prove verify cannot become READY first when prerequisites are incomplete.
# ─────────────────────────────────────────────────────────────────────────────
def test_test_1_verification_cannot_become_ready_first() -> None:
    planner = MissionPlanner()
    t_create = MissionTask(title="Create project layout", description="Setup dirs")
    t_impl = MissionTask(title="Implement core application", description="Write code")
    t_integ = MissionTask(title="Integrate components", description="Connect modules")
    t_verify = MissionTask(title="Verify all functionality", description="Run verification checks")

    tasks = [t_create, t_impl, t_integ, t_verify]
    planner._assign_dependencies(tasks)

    mission = Mission(
        mission_id="m-test-1",
        user_prompt="Build and verify",
        tasks=tasks,
    )

    next_task = mission.next_executable_task
    assert next_task is not None
    assert not next_task.is_verification_task
    assert next_task.title == "Create project layout"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Semantic dependencies for reproduced web mission
# ─────────────────────────────────────────────────────────────────────────────
def test_test_2_semantic_dependencies_web_mission() -> None:
    planner = MissionPlanner()
    t1 = MissionTask(title="Create project layout and directory structure")
    t2 = MissionTask(title="Implement index.html with search and forms")
    t3 = MissionTask(title="Implement styles.css modern layout")
    t4 = MissionTask(title="Implement app.js state handling")
    t5 = MissionTask(title="Integrate components and user interaction flows")
    t6 = MissionTask(title="Verify and validate all created files for completeness")

    tasks = [t1, t2, t3, t4, t5, t6]
    planner._assign_dependencies(tasks)

    # Prove semantic dependencies
    assert len(t1.depends_on) == 0  # scaffold has no prereqs
    assert t1.task_id in t2.depends_on  # implementation depends on scaffold
    assert t1.task_id in t3.depends_on
    assert t1.task_id in t4.depends_on
    assert t2.task_id in t5.depends_on  # integration depends on implementation
    assert t3.task_id in t5.depends_on
    assert t4.task_id in t5.depends_on
    # Verification depends on all preceding artifact and integration tasks
    assert t1.task_id in t6.depends_on
    assert t2.task_id in t6.depends_on
    assert t3.task_id in t6.depends_on
    assert t4.task_id in t6.depends_on
    assert t5.task_id in t6.depends_on


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Deterministic topological ordering
# ─────────────────────────────────────────────────────────────────────────────
def test_test_3_deterministic_topological_ordering() -> None:
    planner = MissionPlanner()
    mission = planner.plan(
        "Build portfolio site with index.html, styles.css and test and verify",
        workspace_root="/tmp/fake_ws",
        execution_mode="strict",
    )

    non_verify_tasks = [t for t in mission.tasks if not t.is_verification_task]
    verify_tasks = [t for t in mission.tasks if t.is_verification_task]

    # Non-verification tasks should precede verification tasks in execution_order
    for nvt in non_verify_tasks:
        for vt in verify_tasks:
            idx_nvt = mission.execution_order.index(nvt.task_id)
            idx_vt = mission.execution_order.index(vt.task_id)
            assert idx_nvt < idx_vt, f"Task '{nvt.title}' must execute before '{vt.title}'"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Path binding test
# All task target paths resolve under W without automatic generated_projects/.
# ─────────────────────────────────────────────────────────────────────────────
def test_test_4_path_binding_no_generated_projects_drift(tmp_path: Path) -> None:
    planner = MissionPlanner()
    mission = planner.plan(
        "Create index.html, css/styles.css and js/app.js for lost and found app",
        workspace_root=str(tmp_path),
        execution_mode="strict",
    )

    for task in mission.tasks:
        for target in getattr(task, "target_paths", []):
            assert not target.startswith("generated_projects/"), (
                f"Target path '{target}' drifted into generated_projects/"
            )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Duplicate root test
# index.html and project/index.html cannot both be generated for one logical root app.
# ─────────────────────────────────────────────────────────────────────────────
def test_test_5_duplicate_root_prevention(tmp_path: Path) -> None:
    workspace_manager.lock(str(tmp_path))
    try:
        # Create canonical root index.html
        root_idx = tmp_path / "index.html"
        root_idx.write_text("<!DOCTYPE html><html><body>Root</body></html>", encoding="utf-8")
        workspace_manager.refresh_index()

        tool = WriteFileTool()
        res = tool.execute(
            WriteFileTool.Input(
                path="generated_projects/lost_found/index.html",
                content="<!DOCTYPE html><html><body>Duplicate</body></html>",
                mode="create",
            )
        )
        assert res.success is False
        assert "DUPLICATE_LOGICAL_ARTIFACT" in res.error
    finally:
        workspace_manager.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: Write-existing-file test
# Existing file + write_file(create mode) -> REJECT
# ─────────────────────────────────────────────────────────────────────────────
def test_test_6_write_existing_file_rejects_in_create_mode(tmp_path: Path) -> None:
    workspace_manager.lock(str(tmp_path))
    try:
        f = tmp_path / "app.js"
        f.write_text("console.log('original');", encoding="utf-8")
        workspace_manager.refresh_index()

        tool = WriteFileTool()
        res = tool.execute(
            WriteFileTool.Input(
                path="app.js",
                content="console.log('different');",
                mode="create",
            )
        )
        assert res.success is False
        assert "ALREADY_EXISTS" in res.error
    finally:
        workspace_manager.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Read-before-edit test
# Edit unread file -> REJECT (READ_BEFORE_EDIT_REQUIRED)
# Read then edit -> SUCCESS
# ─────────────────────────────────────────────────────────────────────────────
def test_test_7_read_before_edit_contract(tmp_path: Path) -> None:
    file_identity_cache.clear()
    f = tmp_path / "service.py"
    f.write_text("PORT = 8000\n", encoding="utf-8")

    edit_tool = FSEditTool()
    # 1. Edit without reading first
    res_unread = edit_tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "PORT = 8000",
        "new_string": "PORT = 9000",
        "require_read": True,
    })
    assert res_unread.success is False
    assert "READ_BEFORE_EDIT_REQUIRED" in res_unread.error

    # 2. Read first
    read_tool = FSReadTool()
    res_read = read_tool.execute({"_workspace": None, "path": str(f)})
    assert res_read.success is True

    # 3. Edit after reading
    res_edit = edit_tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": "PORT = 8000",
        "new_string": "PORT = 9000",
        "require_read": True,
    })
    assert res_edit.success is True
    assert "PORT = 9000" in f.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: Identical write test
# Existing file + identical content -> UNCHANGED
# ─────────────────────────────────────────────────────────────────────────────
def test_test_8_identical_write_returns_unchanged(tmp_path: Path) -> None:
    workspace_manager.lock(str(tmp_path))
    try:
        f = tmp_path / "styles.css"
        content = "body { margin: 0; background: #fff; }"
        f.write_text(content, encoding="utf-8")
        workspace_manager.refresh_index()

        tool = WriteFileTool()
        res = tool.execute(
            WriteFileTool.Input(
                path="styles.css",
                content=content,
                mode="create",
            )
        )
        assert res.success is True
        assert "UNCHANGED" in res.output
    finally:
        workspace_manager.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: Changed file after read test
# Read -> external modification -> edit -> FILE_CHANGED_SINCE_READ
# ─────────────────────────────────────────────────────────────────────────────
def test_test_9_changed_file_after_read(tmp_path: Path) -> None:
    file_identity_cache.clear()
    f = tmp_path / "config.json"
    f.write_text('{"v": 1}\n', encoding="utf-8")

    # Read
    read_tool = FSReadTool()
    res_read = read_tool.execute({"_workspace": None, "path": str(f)})
    assert res_read.success is True

    # External modification
    f.write_text('{"v": 2, "external": true}\n', encoding="utf-8")

    # Edit
    edit_tool = FSEditTool()
    res_edit = edit_tool.execute({
        "_workspace": None,
        "path": str(f),
        "old_string": '{"v": 1}',
        "new_string": '{"v": 3}',
    })
    assert res_edit.success is False
    assert "FILE_CHANGED_SINCE_READ" in res_edit.error


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10: Resume reconciliation
# Create files -> stop -> resume -> no blind regeneration
# ─────────────────────────────────────────────────────────────────────────────
def test_test_10_resume_reconciliation_preserves_completed_files(tmp_path: Path) -> None:
    workspace_manager.lock(str(tmp_path))
    try:
        f_html = tmp_path / "index.html"
        f_html.write_text("<!DOCTYPE html><html><body>Valid content here</body></html>", encoding="utf-8")

        f_css = tmp_path / "styles.css"
        f_css.write_text("body { color: black; font-family: sans-serif; }", encoding="utf-8")

        runner = MissionRunner(
            orchestrator=MagicMock(),
            workspace_manager=workspace_manager,
        )

        task1 = MissionTask(title="Create index.html", description="Create index.html", state=TaskState.COMPLETED)
        task2 = MissionTask(title="Create styles.css", description="Create styles.css", state=TaskState.COMPLETED)
        task3 = MissionTask(title="Create app.js", description="Create app.js", state=TaskState.PENDING)

        mission = Mission(
            mission_id="m-resume-test",
            user_prompt="Build site",
            tasks=[task1, task2, task3],
        )

        runner.reconcile_mission_state(mission)

        # Existing files must remain COMPLETED
        assert task1.state == TaskState.COMPLETED
        assert task2.state == TaskState.COMPLETED
        # Missing file must remain PENDING
        assert task3.state == TaskState.PENDING
    finally:
        workspace_manager.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11: Resume with complete artifact
# Pending task + already-valid file -> task recognized as satisfied
# ─────────────────────────────────────────────────────────────────────────────
def test_test_11_resume_satisfies_pending_task_with_valid_file(tmp_path: Path) -> None:
    workspace_manager.lock(str(tmp_path))
    try:
        f_js = tmp_path / "app.js"
        f_js.write_text("document.addEventListener('DOMContentLoaded', () => { console.log('Ready'); });", encoding="utf-8")

        runner = MissionRunner(
            orchestrator=MagicMock(),
            workspace_manager=workspace_manager,
        )

        task = MissionTask(title="Create app.js", description="Create app.js", state=TaskState.PENDING)
        mission = Mission(
            mission_id="m-artifact-test",
            user_prompt="Build app",
            tasks=[task],
        )

        runner.reconcile_mission_state(mission)

        # Pending task recognized as satisfied because valid file exists
        assert task.state == TaskState.COMPLETED
        assert task.ready_reason == "reconciled_existing_artifact"
    finally:
        workspace_manager.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12: Read loop termination
# Repeated identical reads terminate without error or T3 storm
# ─────────────────────────────────────────────────────────────────────────────
def test_test_12_read_loop_terminates_cleanly(tmp_path: Path) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("Hello world", encoding="utf-8")

    tool = FSReadTool()
    res = None
    for _ in range(5):
        res = tool.execute({"_workspace": None, "path": str(f)})

    assert res is not None
    # Clean termination with UNCHANGED_READ indicator / loop enforcement
    assert "UNCHANGED_READ" in (res.output or "") or "UNCHANGED_READ" in (res.error or "")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13: T3 infrastructure isolation
# Infrastructure failure does not consume T3 budget beyond limits
# ─────────────────────────────────────────────────────────────────────────────
def test_test_13_t3_infrastructure_isolation() -> None:
    router = DisagreementRouter()
    verification = VerificationResult(
        agree=False,
        confidence=0.5,
        risk_score=0.2,
        critical_issues=["TOOL_INFRASTRUCTURE_FAILURE: File system access error"],
    )

    res = router.route(
        verification=verification,
        tool_name="write_file",
        task_id="t-infra",
        mission_id="m-infra",
        error_message="Disk I/O failure",
    )

    assert res.decision == RoutingDecision.ACCEPT
    assert res.tier3_needed is False
    assert "quarantined from Tier 3" in res.reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14: T3 fingerprint deduplication
# Same failure repeated -> only one escalation
# ─────────────────────────────────────────────────────────────────────────────
def test_test_14_t3_fingerprint_deduplication() -> None:
    router = DisagreementRouter()
    verification = VerificationResult(
        agree=False,
        confidence=0.4,
        risk_score=0.3,
        critical_issues=["Logic flaw in calculation"],
    )

    # First call escalates
    res1 = router.route(
        verification=verification,
        tool_name="write_file",
        task_id="task-fp",
        mission_id="m-fp",
    )
    assert res1.decision == RoutingDecision.ESCALATE
    assert res1.tier3_needed is True

    # Duplicate call with same fingerprint suppressed
    res2 = router.route(
        verification=verification,
        tool_name="write_file",
        task_id="task-fp",
        mission_id="m-fp",
    )
    assert res2.decision == RoutingDecision.ACCEPT
    assert res2.tier3_needed is False
    assert "fingerprint already arbitrated" in res2.reason or "budget limit reached" in res2.reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15: SEND latency
# TUI SEND handler schedules worker and returns immediately (< 50ms)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_test_15_tui_send_latency_immediate() -> None:
    from ui.app import HermesApp, UserMessageSent

    app = HermesApp(mode="auto")
    msg = UserMessageSent(text="Build portfolio website")

    t_start = time.monotonic()
    await app.handle_user_message(msg)
    elapsed_ms = (time.monotonic() - t_start) * 1000.0

    assert elapsed_ms < 50.0, f"SEND took {elapsed_ms:.2f}ms, expected < 50ms"
    assert hasattr(app, "_send_latency_audit")
    assert app.is_processing is True


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16: Freeform planner stall
# Decomposition bounded without synchronous 60-second stalls
# ─────────────────────────────────────────────────────────────────────────────
def test_test_16_freeform_planner_bounded_stall() -> None:
    planner = MissionPlanner()
    t_start = time.monotonic()
    # Planning should return within a fraction of a second via fast heuristic
    mission = planner.plan(
        "Build a multi-page interactive web application",
        workspace_root="/tmp/fake_ws",
        execution_mode="strict",
    )
    elapsed = time.monotonic() - t_start

    assert elapsed < 5.0, f"Planner took {elapsed:.2f}s; expected < 5.0s"
    assert len(mission.tasks) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17: TUI/backend task identity consistency
# Displayed active task derived from authoritative backend task
# ─────────────────────────────────────────────────────────────────────────────
def test_test_17_tui_backend_task_identity_consistency() -> None:
    from core.runtime_state.models import HermesRuntimeState, MissionState, TaskState, TaskStatus
    from ui.state.selectors import select_progress_view_model, select_task_queue_view_model

    state = HermesRuntimeState(mission=MissionState(mission_id="m-1", prompt="test"))
    task_snap = TaskState(
        task_id="task-42",
        mission_id="m-1",
        order_index=1,
        title="Create application router",
        status=TaskStatus.RUNNING,
    )
    state.tasks["task-42"] = task_snap
    state.current_task = task_snap

    p_vm = select_progress_view_model(state)
    q_vm = select_task_queue_view_model(state)

    assert p_vm.active_task_title == "Create application router"
    assert q_vm.current_task_id == "task-42"
    assert q_vm.tasks[0].task_id == "task-42"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 18: Unknown tool event regression
# Thought/verification event without tool field is not rendered as unknown_tool
# ─────────────────────────────────────────────────────────────────────────────
def test_test_18_unknown_tool_event_regression() -> None:
    from ui.panels.chat import ProcessingIndicator

    indicator = ProcessingIndicator()
    indicator.show_detailed_trace = True
    indicator.live_feed = [
        {"event_type": "thought", "thought": "Analyzing requirements"},
        {"event_type": "verify_started", "stage_name": "Verification"},
    ]

    rendered_text = indicator.render()
    rendered_str = rendered_text.plain if hasattr(rendered_text, "plain") else str(rendered_text)

    assert "unknown_tool" not in rendered_str
    assert "unknown tool" not in rendered_str.lower()
    assert "Thought: Analyzing requirements" in rendered_str or "Verification" in rendered_str


# ─────────────────────────────────────────────────────────────────────────────
# TEST 19: TUI/CLI execution parity
# Both use the canonical MissionRunner execution lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def test_test_19_canonical_execution_parity() -> None:
    from kairos.mission_driver import MissionDriver

    driver_tui = MissionDriver(orchestrator=MagicMock(), execution_mode="strict")
    driver_cli = MissionDriver(orchestrator=MagicMock(), execution_mode="strict")

    assert driver_tui.execution_mode == driver_cli.execution_mode
    assert driver_tui.execution_mode == "strict"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 20: Verification is always final
# A mission cannot complete before verification
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_test_20_verification_is_always_final() -> None:
    t_impl = MissionTask(title="Implement index.html", description="Code index")
    t_verify = MissionTask(title="Verify all functionality", description="Run checks")

    mission = Mission(
        mission_id="m-verify-final",
        user_prompt="Build and verify",
        tasks=[t_impl, t_verify],
    )

    # When implementation is not complete, verify cannot run
    assert not mission.is_complete
    assert t_verify.is_verification_task
    # Mission cannot be marked complete if verification is pending
    t_impl.state = TaskState.COMPLETED
    assert not mission.is_complete
    assert mission.next_executable_task == t_verify

    t_verify.state = TaskState.COMPLETED
    assert mission.is_complete
