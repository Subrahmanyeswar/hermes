import sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import asyncio
from core.event_bus import EventBus
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.mission_planner import Mission

async def main():
    bus = EventBus()
    store = bus.get_or_create_state("m_debug")
    mock_orch = MagicMock()
    async def mock_gen(*args, **kwargs):
        res = MagicMock()
        res.model = "test-model"
        res.tool_calls = None
        res.text = '{"tool_name": "task.todo", "arguments": {"action": "add", "tasks": ["step 1"]}}'
        res.content = res.text
        return res
    mock_orch._generate_t1 = mock_gen

    mock_ws = MagicMock()
    mock_ws.root_str = "."
    mock_ws.is_locked = True
    mock_ws.get_workspace_summary.return_value = {"root": ".", "total_files": 0}
    mock_ws.get_skeleton.return_value = ""

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=mock_ws,
        event_bus_instance=bus,
        state_store_instance=store,
        config=AgentLoopConfig(max_turns=3),
    )
    mission = Mission(user_prompt="Build application", mission_id="m_debug")
    res = await loop.run(mission)
    print("FINISHED RUN:")
    print("Turns:", loop._turns_count)
    print("Consecutive planning turns:", loop._consecutive_planning_turns)
    print("Consecutive non-mutating turns:", loop._consecutive_non_mutating_turns)
    for i, obs in enumerate(loop._observation_history):
        print(f"Obs {i}: success={obs.success}, src={obs.source_id}, summary={obs.summary}")

asyncio.run(main())
