import asyncio
import os
import time
import json
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from dotenv import load_dotenv

load_dotenv()

from core.orchestrator import Orchestrator, MultiTierRoutingExhaustedError
from core.response_parser import ResponseParser, ParseSuccess
from core.workspace import WorkspaceManager
from core.agent_loop.actions import ActionExecutor, ActionEnvelope
from core.event_bus import EventBus
from models.nvidia_client import NvidiaTimeoutError
from core.adaptive_routing import get_adaptive_router, ProviderHealthState

FAILOVER_WS = Path(os.getenv("TEMP", "C:/Users/SUBBU/AppData/Local/Temp")) / "hermes_real_failover_test_ws"
FAILOVER_WS.mkdir(parents=True, exist_ok=True)

async def test_live_tier2_failover():
    print("===============================================================")
    print("TEST FAILOVER: SIMULATED TIER 1 FAILURE -> LIVE TIER 2 EXECUTION")
    print("===============================================================")

    target_file = FAILOVER_WS / "failover_recovery.json"
    if target_file.exists():
        target_file.unlink()

    router = get_adaptive_router()
    router.providers[1].state = ProviderHealthState.HEALTHY
    router.providers[1].failure_count = 0

    bus = EventBus()
    events = []
    bus.subscribe(lambda ev: events.append(ev))

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(FAILOVER_WS))
    executor = ActionExecutor(event_bus_instance=bus)

    orch = Orchestrator()
    orch.event_bus = bus

    # Simulate Tier 1 timeout
    from unittest.mock import AsyncMock
    orch.tier1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError("Simulated T1 25.0s first-token timeout", timeout_type="FIRST_TOKEN_TIMEOUT")
    )

    t0 = time.monotonic()
    # Call _generate_t1 which will catch T1 timeout, fail over to live Tier 2 (Ollama gpt-oss:120b-cloud)
    prompt = (
        "Create failover_recovery.json with recovery status 'TIER2_ACTIVE' and timestamp 1793125000. "
        "Use write_file to save the file."
    )
    system = "You are an autonomous engineer. Always call write_file to save files."
    tools = [
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
                    "required": ["path", "content"],
                },
            },
        }
    ]

    print("  Triggering Orchestrator._generate_t1 with simulated T1 timeout...")
    resp = await orch._generate_t1(
        model=orch.tier1.model,
        prompt=prompt,
        system=system,
        tools=tools,
        mission_id="m_test_failover_live",
        turn_id="turn_failover_1",
    )
    dur = time.monotonic() - t0
    print(f"  Failover response received in {dur:.2f}s | Model: {resp.model} | Provider: {resp.provider}")

    # Verify ResponseParser parses the response
    parser = ResponseParser()
    parse_res = parser.parse(resp)
    print(f"  ResponseParser result: is_success={isinstance(parse_res, ParseSuccess)} | tool={getattr(parse_res, 'tool', None)}")
    assert isinstance(parse_res, ParseSuccess), f"Failed to parse Tier 2 response: {parse_res}"

    # Execute action through ActionExecutor
    action_env = ActionEnvelope(
        action_id=f"act_failover_{int(time.time())}",
        tool_name=parse_res.tool,
        arguments=parse_res.parameters,
        turn_id="turn_failover_1",
        mission_id="m_test_failover_live",
    )
    obs = await executor.execute_action(action_env, workspace=ws_mgr)
    print(f"  ActionExecutor result: success={obs.success} | summary={obs.summary}")
    assert obs.success, f"Action execution failed: {obs.error}"

    # Verify disk truth
    assert target_file.exists(), "failover_recovery.json was not created on disk!"
    content = target_file.read_text(encoding="utf-8")
    print(f"  VERIFIED ON DISK: {target_file.name} ({len(content)} bytes) -> {content.strip()[:80]}")
    assert "TIER2_ACTIVE" in content or "failover" in content.lower() or "recovery" in content.lower()

    print("\n  [PASS] Live Tier 2 failover verified end-to-end with genuine disk write!\n")

async def main():
    await test_live_tier2_failover()

if __name__ == "__main__":
    asyncio.run(main())
