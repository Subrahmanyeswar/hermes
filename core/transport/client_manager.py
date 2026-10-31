# core/transport/client_manager.py
"""
HERMES Phase 6: HTTP Client Lifetime and Connection Pool Management.
Ensures:
1. Reusable, connection-pooled AsyncClient per provider endpoint.
2. Request isolation (cancelling Mission A never closes Mission B's shared client).
3. Explicit FastAPI lifespan / service-level lifecycle management.
4. Clean shutdown closing all connections without resource leaks.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional
import httpx
from loguru import logger

from core.transport.types import ErrorCategory, StructuredTransportError


class TransportClientManager:
    """
    Manages long-lived HTTP client pools across model providers (NVIDIA NIM, Ollama).
    Guarantees thread-safe / async-safe access, pool limits, and explicit shutdown.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def get_client(
        self,
        base_url: str,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
        write_timeout: float = 15.0,
        pool_timeout: float = 10.0,
        max_connections: int = 20,
        max_keepalive: int = 10,
    ) -> httpx.AsyncClient:
        """
        Return an existing active AsyncClient for base_url, or instantiate a new one
        with the specified layered timeouts and pool limits.
        """
        clean_url = base_url.rstrip("/")
        if self._closed:
            raise StructuredTransportError(
                category=ErrorCategory.CANCELLED_BY_SHUTDOWN,
                message="Transport client manager is closed due to application shutdown.",
                provider="transport",
                model="",
                retryable=False,
            )

        async with self._lock:
            client = self._clients.get(clean_url)
            if client is None or client.is_closed:
                timeout = httpx.Timeout(
                    timeout=max(read_timeout, 120.0),
                    connect=connect_timeout,
                    read=read_timeout,
                    write=write_timeout,
                    pool=pool_timeout,
                )
                limits = httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive,
                )
                client = httpx.AsyncClient(timeout=timeout, limits=limits)
                self._clients[clean_url] = client
                logger.debug(f"TransportClientManager: created pooled client for {clean_url}")
            return client

    async def close_client(self, base_url: str) -> None:
        """Close a specific client pool gracefully."""
        clean_url = base_url.rstrip("/")
        async with self._lock:
            client = self._clients.pop(clean_url, None)
            if client is not None and not client.is_closed:
                await client.aclose()
                logger.debug(f"TransportClientManager: closed client for {clean_url}")

    async def aclose(self) -> None:
        """Close all managed clients on application shutdown."""
        self._closed = True
        async with self._lock:
            for url, client in list(self._clients.items()):
                if not client.is_closed:
                    try:
                        await client.aclose()
                    except Exception as e:
                        logger.warning(f"Error closing client for {url}: {e}")
            self._clients.clear()
            logger.info("TransportClientManager: all HTTP client pools closed.")


# Process-wide singleton
transport_client_manager = TransportClientManager()
