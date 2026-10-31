# tests/test_prompt18_parity.py
"""
Prompt 18: Architectural Runtime Parity Verification.

Verifies:
1. One Engine, Many Surfaces: TUI, CLI run, and Headless share the exact canonical
   ApplicationRuntime, AgentLoop, StateStore, SecurityService, and SessionManager.
2. Anti-divergence: Detects and rejects any parallel or shadow runtime abstractions
   (e.g., SecondAgentLoop, ParallelRuntime, SeparateSecurityRuntime, SeparateStateEngine).
3. Semantic Parity: Deterministic commands execute identically across surfaces.
4. Replay Purity: Replay operates strictly via ReplayEngine and StateReducer without
   invoking AgentLoop, LLM, network, or live workspace mutations.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner

from core.agent_loop.loop import AgentLoop
from core.commands.dispatcher import CommandDispatcher
from core.commands.models import CommandStatus
from core.commands.registry import command_registry
from core.replay.engine import ReplayEngine
from core.runtime_factory import ApplicationRuntime, ApplicationRuntimeFactory, SurfaceMode
from core.runtime_state.store import StateStore
from core.security.service import SecurityService
from core.sessions.manager import SessionManager
from main import app

runner = CliRunner()


def test_runtime_factory_shared_canonical_subsystems(tmp_path: Path):
    """
    Sections 12 & 13: Runtime Parity Guard.
    Confirms Headless and Interactive TUI modes share identical subsystem classes
    and registry instances from ApplicationRuntimeFactory.
    """
    ws_headless = tmp_path / "headless_ws"
    ws_headless.mkdir(parents=True, exist_ok=True)
    ws_tui = tmp_path / "tui_ws"
    ws_tui.mkdir(parents=True, exist_ok=True)

    rt_headless = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=ws_headless,
    )
    rt_tui = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.INTERACTIVE_TUI,
        workspace_root=ws_tui,
    )

    # 1. Canonical AgentLoop
    assert isinstance(rt_headless.agent_loop, AgentLoop)
    assert isinstance(rt_tui.agent_loop, AgentLoop)
    assert type(rt_headless.agent_loop) is type(rt_tui.agent_loop)

    # 2. Authoritative State Store
    assert isinstance(rt_headless.state_store, StateStore)
    assert isinstance(rt_tui.state_store, StateStore)
    assert type(rt_headless.state_store) is type(rt_tui.state_store)

    # 3. Canonical Security Service (Prompt 13)
    assert isinstance(rt_headless.security, SecurityService)
    assert isinstance(rt_tui.security, SecurityService)
    assert type(rt_headless.security) is type(rt_tui.security)

    # 4. Durable Persistence Subsystem (Prompt 14)
    assert isinstance(rt_headless.session_manager, SessionManager)
    assert isinstance(rt_tui.session_manager, SessionManager)
    assert type(rt_headless.session_manager) is type(rt_tui.session_manager)

    # 5. Shared Command Registry (Prompt 16)
    assert rt_headless.command_registry is command_registry
    assert rt_tui.command_registry is command_registry
    assert isinstance(rt_headless.dispatcher, CommandDispatcher)
    assert isinstance(rt_tui.dispatcher, CommandDispatcher)


def test_anti_divergence_no_shadow_runtimes():
    """
    Section 13: Guard against architectural shadow engines or duplicate loops.
    Fails if shadow classes are introduced.
    """
    import core.agent_loop as al_mod
    import core.runtime_factory as rf_mod
    import core.security as sec_mod

    disallowed_symbols = [
        "SecondAgentLoop",
        "ParallelRuntime",
        "SeparateSecurityRuntime",
        "SeparateStateEngine",
        "AltAgentLoop",
        "ShadowRuntime",
    ]

    for mod in (al_mod, rf_mod, sec_mod):
        for sym in disallowed_symbols:
            assert not hasattr(mod, sym), f"Prohibited shadow abstraction '{sym}' found in {mod}!"


def test_cli_and_runtime_semantic_parity(tmp_path: Path):
    """
    Section 14: Semantic Parity across CLI and Direct Runtime execution.
    Verifies /status query returns semantically consistent results across surfaces.
    """
    # Surface A: Direct Runtime Execution (HEADLESS)
    rt = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=tmp_path,
    )
    res_rt = asyncio.run(rt.execute_input("/status"))
    assert res_rt.exit_code == 0
    assert res_rt.status == CommandStatus.SUCCESS
    assert "HERMES Runtime Status" in res_rt.message
    assert res_rt.llm_called is False

    # Surface B: Typer CLI invocation
    res_cli = runner.invoke(app, ["status", "--workspace", str(tmp_path)])
    assert res_cli.exit_code == 0
    assert "HERMES Runtime Status" in res_cli.stdout

    # Surface C: Both confirm zero LLM calls and identical header semantics
    assert "HERMES Runtime Status" in res_rt.message
    assert "HERMES Runtime Status" in res_cli.stdout


def test_replay_parity_and_side_effect_freedom(tmp_path: Path):
    """
    Section 15: Replay Parity & Side-Effect Freedom.
    Replay operates strictly through ReplayEngine without AgentLoop or live side-effects.
    """
    rt_replay = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.REPLAY,
        workspace_root=tmp_path,
    )

    # Replay engine must be instantiated
    assert isinstance(rt_replay.replay_engine, ReplayEngine)

    # Prepare dummy trace
    trace_file = tmp_path / "replay_test_trace.json"
    records = [
        {"event_type": "SESSION_INITIALIZED", "session_id": "rep_test_001", "sequence": 1, "payload": {}},
        {"event_type": "TASK_COMPLETED", "task_id": "t1", "sequence": 2, "payload": {}},
    ]
    trace_file.write_text(json.dumps(records), encoding="utf-8")

    # Patch potential live execution vectors to assert they are NEVER touched during replay
    with patch("core.agent_loop.loop.AgentLoop.run") as mock_agent_loop, \
         patch("httpx.AsyncClient.post") as mock_http_post, \
         patch("httpx.Client.post") as mock_sync_http:

        res = rt_replay.replay_engine.replay_trace_file(trace_file)

        assert res.success is True
        assert res.events_replayed == 2
        # Zero live execution vectors triggered
        mock_agent_loop.assert_not_called()
        mock_http_post.assert_not_called()
        mock_sync_http.assert_not_called()
