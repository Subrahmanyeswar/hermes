"""
HERMES 2.x - Provider Resilience Qualification Test Suite
Validates:
- Scenario 9: HTTP 429 Rate Limit classification and backoff
- Scenario 10: HTTP 500, 502, 503 Service Unavailable / Server Errors
- Scenario 11: Active inference health probe vs cheap endpoint availability
- Graceful handling of malformed and corrupted model outputs
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.adaptive_routing import AdaptiveRouter, ProviderHealthState
from core.agent_loop.decisions import DecisionInterpreter, AgentDecisionType
from models.common_adapter import NormalizedModelResponse


def test_scenario_9_rate_limit_429_classification():
    """
    Scenario 9: HTTP 429 rate limit errors from providers are classified as
    INVALID with PROVIDER_ERROR tag to prevent tight retry loops.
    """
    interpreter = DecisionInterpreter()
    rate_limit_response = NormalizedModelResponse(
        success=False,
        error="[429 Too Many Requests] Rate limit reached for model gemini-2.5-pro",
        text="",
    )
    decision = interpreter.interpret(rate_limit_response)
    assert decision.decision_type == AgentDecisionType.INVALID
    assert "PROVIDER_ERROR" in decision.reasoning
    assert len(decision.tool_calls) == 0


@pytest.mark.parametrize("status_code,err_msg", [
    (500, "Internal Server Error: Unexpected failure in provider infrastructure"),
    (502, "Bad Gateway: Upstream inference cluster unresponsive"),
    (503, "Service Unavailable: Model is overloaded. Please try again later."),
])
def test_scenario_10_server_error_failover(status_code: int, err_msg: str):
    """
    Scenario 10: HTTP 500, 502, 503 errors trigger circuit degradation and provider failure recording.
    """
    router = AdaptiveRouter()
    interpreter = DecisionInterpreter()

    resp = NormalizedModelResponse(
        success=False,
        error=f"[{status_code}] {err_msg}",
        text="",
    )
    decision = interpreter.interpret(resp)
    assert decision.decision_type == AgentDecisionType.INVALID
    assert "PROVIDER_ERROR" in decision.reasoning

    # Record failure on router
    router.record_failure(tier=1, error=RuntimeError(resp.error))
    health = router.get_health(1)
    assert health.state in (ProviderHealthState.DEGRADED, ProviderHealthState.OPEN_CIRCUIT)


@pytest.mark.asyncio
async def test_scenario_11_active_inference_probe_requirement():
    """
    Scenario 11: Background probes require actual model inference.
    A server endpoint that responds HTTP 200 to /health but fails inference
    MUST NOT be marked HEALTHY.
    """
    router = AdaptiveRouter()

    # Client A: Endpoint is responsive, but lacks generate method
    fake_client_no_gen = MagicMock()
    fake_client_no_gen.is_running = AsyncMock(return_value=True)
    del fake_client_no_gen.generate  # No generate method

    probe_result_a = await router._run_probe(tier=1, client=fake_client_no_gen)
    assert probe_result_a is False, "Endpoint without inference capability must not pass health probe"

    # Reset probe in flight
    router.get_health(1).probe_in_flight = False

    # Client B: Endpoint is responsive, but generate() raises error (e.g. out of memory / queue full)
    fake_client_failing_gen = MagicMock()
    fake_client_failing_gen.is_running = AsyncMock(return_value=True)
    fake_client_failing_gen.generate = AsyncMock(side_effect=RuntimeError("503 Backend overloaded"))

    probe_result_b = await router._run_probe(tier=1, client=fake_client_failing_gen)
    assert probe_result_b is False, "Client with failing generation must fail health probe"

    # Reset probe in flight
    router.get_health(1).probe_in_flight = False

    # Client C: Active inference succeeds
    fake_client_working = MagicMock()
    fake_client_working.is_running = AsyncMock(return_value=True)
    fake_client_working.generate = AsyncMock(return_value=NormalizedModelResponse(success=True, text="pong"))

    probe_result_c = await router._run_probe(tier=1, client=fake_client_working)
    assert probe_result_c is True, "Client with active inference success must pass health probe"


def test_malformed_and_truncated_json_tool_calls():
    """
    Ensure DecisionInterpreter handles truncated or malformed JSON blocks without throwing exceptions.
    """
    interpreter = DecisionInterpreter()
    malformed_inputs = [
        '```json\n{"action": "fs.write", "path": "index.html", "content": "incomplete',
        '{"action": "exec", "command": }',
        'Not a json at all but has { unclosed braces',
        '',
    ]
    for text in malformed_inputs:
        resp = NormalizedModelResponse(success=True, text=text)
        decision = interpreter.interpret(resp)
        assert decision.decision_type in (AgentDecisionType.INVALID, AgentDecisionType.CONTINUE_REASONING)
        assert len(decision.tool_calls) == 0
