# tests/test_tui_viewmodels_and_selectors.py
"""Tests for state selectors, None safety, and ViewModel assembly."""

import pytest
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
)
from ui.state.selectors import (
    build_root_view_model,
    safe_float_str,
    select_mission_view_model,
    select_progress_view_model,
    select_task_queue_view_model,
    select_verification_view_model,
)


def test_safe_float_str_none_safety():
    assert safe_float_str(None) == "N/A"
    assert safe_float_str(float("nan")) == "N/A"
    assert safe_float_str(float("inf")) == "N/A"
    assert safe_float_str("not_a_number") == "N/A"
    assert safe_float_str(12.3456, ".2f") == "12.35"


def test_select_mission_view_model_clean_projections():
    state = HermesRuntimeState.create_empty("test_mission")
    state.mission.title = "Build Web Server"
    state.mission.status = MissionStatus.RUNNING

    vm = select_mission_view_model(state)
    assert vm.mission_id == "test_mission"
    assert vm.title == "Build Web Server"
    assert vm.status == "RUNNING"
    assert vm.is_terminal is False


def test_select_tasks_and_acceptance_checks():
    state = HermesRuntimeState.create_empty("m_tasks")
    state.tasks["t1"] = TaskState(
        task_id="t1",
        mission_id="m_tasks",
        title="Setup database",
        status=TaskStatus.COMPLETED,
        order_index=1,
    )
    state.tasks["t2"] = TaskState(
        task_id="t2",
        mission_id="m_tasks",
        title="Write API routes",
        status=TaskStatus.RUNNING,
        order_index=2,
    )

    state.acceptance_ledger.add_check(
        AcceptanceCheck(
            check_id="chk_api",
            requirement_id="req_api",
            description="Verify GET /routes responds 200",
            status=AcceptanceCheckStatus.PASS,
        )
    )

    t_vm = select_task_queue_view_model(state)
    assert t_vm.total_count == 2
    assert t_vm.completed_count == 1
    assert t_vm.tasks[0].task_id == "t1"
    assert t_vm.tasks[1].task_id == "t2"

    v_vm = select_verification_view_model(state)
    assert v_vm.total_checks == 1
    assert v_vm.passing_checks == 1
    assert v_vm.checks[0].check_id == "chk_api"


def test_build_root_view_model_completeness():
    state = HermesRuntimeState.create_empty("m_root")
    root_vm = build_root_view_model(
        state=state,
        revision=42,
        active_notifications=["Session resumed successfully"],
    )

    assert root_vm.revision == 42
    assert root_vm.mission_id == "m_root"
    assert len(root_vm.active_notifications) == 1
    assert root_vm.active_notifications[0] == "Session resumed successfully"
    assert root_vm.memory.is_empty is True
