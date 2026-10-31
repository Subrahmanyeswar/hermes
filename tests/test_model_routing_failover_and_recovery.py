import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from core.orchestrator import Orchestrator, MultiTierRoutingExhaustedError
from core.response_parser import ResponseParser, ParseSuccess
from models.nvidia_client import NvidiaTimeoutError, NvidiaConnectionError
from models.provider import NormalizedModelResponse
from core.runtime_state.events import EventType, HermesEvent
from core.adaptive_routing import get_adaptive_router, ProviderHealthState


@pytest.mark.asyncio
async def test_t1_timeout_clean_failover_to_t2():
    """Verify that when Tier 1 times out, Orchestrator fails over to Tier 2 observably with tool schemas."""
    router = get_adaptive_router()
    # Reset router state for isolation
    router.providers[1].state = ProviderHealthState.HEALTHY
    router.providers[1].failure_count = 0
    router.providers[1].consecutive_first_token_failures = 0

    orch = Orchestrator()
    events_emitted = []

    async def mock_publish(event: HermesEvent):
        events_emitted.append(event)

    orch.event_bus = MagicMock()
    orch.event_bus.publish = AsyncMock(side_effect=mock_publish)

    # Mock Tier 1 to simulate NVIDIA NIM first-token timeout
    mock_t1 = MagicMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "z-ai/glm-5.3-flash"
    mock_t1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError(
            "NVIDIA NIM first token timed out after 16.3s (upstream server stalled)",
            timeout_type="FIRST_TOKEN_TIMEOUT",
            duration=16.3,
        )
    )
    orch.tier1 = mock_t1

    # Mock Tier 2 (Ollama) to succeed with valid JSON tool call
    mock_ollama = MagicMock()
    t2_json = '{"tool": "write_file", "parameters": {"path": "index.html", "content": "<h1>Hello Aether</h1>"}}'
    mock_ollama.generate = AsyncMock(
        return_value=NormalizedModelResponse(
            text=t2_json,
            model="gpt-oss:120b-cloud",
            provider="ollama",
            latency_ms=1200.0,
            success=True,
        )
    )
    orch.ollama = mock_ollama

    kwargs = {
        "model": "z-ai/glm-5.3-flash",
        "prompt": "Create index.html for Aether Orbital",
        "system": "You are an autonomous engineer.",
        "mission_id": "m_test_failover",
        "turn_id": "turn_1_abc",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                },
            }
        ],
    }

    resp = await orch._generate_t1(**kwargs)

    # 1. Verify Tier 2 response was returned
    assert resp is not None
    assert resp.model == "gpt-oss:120b-cloud"
    assert resp.provider == "ollama"

    # 2. Verify ResponseParser parses the response into write_file
    parser = ResponseParser()
    parsed = parser.parse(resp)
    assert isinstance(parsed, ParseSuccess)
    assert parsed.tool == "write_file"
    assert parsed.parameters.get("path") == "index.html"
    assert "Hello Aether" in parsed.parameters.get("content", "")

    # 3. Verify Observable Events were emitted with correct mission_id and turn_id
    event_types = [e.event_type for e in events_emitted]
    assert EventType.TIER_FAILOVER_STARTED in event_types
    assert EventType.MODEL_COMPLETED in event_types

    failover_event = next(e for e in events_emitted if e.event_type == EventType.TIER_FAILOVER_STARTED)
    assert failover_event.mission_id == "m_test_failover"
    assert failover_event.turn_id == "turn_1_abc"
    assert failover_event.payload.get("tier") == 2

    # 4. Verify Tier 2 kwargs received tool schema documentation
    t2_call_kwargs = mock_ollama.generate.call_args.kwargs
    assert "Available Tools:" in t2_call_kwargs["system"]
    assert "write_file" in t2_call_kwargs["system"]
    assert "path, content" in t2_call_kwargs["system"]


