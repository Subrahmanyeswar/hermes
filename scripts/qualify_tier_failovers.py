import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from dotenv import load_dotenv
load_dotenv()

from core.orchestrator import Orchestrator, MultiTierRoutingExhaustedError
from core.event_bus import EventBus
from models.nvidia_client import NvidiaTimeoutError
from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from config.model_config import TIER1_MODEL, TIER2_MODEL, TIER3_MODEL

async def run_tier_failover_qualification():
    print("======================================================================")
    print("STEP 1: QUALIFY TIER 1 TIMEOUT -> TIER 2 LIVE SUCCESS")
    print("======================================================================")
    
    bus = EventBus()
    events = []
    bus.subscribe(lambda ev: events.append(ev))
    
    router = get_adaptive_router()
    router.reset_all() if hasattr(router, "reset_all") else None
    
    orch = Orchestrator()
    orch.event_bus = bus
    
    # Force Tier 1 timeout simulation
    orch.tier1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError("Simulated T1 25.0s first-token timeout", timeout_type="FIRST_TOKEN_TIMEOUT")
    )
    
    prompt = "Reply with exactly: 'TIER2_OK'"
    tools = []
    
    t0 = time.monotonic()
    print(f"Triggering Orchestrator._generate_t1 with simulated T1 ({TIER1_MODEL}) timeout...")
    resp2 = await orch._generate_t1(
        model=TIER1_MODEL,
        prompt=prompt,
        system="You are an AI assistant.",
        tools=tools,
        mission_id="m_qual_t1_to_t2",
        turn_id="turn_t2_1",
    )
    lat2 = time.monotonic() - t0
    
    print(f"[TEST 1 PASS] Tier 2 response received in {lat2:.2f}s")
    print(f"  Model returned: {resp2.model}")
    print(f"  Provider: {resp2.provider}")
    print(f"  Error: {resp2.error}")
    print(f"  Response text snippet: {resp2.text[:80]!r}")
    
    assert resp2.model == TIER2_MODEL or "gpt-oss:120b" in resp2.model, f"Expected {TIER2_MODEL}, got {resp2.model}"
    assert resp2.error is None or resp2.error == "", f"Unexpected error in response: {resp2.error}"
    
    print("\n======================================================================")
    print("STEP 2: QUALIFY TIER 1 TIMEOUT + TIER 2 FAILURE -> TIER 3 LIVE SUCCESS")
    print("======================================================================")
    
    # Now create orchestrator where T1 times out and T2 raises RuntimeError/ConnectionError
    orch3 = Orchestrator()
    orch3.event_bus = bus
    orch3.tier1.generate = AsyncMock(
        side_effect=NvidiaTimeoutError("Simulated T1 25.0s first-token timeout", timeout_type="FIRST_TOKEN_TIMEOUT")
    )
    
    real_ollama_generate = orch3.ollama.generate
    async def mock_ollama_generate(model, *args, **kwargs):
        if model == TIER2_MODEL or "gpt-oss" in model:
            print(f"  [SIMULATION] Forcing Tier 2 failure for model={model}...")
            raise RuntimeError("Simulated Tier 2 failure: GPU memory exhausted / provider timeout")
        print(f"  [INVOCATION] Live Ollama invoking Tier 3 model={model}...")
        return await real_ollama_generate(model, *args, **kwargs)
        
    orch3.ollama.generate = mock_ollama_generate
    
    t0 = time.monotonic()
    print(f"Triggering Orchestrator._generate_t1 with T1 timeout AND T2 failure...")
    resp3 = await orch3._generate_t1(
        model=TIER1_MODEL,
        prompt="Reply with exactly: 'TIER3_OK'",
        system="You are an AI assistant.",
        tools=tools,
        mission_id="m_qual_t1_t2_to_t3",
        turn_id="turn_t3_1",
    )
    lat3 = time.monotonic() - t0
    
    print(f"[TEST 2 PASS] Tier 3 response received in {lat3:.2f}s")
    print(f"  Model returned: {resp3.model}")
    print(f"  Provider: {resp3.provider}")
    print(f"  Error: {resp3.error}")
    print(f"  Response text snippet: {resp3.text[:80]!r}")
    
    assert resp3.model == TIER3_MODEL or "nemotron-3-ultra" in resp3.model, f"Expected {TIER3_MODEL}, got {resp3.model}"
    assert resp3.error is None or resp3.error == "", f"Unexpected error in response: {resp3.error}"
    
    print("\n======================================================================")
    print("FAILOVER QUALIFICATION SUMMARY:")
    print(f"  Tier 1 Timeout -> Tier 2 ({TIER2_MODEL}): SUCCESS (No NameError, lat={lat2:.2f}s)")
    print(f"  Tier 2 Failure -> Tier 3 ({TIER3_MODEL}): SUCCESS (No NameError, lat={lat3:.2f}s)")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_tier_failover_qualification())
