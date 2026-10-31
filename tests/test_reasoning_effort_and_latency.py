"""
Regression and unit tests for HERMES reasoning effort policy, model latency optimization,
duplicate thinking event suppression, stall guard for reasoning-only turns, and telemetry secret redaction.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.telemetry import ModelCallTelemetry, redact_telemetry_secrets
from models.nvidia_client import NvidiaClient
from core.orchestrator import Orchestrator
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig, AgentDecision, AgentDecisionType
from core.runtime_state.events import EventType
from core.event_bus import EventBus
from core.mission_planner import Mission


def test_telemetry_secret_redaction():
    """Verify secrets, Bearer tokens, and API keys are strictly redacted in telemetry."""
    raw_data = {
        "api_key": "nvapi-1234567890abcdef",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "system_prompt": "You are HERMES using key sk-abcdef123456.",
        "nested": {
            "token": "secret_token_value",
            "safe_field": "safe_value",
            "url": "https://api.nvidia.com/v1?token=secret123"
        }
    }
    redacted = redact_telemetry_secrets(raw_data)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert "sk-abcdef123456" not in redacted["system_prompt"]
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "safe_value"

    mc = ModelCallTelemetry(
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
        reasoning_effort="low",
        attempt_index=0,
        finish_reason="stop",
        max_idle_interval_ms=125.4,
    )
    d = mc.to_dict()
    assert d["reasoning_effort"] == "low"
    assert d["attempt_index"] == 0
    assert d["max_idle_interval_ms"] == 125.4


def test_nvidia_payload_reasoning_effort():
    """Verify NvidiaClient respects explicit reasoning_effort and defaults Nemotron to 'low'."""
    client = NvidiaClient(api_key="test-key")
    
    # 1. Explicit 'none'
    captured_payloads = []
    async def mock_post(url, json=None, **kwargs):
        captured_payloads.append(json)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }
        return mock_resp

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post
        mock_get_client.return_value = mock_http

        # Call with reasoning_effort="none"
        asyncio.run(client.generate(
            model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            prompt="list files",
            reasoning_effort="none",
            stream=False,
        ))
        assert captured_payloads[-1]["reasoning_effort"] == "none"

        # Call with reasoning_effort="low"
        asyncio.run(client.generate(
            model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            prompt="write code",
            reasoning_effort="low",
            stream=False,
        ))
        assert captured_payloads[-1]["reasoning_effort"] == "low"

        # Call without reasoning_effort specified -> defaults to 'low' for Nemotron
        asyncio.run(client.generate(
            model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            prompt="general prompt",
            stream=False,
        ))
        assert captured_payloads[-1]["reasoning_effort"] == "low"


def test_reasoning_policy_determination():
    """Verify AgentLoop._determine_reasoning_policy assigns appropriate effort and token caps."""
    loop = AgentLoop.__new__(AgentLoop)
    loop.mission = MagicMock()
    loop.mission.user_prompt = "Build a complete Three.js cinematic rocket simulation website"

    # 1. Complex 3D scene / shader prompt -> 'high', 8192
    effort, max_tokens = loop._determine_reasoning_policy(
        user_message="Implement the main.js shader material, particle system, and camera trajectory",
        turn_id="turn_1"
    )
    assert effort == "high"
    assert max_tokens == 8192

    # 2. Routine inspection / file reading -> 'none', 4096
    effort, max_tokens = loop._determine_reasoning_policy(
        user_message="read_file index.html and verify whether script tag is present",
        turn_id="turn_2"
    )
    assert effort == "none"
    assert max_tokens == 4096

    # 3. Routine scaffolding (package.json, style.css, etc.) -> 'low', 8192
    effort, max_tokens = loop._determine_reasoning_policy(
        user_message="Create package.json and style.css for the application",
        turn_id="turn_3"
    )
    assert effort == "low"
    assert max_tokens == 8192

    # 4. Recovery escalation active -> 'high', 8192
    loop._consecutive_empty_turns = 1
    effort, max_tokens = loop._determine_reasoning_policy(
        user_message="Any message while recovering from a stall",
        turn_id="turn_4"
    )
    assert effort == "high"
    assert max_tokens == 8192


@pytest.mark.asyncio
async def test_suppress_duplicate_model_completed_event():
    """Verify suppress_model_completed_event prevents Orchestrator from emitting duplicate MODEL_COMPLETED."""
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e), {EventType.MODEL_COMPLETED})

    orch = Orchestrator.__new__(Orchestrator)
    orch.event_bus = bus
    mock_t1 = AsyncMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    mock_t1.generate.return_value = MagicMock(
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
        provider="nvidia_nim",
        text="done"
    )
    orch.tier1 = mock_t1
    orch.active_t1_client = mock_t1
    orch.ollama = None

    # Call with suppress_model_completed_event=True (from AgentLoop)
    with patch("core.orchestrator.TIER1_PROVIDER", "nvidia_nim"):
        with patch("core.orchestrator.TIER1_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"):
            with patch("core.adaptive_routing.adaptive_router.record_success"):
                await orch._generate_t1(
                    prompt="test",
                    mission_id="m_dup_test",
                    turn_id="turn_1",
                    suppress_model_completed_event=True
                )
    
    # Should not have emitted MODEL_COMPLETED
    assert len(events) == 0

    # Call with suppress_model_completed_event=False (standalone orchestrator call)
    with patch("core.orchestrator.TIER1_PROVIDER", "nvidia_nim"):
        with patch("core.orchestrator.TIER1_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"):
            with patch("core.adaptive_routing.adaptive_router.record_success"):
                await orch._generate_t1(
                    prompt="test",
                    mission_id="m_dup_test",
                    turn_id="turn_2",
                    suppress_model_completed_event=False
                )
    assert len(events) == 1
    assert events[0].turn_id == "turn_2"
    assert "Thought for" in events[0].payload.get("headline", "")
    bus.shutdown()
