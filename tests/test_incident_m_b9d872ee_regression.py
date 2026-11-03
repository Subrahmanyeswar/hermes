import ast
import inspect
from pathlib import Path
import pytest
from unittest.mock import MagicMock
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig, Observation
from core.mission_planner import Mission
from core.event_bus import EventBus
from core.workspace import WorkspaceManager


def test_agent_loop_run_does_not_shadow_observation():
    """Ensure AgentLoop.run does not classify Observation as a local variable.
    
    A local assignment or local import of Observation inside run() causes
    CPython to classify Observation as a FAST local across the entire run() method,
    triggering UnboundLocalError whenever Observation is referenced before that line.
    """
    assert "Observation" not in AgentLoop.run.__code__.co_varnames, (
        "Observation is bound as a local variable in AgentLoop.run! "
        "Remove any local import or assignment to Observation inside AgentLoop.run."
    )


def test_core_has_no_functions_shadowing_observation():
    """Scan all python files in core/ to ensure no function binds Observation locally while referencing it."""
    core_dir = Path(__file__).resolve().parent.parent / "core"
    for py_file in core_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    assigned = set()
                    loaded = []
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Name):
                            if isinstance(sub.ctx, (ast.Store, ast.Del)):
                                assigned.add(sub.id)
                            elif isinstance(sub.ctx, ast.Load):
                                loaded.append(sub.id)
                        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                            for a in sub.names:
                                assigned.add(a.asname or a.name)
                    assert not ("Observation" in assigned and "Observation" in loaded and "Observation" in [a.name for a in getattr(node, "args", {}).args if hasattr(a, "name")]), (
                        f"{py_file}:{node.name} inappropriately shadows Observation locally"
                    )
        except Exception:
            pass


@pytest.mark.asyncio
async def test_agent_loop_turn1_no_unbound_local_error(tmp_path: Path):
    """Simulate a mission turn where model response evaluates isinstance(model_response, Observation).
    
    This exact check at line 1027 triggered the UnboundLocalError in mission m_b9d872ee.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))
    bus = EventBus()

    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    # Turn 1: Return an Observation directly (e.g. from a filter or pre-run hook)
    async def mock_generate_t1(*args, **kwargs):
        return Observation(
            observation_id="obs_sim_1",
            mission_id="m_test_unbound",
            source_type="model",
            source_id="test_model",
            success=False,
            summary="Preflight model check",
            content="Simulated observation response"
        )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=2, execution_mode="agentic")
    )

    mission = Mission(
        mission_id="m_test_unbound",
        user_prompt="Build application",
        tasks=[]
    )

    # Must execute without UnboundLocalError
    try:
        result = await loop.run(mission)
        # Verify it ran without crashing on UnboundLocalError
        assert result is not None
    except UnboundLocalError as ule:
        pytest.fail(f"AgentLoop.run crashed with UnboundLocalError: {ule}")
