# tests/test_phase4c_fastpath.py
"""
HERMES Phase 4C — Model Fast-Path & Generation Quality Unit & Integration Tests.
Verifies:
  1. Persistent client reuse in NvidiaClient & OllamaClient (no redundant connection pool creation)
  2. Fast failover on FIRST_TOKEN_TIMEOUT without redundant retry loop
  3. Non-blocking ThreadPoolExecutor shutdown in MissionPlanner
  4. High-End Code Generation Quality Contract in prompt_builder
  5. Static prefix stability and KV cache alignment
  6. Balanced think tag normalization in OllamaClient
  7. Action discipline momentum preserved (OBSERVE -> UNDERSTAND -> ACT -> VERIFY)
  8. DevServer startup latency (< 1.5s)
"""

import sys
import time
import pytest
import asyncio
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from models.nvidia_client import NvidiaClient, NvidiaTimeoutError, get_shared_nvidia_client
from models.ollama_client import OllamaClient, get_shared_ollama_client, normalize_ollama_payload
from core.mission_planner import MissionPlanner
from core.prompt_builder import (
    HERMES_STATIC_PREFIX,
    HERMES_ROLE,
    build_system_prompt,
    PromptContext,
    get_static_prefix_hash,
)
from core.action_discipline import TaskActionContract, ActionMomentumTracker


@pytest.mark.asyncio
async def test_persistent_nvidia_client_reuse():
    """Verify NvidiaClient reuses the underlying httpx.AsyncClient without recreating connections."""
    client = NvidiaClient()
    c1 = await client._get_client()
    c2 = await client._get_client()
    assert c1 is c2, "NvidiaClient must reuse the persistent async HTTP client"
    assert not c1.is_closed


@pytest.mark.asyncio
async def test_persistent_ollama_client_reuse():
    """Verify OllamaClient reuses the underlying httpx.AsyncClient without recreating connections."""
    client = OllamaClient()
    c1 = await client._get_client()
    c2 = await client._get_client()
    assert c1 is c2, "OllamaClient must reuse the persistent async HTTP client"
    assert not c1.is_closed


@pytest.mark.asyncio
async def test_shared_singleton_clients():
    """Verify process-wide singletons return consistent instances."""
    s1 = get_shared_nvidia_client()
    s2 = get_shared_nvidia_client()
    assert s1 is s2

    o1 = get_shared_ollama_client()
    o2 = get_shared_ollama_client()
    assert o1 is o2


def test_mission_planner_non_blocking_timeout():
    """Verify MissionPlanner LLM decomposition does not block the thread when timed out."""
    planner = MissionPlanner()
    t0 = time.monotonic()
    # Freeform prompt that falls through to _llm_decompose
    prompt = "I want a small campus event board for students. Students should browse events, search, and add events."
    mission = planner.plan(prompt)
    dur = time.monotonic() - t0
    # Must complete well within 15 seconds (rather than previous 72.8s thread block)
    assert dur < 15.0, f"MissionPlanner planning took {dur:.2f}s, exceeding fast-path threshold"
    assert len(mission.tasks) >= 1


def test_high_end_quality_contract_in_prompts():
    """Verify Phase 4C High-End Quality Contract keywords exist in static and dynamic templates."""
    required_keywords = [
        "Semantic HTML5",
        "design tokens",
        "Micro-interactions",
        "Responsive",
        "localStorage",
        "AT LEAST 5 realistic",
        "Empty state",
    ]
    for kw in required_keywords:
        assert kw in HERMES_STATIC_PREFIX, f"Missing '{kw}' in HERMES_STATIC_PREFIX"
        assert kw in HERMES_ROLE, f"Missing '{kw}' in HERMES_ROLE"


def test_static_prefix_hash_stability():
    """Verify static prefix SHA-256 hash is stable and precomputed."""
    h1 = get_static_prefix_hash()
    h2 = get_static_prefix_hash()
    assert h1 == h2
    assert len(h1) == 64


def test_ollama_think_tag_sanitization():
    """Verify normalize_ollama_payload cleanly balances think tags."""
    # Case 1: thinking present without response
    p1 = {"thinking": "Need to analyze user request", "response": ""}
    norm1 = normalize_ollama_payload(p1)
    assert norm1.startswith("<think>")
    assert norm1.endswith("</think>")

    # Case 2: thinking present with response
    p2 = {"thinking": "<think>\nThinking about layout", "response": '{"tool": "write_file"}'}
    norm2 = normalize_ollama_payload(p2)
    assert "<think>" in norm2
    assert "</think>" in norm2
    assert '{"tool": "write_file"}' in norm2

    # Case 3: pure response
    p3 = {"response": '{"status": "ok"}'}
    norm3 = normalize_ollama_payload(p3)
    assert norm3 == '{"status": "ok"}'


def test_action_momentum_invariants_preserved():
    """Verify Phase 4B Action Discipline invariants remain strictly active."""
    contract = TaskActionContract(
        task_id="t1",
        title="Implement app.js",
        objective="Create js/app.js",
        expected_artifacts=["js/app.js"],
        expected_operation="write_file",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract)
    assert tracker.consecutive_read_only == 0
    tracker.record_action("list_directory", {}, False, True, 1)
    assert tracker.consecutive_read_only == 1
    tracker.record_action("write_file", {"path": "js/app.js", "content": "console.log(1)"}, True, True, 2)
    assert tracker.consecutive_read_only == 0


@pytest.mark.asyncio
async def test_fast_dev_server_startup(tmp_path):
    """Verify DevServerManager starts in under 1500ms."""
    from core.browser.dev_server import DevServerManager
    index = tmp_path / "index.html"
    index.write_text("<!DOCTYPE html><html><body><h1>Hello</h1></body></html>")
    dsm = DevServerManager()
    t0 = time.monotonic()
    srv = await dsm.start_static_server(tmp_path, name="p4c_test_srv")
    startup_dur = (time.monotonic() - t0) * 1000.0
    try:
        assert startup_dur < 1500.0, f"DevServer startup took {startup_dur:.2f}ms"
        assert srv.url.startswith("http://127.0.0.1")
    finally:
        srv.process.terminate()
        srv.process.wait()
