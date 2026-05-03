# tests/test_ollama_client.py
# Test suite for models/ollama_client.py
# Run with: pytest tests/test_ollama_client.py -v

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio  # noqa: F401 — registers asyncio mode

from models.ollama_client import OllamaClient, OllamaConnectionError, OllamaTimeoutError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a minimal mock that behaves like httpx.Response."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    return mock_response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_calls_correct_endpoint() -> None:
    """generate() must POST to /api/generate with keep_alive=0, stream=False,
    and return the 'response' field from the JSON body."""
    client = OllamaClient()
    mock_response = _make_response({"response": "hello world"})

    mock_post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient.post", mock_post):
        result = await client.generate(
            model="qwen2.5-coder:7b",
            prompt="Say hello",
        )

    # Return value
    assert result == "hello world"

    # Verify the call
    mock_post.assert_awaited_once()
    call_args = mock_post.call_args

    # URL
    called_url: str = call_args.args[0] if call_args.args else call_args.kwargs["url"]
    assert called_url == "http://localhost:11434/api/generate"

    # Body (passed as json= kwarg)
    body: dict = call_args.kwargs["json"]
    assert body["keep_alive"] == 0
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_generate_raises_timeout_error() -> None:
    """generate() must raise OllamaTimeoutError when httpx raises TimeoutException."""
    client = OllamaClient()

    mock_post = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=MagicMock())
    )

    with patch("httpx.AsyncClient.post", mock_post):
        with pytest.raises(OllamaTimeoutError):
            await client.generate(model="qwen2.5-coder:7b", prompt="test")


@pytest.mark.asyncio
async def test_generate_raises_connection_error() -> None:
    """generate() must raise OllamaConnectionError when httpx raises ConnectError."""
    client = OllamaClient()

    mock_post = AsyncMock(
        side_effect=httpx.ConnectError("connection refused", request=MagicMock())
    )

    with patch("httpx.AsyncClient.post", mock_post):
        with pytest.raises(OllamaConnectionError):
            await client.generate(model="qwen2.5-coder:7b", prompt="test")


@pytest.mark.asyncio
async def test_is_running_returns_true_on_200() -> None:
    """is_running() must return True when the /api/tags endpoint responds with 200."""
    client = OllamaClient()
    mock_response = _make_response({"models": []}, status_code=200)

    mock_get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient.get", mock_get):
        result = await client.is_running()

    assert result is True


@pytest.mark.asyncio
async def test_is_running_returns_false_on_error() -> None:
    """is_running() must return False (never raise) when any exception occurs."""
    client = OllamaClient()

    mock_get = AsyncMock(side_effect=httpx.ConnectError("offline", request=MagicMock()))

    with patch("httpx.AsyncClient.get", mock_get):
        result = await client.is_running()

    assert result is False
