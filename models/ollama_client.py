# models/ollama_client.py
# Ollama API client for HERMES.
# All calls use keep_alive=0 to release VRAM immediately after generation.
# This is the ONLY file that makes HTTP calls to Ollama.

import time
from typing import Any

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class OllamaTimeoutError(Exception):
    """Raised when Ollama takes more than timeout_seconds to respond."""


class OllamaConnectionError(Exception):
    """Raised when Ollama is not running or is otherwise unreachable."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OllamaClient:
    """Single gateway for all HTTP communication with the Ollama API server."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_seconds: int = 120,
        num_ctx: int = 4096,
    ) -> None:
        """Store connection configuration; no network calls are made here."""
        self.base_url: str = base_url.rstrip("/")
        self.timeout_seconds: int = timeout_seconds
        self.num_ctx: int = num_ctx

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        keep_alive: int = 0,
        temperature: float = 0.1,
        num_ctx: int = 4096,
    ) -> str:
        """
        Send a generation request to Ollama and return the response text.

        Temperature guidelines:
        - 0.05 - 0.1: Tool call generation (deterministic JSON required)
        - 0.1 - 0.2:  Code writing (consistent implementation)
        - 0.2 - 0.3:  Planning and decomposition (some creativity needed)
        - 0.3 - 0.5:  Design decisions (flexibility needed)
        Never go above 0.5 for tool-call generation — malformed JSON increases.

        Raises:
            OllamaTimeoutError: if the request exceeds timeout_seconds.
            OllamaConnectionError: if Ollama is not reachable.
            RuntimeError: if Ollama returns an ``error`` field in the response.
        """
        url: str = f"{self.base_url}/api/generate"
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "keep_alive": keep_alive,
            "stream": False,
            "options": {
                "num_ctx": num_ctx if num_ctx else self.num_ctx,
                "temperature": temperature,
            },
        }

        logger.debug(
            "OllamaClient.generate | model={} | prompt_len={} chars",
            model,
            len(prompt),
        )

        start: float = time.perf_counter()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds)
            ) as client:
                response: httpx.Response = await client.post(url, json=body)

        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {self.timeout_seconds}s"
            ) from exc

        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Is the Ollama server running?"
            ) from exc

        elapsed: float = time.perf_counter() - start

        data: dict[str, Any] = response.json()

        if "error" in data:
            raise RuntimeError(data["error"])

        result: str = data["response"]

        logger.debug(
            "OllamaClient.generate | model={} | response_len={} chars | elapsed={:.3f}s",
            model,
            len(result),
            elapsed,
        )

        return result

    async def is_running(self) -> bool:
        """Return True if Ollama responds with HTTP 200, False for any error.

        Never raises; safe to use as a startup health check.
        """
        url: str = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds)
            ) as client:
                response: httpx.Response = await client.get(url)
            return response.status_code == 200
        except Exception:  # noqa: BLE001 — intentionally broad: method must never raise
            return False

    async def list_models(self) -> list[str]:
        """Return a list of locally available Ollama model name strings.

        Returns an empty list on any error; never raises.
        """
        url: str = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds)
            ) as client:
                response: httpx.Response = await client.get(url)
            data: dict[str, Any] = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:  # noqa: BLE001 — intentionally broad: method must never raise
            return []
