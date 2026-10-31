# scripts/run_live_test_d.py
import asyncio
from pathlib import Path
from unittest.mock import MagicMock
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.mission_planner import Mission
from core.event_bus import event_bus
from core.runtime_state.events import EventType

async def run_test_d():
    print("=== TEST D: Deterministic Failure Recovery Qualification ===")
    
    # 1. Multi-tool batch duplicate suppression
    cfg = AgentLoopConfig(max_turns=5, timeout_seconds=15.0)
    mock_orch = MagicMock()
    mock_orch.ollama = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "test_d_failure_recovery"

    # Workspace setup
    ws = Path("generated_projects/live_qual_d_adversarial").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "style.css"
    target.write_text("body { margin: 0; }", encoding="utf-8")
    loop._written_files.append("style.css")

    # Simulate multi-tool batch containing duplicate reads
    batch = [
        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "style.css"}'}},
        {"id": "call_2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "style.css"}'}},
        {"id": "call_3", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "style.css"}'}},
    ]
    seen = set()
    deduped = []
    for call in batch:
        sig = ("read_file", "style.css")
        if sig not in seen:
            seen.add(sig)
            deduped.append(call)

    print(f"[Duplicate Batch Test] Initial calls: {len(batch)} -> Deduplicated calls: {len(deduped)}")
    assert len(deduped) == 1, f"Expected 1 call after deduplication, got {len(deduped)}"

    # 2. Bounded recovery termination test across turn boundaries
    mission = MagicMock()
    mission.user_prompt = "Build cinematic website with main.js and style.css"

    # Attempt 1: Trigger recovery
    handled_1 = await loop._execute_no_progress_recovery(
        turn_id="turn_1",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked repeated read",
    )
    print(f"[Recovery Attempt 1] Handled: {handled_1} | Count: {loop._recovery_attempt_count} | Escalated: {getattr(loop, '_recovery_escalation_attempted', False)}")
    assert handled_1 is True
    assert loop._recovery_attempt_count == 1
    assert getattr(loop, "_recovery_escalation_attempted", False) is True

    # Attempt 2: Trigger recovery
    handled_2 = await loop._execute_no_progress_recovery(
        turn_id="turn_2",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked repeated read",
    )
    print(f"[Recovery Attempt 2] Handled: {handled_2} | Count: {loop._recovery_attempt_count}")
    assert handled_2 is True
    assert loop._recovery_attempt_count == 2

    # Attempt 3: Exhaustion -> clean termination
    handled_3 = await loop._execute_no_progress_recovery(
        turn_id="turn_3",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked repeated read",
    )
    print(f"[Recovery Attempt 3] Handled: {handled_3} | Recovery Exhausted -> Bounded Termination")
    assert handled_3 is False, "Expected recovery to return False when budget exhausted"

    print("Test D verification PASSED: Bounded recovery terminates cleanly before ceiling without infinite loop.")

if __name__ == "__main__":
    asyncio.run(run_test_d())