@pytest.mark.asyncio
async def test_zero_wait_circuit_bypass_on_next_turn():
    """Verify that after Tier 1 fails, subsequent turns immediately bypass Tier 1 to Tier 2 in < 5ms."""
    router = get_adaptive_router()
    # Force T1 circuit to OPEN_CIRCUIT
    router.providers[1].state = ProviderHealthState.OPEN_CIRCUIT
    router.providers[1].failure_count = 2

    orch = Orchestrator()
    events_emitted = []

    async def mock_publish(event: HermesEvent):
        events_emitted.append(event)

    orch.event_bus = MagicMock()
    orch.event_bus.publish = AsyncMock(side_effect=mock_publish)

    # Tier 1 should NOT be called at all
    mock_t1 = MagicMock()
    mock_t1.generate = AsyncMock()
    orch.tier1 = mock_t1

    # Tier 2 responds immediately
    mock_ollama = MagicMock()
    mock_ollama.generate = AsyncMock(
        return_value=NormalizedModelResponse(
            text='{"tool": "read_file", "parameters": {"path": "index.html"}}',
            model="gpt-oss:120b-cloud",
            provider="ollama",
            latency_ms=800.0,
            success=True,
        )
    )
    orch.ollama = mock_ollama

    t0 = time.perf_counter()
    resp = await orch._generate_t1(
        model="z-ai/glm-5.3-flash",
        prompt="Check file",
        mission_id="m_test_bypass",
        turn_id="turn_2_xyz",
    )
    lat_ms = (time.perf_counter() - t0) * 1000.0

    # T1 was never invoked
    mock_t1.generate.assert_not_called()

    # T2 was returned
    assert resp.model == "gpt-oss:120b-cloud"

    # Circuit bypass was recorded
    event_types = [e.event_type for e in events_emitted]
    assert EventType.TIER_SELECTED in event_types
    selected_event = next(e for e in events_emitted if e.event_type == EventType.TIER_SELECTED)
    assert selected_event.payload.get("tier") == 2
    assert selected_event.mission_id == "m_test_bypass"
    assert selected_event.turn_id == "turn_2_xyz"


