# tests/test_prompt18_long_horizon_context.py
"""
Prompt 18: Long-Horizon Context, Large Workspaces, Goal Integrity, and Checkpoint Invariants.
Validates 10-turn, 50-turn, and 100-turn context preservation, truncation of huge test outputs,
externalized artifact storage, and goal/todo state survival across interruptions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from core.context import (
    ContextCapacity,
    ContextEngine,
    ContextItem,
    ContextPriority,
    ContextProvenance,
    ContextSectionType,
    ContextSourceType,
    ExternalizedOutputStore,
    ToolResultStore,
)
from core.runtime_state.models import HermesRuntimeState, MissionStatus, TaskStatus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.reducer import StateReducer


def test_huge_test_output_externalization_and_truncation():
    """
    Section 46: Huge Test Output Truncation & Externalization.
    When a tool emits huge output (e.g. 10,000 lines of pytest output),
    it must be externalized to CAS storage and bounded in context.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ext_store = ExternalizedOutputStore(base_dir=tmp_dir)
        res_store = ToolResultStore(external_store=ext_store)
        engine = ContextEngine(
            capacity=ContextCapacity(context_window_tokens=4000),
            external_store=ext_store,
            result_store=res_store,
        )

        huge_stdout = "\n".join([f"Line {i}: test step execution log detail" for i in range(2000)])
        huge_stdout += "\nFAILED tests/test_example.py::test_case - AssertionError: Expected 10 got 0\n"

        rec = engine.record_tool_result(
            tool_call_id="call_huge_test",
            tool_name="shell.bash",
            turn_id="turn_huge",
            mission_id="m_chaos",
            output_text=huge_stdout,
            summary="Test execution failed with assertion error",
            auto_externalize_threshold_chars=1000,
        )

        assert rec.external_ref is not None
        assert rec.size_bytes > 1000

        # Build context and verify pack remains bounded
        pack = engine.build_context(mission_goal="Investigate failure", turn_number=1)
        assert pack.total_estimated_tokens <= 4000
        prompt_str = pack.to_prompt_string()
        assert "AssertionError" in prompt_str or "Test execution failed" in prompt_str


def test_long_horizon_10_50_100_turns_bounded_context():
    """
    Sections 42, 43, 44: Context Long-Horizon Tests (10 turns, 50 turns, 100 turns).
    Context size must stay within hard token budget; compaction must retain goals and constraints.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ext_store = ExternalizedOutputStore(base_dir=tmp_dir)
        res_store = ToolResultStore(external_store=ext_store)
        capacity = ContextCapacity(
            context_window_tokens=8_000,
            output_reserve_tokens=1_000,
            safety_reserve_tokens=1_000,
        )
        engine = ContextEngine(
            capacity=capacity,
            external_store=ext_store,
            result_store=res_store,
        )

        engine.register_item(ContextItem(
            id="goal_item",
            section=ContextSectionType.CURRENT_GOAL,
            content="Maintain architectural integrity and bounded memory across 100 turns.",
            provenance=ContextProvenance(source_type=ContextSourceType.USER, source_id="user"),
            priority=ContextPriority.MANDATORY,
            pinned=True,
        ))

        context_sizes = []
        for turn in range(1, 101):
            # Record synthetic tool result
            engine.record_tool_result(
                tool_call_id=f"step_{turn}",
                tool_name="search.grep",
                turn_id=f"turn_{turn}",
                mission_id="m_100",
                output_text=f"Turn {turn} exploration output content.",
                summary=f"Turn {turn} completed",
            )
            pack = engine.build_context(
                mission_goal="Maintain architectural integrity and bounded memory across 100 turns.",
                turn_number=turn,
            )
            context_sizes.append(pack.total_estimated_tokens)

            # Invariant: Must NEVER exceed usable capacity at ANY turn
            assert pack.total_estimated_tokens <= capacity.usable_capacity_tokens, (
                f"Turn {turn} exceeded usable capacity"
            )

        # 10, 50, and 100 turn snapshots
        assert context_sizes[9] <= capacity.usable_capacity_tokens   # Turn 10
        assert context_sizes[49] <= capacity.usable_capacity_tokens  # Turn 50
        assert context_sizes[99] <= capacity.usable_capacity_tokens  # Turn 100

        # Goal is preserved at turn 100
        final_prompt = pack.to_prompt_string()
        assert "Maintain architectural integrity" in final_prompt


def test_goal_and_todo_integrity_under_interruption():
    """
    Section 49 & 50: Goal & Todo Integrity Under Chaos.
    Interrupting during task progress must not erase goals, revert completed tasks,
    or create phantom completion markers upon recovery.
    """
    reducer = StateReducer()
    state = HermesRuntimeState.create_empty("sess_chaos_todo_001")
    state.mission.goal = "Refactor authentication module"
    state.mission.status = MissionStatus.RUNNING

    # Add task 1 and complete it
    ev1 = HermesEvent(
        event_type=EventType.TASK_STARTED,
        payload={"task_id": "t1", "title": "Setup JWT helper"},
        source="test",
    )
    state = reducer.reduce(state, ev1)
    ev2 = HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        payload={"task_id": "t1", "output": "jwt_ready"},
        source="test",
    )
    state = reducer.reduce(state, ev2)

    # Add task 2 in progress
    ev3 = HermesEvent(
        event_type=EventType.TASK_STARTED,
        payload={"task_id": "t2", "title": "Implement RBAC checks"},
        source="test",
    )
    state = reducer.reduce(state, ev3)

    # Simulate interruption event
    ev_interrupt = HermesEvent(
        event_type=EventType.SESSION_INTERRUPTED,
        payload={"reason": "SIGINT_RECEIVED", "interrupted_stage": "TASK_EXECUTION"},
        source="test",
    )
    state = reducer.reduce(state, ev_interrupt)

    # Verify state integrity after recovery
    assert state.mission.goal == "Refactor authentication module"
    assert state.tasks["t1"].status == TaskStatus.COMPLETED
    assert state.tasks["t2"].status in (TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.BLOCKED)
    assert state.tasks["t2"].status != TaskStatus.COMPLETED

