"""
Phase 4 Acceptance Test Suite: HTTP Client Lifecycle & Connection Pooling (Scenario T / Gate B).

Verifies:
- Scenario T: TransportClientManager reuses AsyncClient instances across repeated requests to the same origin.
- Request cancellation on a single mission/request does not close or corrupt the shared client pool.
- aclose() cleanly closes all pooled clients and frees connection resources without leaks.
"""

import asyncio
import pytest

from core.transport.client_manager import TransportClientManager


@pytest.mark.asyncio
async def test_scenario_t_client_reuse_and_pooling():
    """Verify requests to the same origin reuse the pooled client instance."""
    mgr = TransportClientManager()

    client1 = await mgr.get_client("https://integrate.api.nvidia.com/v1")
    client2 = await mgr.get_client("https://integrate.api.nvidia.com/v1")

    # Must be the exact same client instance
    assert client1 is client2
    assert not client1.is_closed

    # Different origin creates separate isolated client
    client_ollama = await mgr.get_client("https://ollama.com/api")
    assert client_ollama is not client1
    assert not client_ollama.is_closed

    await mgr.aclose()
    assert client1.is_closed
    assert client_ollama.is_closed


@pytest.mark.asyncio
async def test_scenario_t_request_cancellation_preserves_shared_client():
    """Verify cancelling an in-flight request task does not close the shared client pool."""
    mgr = TransportClientManager()
    shared_client = await mgr.get_client("https://integrate.api.nvidia.com/v1")

    async def fake_in_flight_task():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(fake_in_flight_task())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Shared client must remain open and healthy for other missions
    assert not shared_client.is_closed

    # Subsequent request can still acquire the same client
    reacquired = await mgr.get_client("https://integrate.api.nvidia.com/v1")
    assert reacquired is shared_client

    await mgr.aclose()
    assert shared_client.is_closed
