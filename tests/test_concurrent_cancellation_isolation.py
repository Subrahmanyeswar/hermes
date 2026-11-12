"""
HERMES 2.x — Task 2: Concurrent Cancellation Isolation Verification.
Verifies:
- Request A starts streaming.
- Request B starts streaming through the same provider client.
- Request A is cancelled.
- Request B must continue and complete successfully.
- Cancelling one request does not unexpectedly close a shared HTTP session or disrupt unrelated active requests.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from models.nvidia_client import NvidiaClient
from models.common_adapter import CommonProviderAdapter, NormalizedModelResponse


@pytest.mark.asyncio
async def test_nvidia_client_concurrent_cancellation_isolation():
    """Verify NvidiaClient: cancelling Request A while streaming does not disrupt Request B."""
    client = NvidiaClient(api_key="test_key", base_url="https://api.nvidia.com/v1")

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False

    req_a_started = asyncio.Event()
    req_b_started = asyncio.Event()
    req_a_cancelled = False
    req_b_completed = False

    def mock_stream_impl(method, url, json=None, headers=None, **kwargs):
        class MockStreamContext:
            def __init__(self, is_req_a: bool):
                self.is_req_a = is_req_a
                self.status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            async def aiter_lines(self):
                if self.is_req_a:
                    req_a_started.set()
                    try:
                        while True:
                            yield 'data: {"choices": [{"delta": {"content": "chunk_a"}}]}'
                            await asyncio.sleep(0.05)
                    except asyncio.CancelledError:
                        nonlocal req_a_cancelled
                        req_a_cancelled = True
                        raise
                else:
                    req_b_started.set()
                    for i in range(3):
                        yield f'data: {{"choices": [{{"delta": {{"content": "chunk_b_{i}"}}}}]}}'
                        await asyncio.sleep(0.05)
                    nonlocal req_b_completed
                    req_b_completed = True
                    yield 'data: [DONE]'

        prompt = (json.get("messages", [{}])[-1].get("content") or "") if json else ""
        is_a = "request_a" in prompt
        return MockStreamContext(is_req_a=is_a)

    mock_http_client.stream = MagicMock(side_effect=mock_stream_impl)

    with patch("core.transport.client_manager.transport_client_manager.get_client", AsyncMock(return_value=mock_http_client)):
        task_a = asyncio.create_task(client.generate(prompt="request_a", stream=True))
        task_b = asyncio.create_task(client.generate(prompt="request_b", stream=True))

        await asyncio.wait_for(asyncio.gather(req_a_started.wait(), req_b_started.wait()), timeout=2.0)

        task_a.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task_a

        resp_b = await asyncio.wait_for(task_b, timeout=3.0)

    assert req_a_cancelled is True
    assert req_b_completed is True
    assert resp_b.success is True
    assert "chunk_b" in resp_b.content or "chunk_b" in resp_b.text
    assert mock_http_client.is_closed is False


@pytest.mark.asyncio
async def test_common_adapter_concurrent_cancellation_isolation():
    """Verify CommonProviderAdapter: cancelling Request A while streaming does not disrupt Request B."""
    adapter = CommonProviderAdapter(
        provider_name="openrouter",
        model_name="qwen/qwen-2.5-coder-32b-instruct",
        api_key="test_key",
        base_url="https://openrouter.ai/api/v1"
    )

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False
    adapter._client = mock_http_client
    adapter._client_loop = asyncio.get_running_loop()

    req_a_started = asyncio.Event()
    req_b_started = asyncio.Event()
    req_a_cancelled = False
    req_b_completed = False

    def mock_stream_impl(method, url, headers=None, json=None, timeout=None, **kwargs):
        class MockStreamContext:
            def __init__(self, is_req_a: bool):
                self.is_req_a = is_req_a
                self.status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

            async def aiter_lines(self):
                if self.is_req_a:
                    req_a_started.set()
                    try:
                        while True:
                            yield 'data: {"choices": [{"delta": {"content": "part_a"}}]}'
                            await asyncio.sleep(0.05)
                    except asyncio.CancelledError:
                        nonlocal req_a_cancelled
                        req_a_cancelled = True
                        raise
                else:
                    req_b_started.set()
                    for i in range(3):
                        yield f'data: {{"choices": [{{"delta": {{"content": "part_b_{i}"}}}}]}}'
                        await asyncio.sleep(0.05)
                    nonlocal req_b_completed
                    req_b_completed = True
                    yield 'data: [DONE]'

        prompt = (json.get("messages", [{}])[-1].get("content") or "") if json else ""
        is_a = "req_a" in prompt
        return MockStreamContext(is_req_a=is_a)

    mock_http_client.stream = MagicMock(side_effect=mock_stream_impl)

    task_a = asyncio.create_task(adapter.generate(prompt="req_a", stream=True))
    task_b = asyncio.create_task(adapter.generate(prompt="req_b", stream=True))

    await asyncio.wait_for(asyncio.gather(req_a_started.wait(), req_b_started.wait()), timeout=2.0)

    task_a.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task_a

    resp_b = await asyncio.wait_for(task_b, timeout=3.0)

    assert req_a_cancelled is True
    assert req_b_completed is True
    assert resp_b.success is True
    assert "part_b" in resp_b.text or "part_b" in resp_b.content
    assert adapter._client is not None
    assert adapter._client.is_closed is False
