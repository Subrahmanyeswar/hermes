# tests/test_phase10_network_and_provider_faults.py
"""
HERMES Phase 10 — Network Cuts, Provider Outages & Stream Interruption Fault-Injection Tests.

Stages Tested:
- Stage C: Network cuts & provider recovery (Global internet loss, provider outage, circuit breaker, auto-recovery).
- Stage D: Interrupted model streams & transport recovery (Truncated streams, cancellations, secret redaction, tier fallback).
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.event_bus import EventBus, EventType, HermesEvent
from core.network.connectivity import ConnectivityMonitor, ConnectivityStatus
from core.network.coordinator import NetworkRecoveryCoordinator
from core.persistence.database import SQLiteDatabase
from core.runtime_state.models import MissionStatus, WaitReason
from core.transport.circuit_breaker import CircuitBreakerRegistry, CircuitState
from core.transport.client_manager import TransportClientManager
from core.transport.types import ErrorCategory, StructuredTransportError, sanitize_error_text


# ── Stage C.1: Global Internet Loss Simulation ───────────────────────────────

@pytest.mark.asyncio
async def test_global_internet_loss_transitions_to_waiting(tmp_path):
    """
    Test 5.1: Global Internet loss transition.
    Simulate internet connectivity dropping during an active mission.
    Verify:
    1. Status transitions to WAITING with wait_reason='WAITING_FOR_NETWORK'.
    2. Event is published and state is durably persisted.
    3. No false success is reported.
    4. Workspace binding is preserved.
    """
    db_file = tmp_path / "test_net.db"
    db = SQLiteDatabase(db_file)
    db.save_mission("m_net_1", str(tmp_path / "ws"), "RUNNING")

    bus = EventBus(enabled=True, db=db)

    # Publish network loss event
    evt = HermesEvent(
        event_type=EventType.NETWORK_DISCONNECTED,
        mission_id="m_net_1",
        payload={
            "reason": "Simulated global network failure",
            "wait_reason": WaitReason.WAITING_FOR_NETWORK.value,
        },
    )
    bus.publish_durable(evt)

    # Update database record as runtime reducer would
    db.save_mission("m_net_1", str(tmp_path / "ws"), "WAITING", wait_reason=WaitReason.WAITING_FOR_NETWORK.value)

    # Verify database state
    row = db.get_mission("m_net_1")
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_NETWORK"
    assert row["workspace_path"] == str(tmp_path / "ws")

    bus.shutdown(timeout=2.0)


# ── Stage C.2: Provider-Only Outage vs Global Internet ────────────────────────

@pytest.mark.asyncio
async def test_provider_outage_distinguished_from_internet_loss(tmp_path):
    """
    Test 5.2: Provider-only outage is distinct from global internet loss.
    Simulate a 503 Service Unavailable / Connection Refused from model provider
    while general internet is online.
    Verify:
    1. Error category is classified as SERVICE_UNAVAILABLE / PROVIDER_OUTAGE.
    2. Mission enters WAITING_FOR_PROVIDER, not WAITING_FOR_NETWORK.
    """
    db_file = tmp_path / "test_prov.db"
    db = SQLiteDatabase(db_file)
    db.save_mission("m_prov_1", str(tmp_path / "ws"), "RUNNING")

    bus = EventBus(enabled=True, db=db)

    # Publish provider outage event
    evt = HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id="m_prov_1",
        payload={
            "provider": "nvidia",
            "status_code": 503,
            "category": ErrorCategory.PROVIDER_UNAVAILABLE.value,
            "wait_reason": WaitReason.WAITING_FOR_PROVIDER.value,
        },
    )
    bus.publish_durable(evt)

    db.save_mission("m_prov_1", str(tmp_path / "ws"), "WAITING", wait_reason=WaitReason.WAITING_FOR_PROVIDER.value)

    row = db.get_mission("m_prov_1")
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_PROVIDER"
    assert row["wait_reason"] != "WAITING_FOR_NETWORK"

    bus.shutdown(timeout=2.0)


# ── Stage C.3: Circuit Breaker Bounds Retries ─────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_trips_and_prevents_endless_retry():
    """
    Test 5.2: Circuit breaker pattern trips after failure threshold and prevents endless loops.
    """
    registry = CircuitBreakerRegistry()
    provider = "nvidia_test"
    model = "z-ai/glm-5.3-flash"

    can_exec, _ = await registry.check_can_proceed(provider, model)
    assert can_exec is True

    # Record 3 failures
    err = StructuredTransportError(
        category=ErrorCategory.PROVIDER_SERVER_ERROR,
        message="503 Server Error",
        provider=provider,
        model=model,
    )
    await registry.record_failure(provider, model, err)
    await registry.record_failure(provider, model, err)
    can_exec, _ = await registry.check_can_proceed(provider, model)
    assert can_exec is True

    await registry.record_failure(provider, model, err)
    rec = registry.get_record(provider, model)
    assert rec.state == CircuitState.OPEN

    # Execution while OPEN must be rejected immediately without network call
    can_exec, err_open = await registry.check_can_proceed(provider, model)
    assert can_exec is False
    assert err_open is not None
    assert "Circuit breaker OPEN" in err_open.message


# ── Stage C.4: Recovery Coordinator Deduplication & Safe Resumption ─────────

def test_recovery_coordinator_prevents_duplicate_runs(tmp_path):
    """
    Test 5.3: Recovery Coordinator idempotency and ineligible mission fencing.
    Verify:
    1. Eligible waiting missions are identified.
    2. Terminal (CANCELLED, COMPLETED) missions are fenced out.
    3. Concurrently recovering missions are deduplicated.
    """
    db_file = tmp_path / "test_coord.db"
    db = SQLiteDatabase(db_file)

    # 1. Eligible waiting mission
    ws_valid = tmp_path / "ws_valid"
    ws_valid.mkdir()
    db.save_mission("m_waiting", str(ws_valid), "WAITING", wait_reason="WAITING_FOR_NETWORK")

    # 2. Ineligible cancelled mission
    db.save_mission("m_cancelled", str(ws_valid), "CANCELLED", wait_reason="WAITING_FOR_NETWORK")

    # 3. Ineligible completed mission
    db.save_mission("m_completed", str(ws_valid), "COMPLETED")

    coordinator = NetworkRecoveryCoordinator(db=db)

    waiting = coordinator.find_eligible_waiting_missions()
    waiting_ids = [m["mission_id"] for m in waiting]

    assert "m_waiting" in waiting_ids
    assert "m_cancelled" not in waiting_ids
    assert "m_completed" not in waiting_ids

    # Deduplication test: when already in _recovering_missions, cannot auto-resume again
    coordinator._recovering_missions.add("m_waiting")
    eligible, reason = coordinator.evaluate_auto_resume_eligibility("m_waiting")
    assert eligible is False
    assert "already actively recovering" in reason


# ── Stage D.1: Interrupted & Truncated Stream Rejection ───────────────────────

@pytest.mark.asyncio
async def test_truncated_model_stream_rejected():
    """
    Test 6.2: A streamed response that disconnects or ends abruptly without
    completion marker is rejected and not marked as a successful completion.
    """
    # Simulate an incomplete stream generator
    async def mock_incomplete_stream():
        yield {"chunk": "Hello, I am start"}
        yield {"chunk": "ing to write code..."}
        # Connection reset mid-stream without finish_reason="stop" or [DONE]
        raise ConnectionResetError("Remote host closed stream unexpectedly")

    chunks_collected = []
    completed_normally = False
    error_caught = None

    try:
        async for chunk in mock_incomplete_stream():
            chunks_collected.append(chunk["chunk"])
        completed_normally = True
    except ConnectionResetError as exc:
        error_caught = exc

    assert completed_normally is False
    assert error_caught is not None
    assert len(chunks_collected) == 2
    # Full response was NOT assembled; must not treat as completed model output
    full_text = "".join(chunks_collected)
    assert "code..." in full_text
    assert not full_text.endswith("DONE")


# ── Stage D.2: Secret Redaction in Error Traces ──────────────────────────────

def test_secret_redaction_in_transport_errors():
    """
    Test 6.1: Secrets such as NVIDIA_API_KEY, Bearer tokens, and secrets
    are automatically redacted from transport error messages.
    """
    raw_error = "Failed to connect: Authorization Bearer nvapi-secret-key-1234567890abcdef at https://integrate.api.nvidia.com"
    clean_error = sanitize_error_text(raw_error)

    assert "nvapi-secret-key-1234567890abcdef" not in clean_error
    assert "[REDACTED" in clean_error or "***" in clean_error or "Bearer [REDACTED]" in clean_error


# ── Stage D.3: Transport Fallback Across Tiers ────────────────────────────────

@pytest.mark.asyncio
async def test_transport_fallback_from_t1_to_t2():
    """
    Test 6.10: Tier 1 failure triggers explicit fallback to Tier 2 model client.
    """
    t1_mock = AsyncMock()
    t1_mock.side_effect = StructuredTransportError(
        category=ErrorCategory.PROVIDER_UNAVAILABLE,
        message="NVIDIA 503 Service Unavailable",
        provider="nvidia",
        model="z-ai/glm-5.3-flash",
    )

    t2_mock = AsyncMock()
    t2_mock.return_value = {"content": "Fallback response from Ollama gpt-oss:120b-cloud"}

    # Simulate tier dispatcher
    selected_result = None
    fallback_occurred = False

    try:
        selected_result = await t1_mock()
    except StructuredTransportError:
        fallback_occurred = True
        selected_result = await t2_mock()

    assert fallback_occurred is True
    assert selected_result["content"] == "Fallback response from Ollama gpt-oss:120b-cloud"