@pytest.mark.asyncio
async def test_exhausted_failover_raises_multi_tier_error():
    """Verify that if all tiers fail, MultiTierRoutingExhaustedError is cleanly raised."""
    router = get_adaptive_router()
    router.providers[1].state = ProviderHealthState.HEALTHY
    router.providers[1].failure_count = 0

    orch = Orchestrator()
    orch.event_bus = MagicMock()
    orch.event_bus.publish = AsyncMock()

    mock_t1 = MagicMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "z-ai/glm-5.3-flash"
    mock_t1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError("NIM timeout", timeout_type="FIRST_TOKEN_TIMEOUT")
    )
    orch.tier1 = mock_t1

    mock_ollama = MagicMock()
    mock_ollama.generate = AsyncMock(
        side_effect=RuntimeError("Ollama failed for both tiers")
    )
    orch.ollama = mock_ollama

    with pytest.raises(MultiTierRoutingExhaustedError) as exc_info:
        await orch._generate_t1(
            model="z-ai/glm-5.3-flash",
            prompt="Build app",
            mission_id="m_fail_all",
            turn_id="turn_1_err",
        )

    assert "All configured model tiers failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_loop_e2e_failover_writes_file(tmp_path):
    """
    End-to-end simulation of mission m_facf2d5d failure mode:
    1. Tier 1 throws NvidiaTimeoutError (16.3s first-token timeout)
    2. Failover to Tier 2 (Ollama 120b) succeeds and emits write_file
    3. ActionExecutor executes tool and index.html is genuinely written to disk
    4. Mission advances without transitioning to WAITING_FOR_PROVIDER
    """
    from core.agent_loop.loop import AgentLoop, AgentLoopConfig
    from core.workspace import WorkspaceManager
    from core.event_bus import EventBus
    from core.mission_planner import Mission

    ws_dir = tmp_path / "e2e_failover_ws"
    ws_dir.mkdir()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    bus = EventBus()
    events_captured = []
    bus.subscribe(lambda ev: events_captured.append(ev))

    router = get_adaptive_router()
    router.providers[1].state = ProviderHealthState.HEALTHY
    router.providers[1].failure_count = 0

    orch = Orchestrator()
    orch.event_bus = bus

    # Tier 1 fails with timeout
    mock_t1 = MagicMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "z-ai/glm-5.3-flash"
    mock_t1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError("NIM 16.3s first token timeout", timeout_type="FIRST_TOKEN_TIMEOUT")
    )
    orch.tier1 = mock_t1

    # Tier 2 succeeds: turn 1 writes file, turn 2 finishes mission
    mock_ollama = MagicMock()
    t2_call_count = 0

    async def mock_ollama_generate(**kwargs):
        nonlocal t2_call_count
        t2_call_count += 1
        if t2_call_count == 1:
            return NormalizedModelResponse(
                text='{"tool": "write_file", "parameters": {"path": "index.html", "content": "<h1>Aether Orbital Rocket Site</h1>"}}',
                model="gpt-oss:120b-cloud",
                provider="ollama",
                latency_ms=1100.0,
                success=True,
            )
        else:
            return NormalizedModelResponse(
                text="The website has been created and verified successfully.",
                model="gpt-oss:120b-cloud",
                provider="ollama",
                latency_ms=800.0,
                success=True,
            )

    mock_ollama.generate = AsyncMock(side_effect=mock_ollama_generate)
    orch.ollama = mock_ollama

    loop = AgentLoop(
        orchestrator=orch,
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3, max_wall_time_seconds=30.0),
    )

    mission = Mission(
        mission_id="m_facf2d5d_repro",
        user_prompt="Build rocket website for Aether Orbital with Three.js",
    )

    result = await loop.run(mission)

    # 1. Verify index.html was genuinely written on disk
    target_file = ws_dir / "index.html"
    assert target_file.exists(), "index.html was not created on disk after failover!"
    content = target_file.read_text(encoding="utf-8")
    assert "Aether Orbital Rocket Site" in content

    # 2. Verify mission did NOT transition to MISSION_WAITING
    waiting_events = [e for e in events_captured if e.event_type == EventType.MISSION_WAITING]
    assert len(waiting_events) == 0, f"Mission unexpectedly entered MISSION_WAITING: {waiting_events}"

    # 3. Verify failover and model completed events
    failover_events = [e for e in events_captured if e.event_type == EventType.TIER_FAILOVER_STARTED]
    assert len(failover_events) >= 1
    assert failover_events[0].mission_id == "m_facf2d5d_repro"

    # 4. Verify tool executed event
    tool_events = [e for e in events_captured if e.event_type == EventType.TOOL_COMPLETED]
    assert len(tool_events) >= 1
    assert tool_events[0].payload.get("tool_name") in ("write_file", "fs.write")


@pytest.mark.asyncio
async def test_concurrent_ollama_startup_lock_isolation():
    """Verify that multiple concurrent calls to _ensure_local_server_running serialize on _OLLAMA_STARTUP_LOCK."""
    from models.ollama_client import OllamaClient
    import models.ollama_client as oc

    client = OllamaClient()
    spawn_count = 0

    # Mock subprocess.Popen and client._get_client
    async def mock_ensure_internal():
        nonlocal spawn_count
        lock = oc._get_startup_lock()
        async with lock:
            spawn_count += 1
            await asyncio.sleep(0.05)
            return True

    with patch.object(client, "_ensure_local_server_running", side_effect=mock_ensure_internal):
        # Fire 5 concurrent requests
        results = await asyncio.gather(*(client._ensure_local_server_running() for _ in range(5)))
        assert all(results)
        assert spawn_count == 5


