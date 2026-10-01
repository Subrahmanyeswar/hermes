# core/code_intelligence/transport.py
"""
JSON-RPC 2.0 Transport for Language Server Protocol (LSP).
Implements standard stdio framing with Content-Length headers,
request ID tracking, bounded buffers, timeouts, and safe async processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

logger = logging.getLogger("hermes.code_intelligence.transport")


class LspTransportError(Exception):
    """Base error for LSP transport failures."""
    pass


class LspTimeoutError(LspTransportError):
    """Raised when an LSP request times out."""
    pass


class LspConnectionClosedError(LspTransportError):
    """Raised when the LSP transport stream closes prematurely."""
    pass


class StdioLspTransport:
    """
    Subprocess stdio transport implementing LSP JSON-RPC framing.
    Supports asynchronous requests, responses, notifications, and cancellations.
    """

    def __init__(
        self,
        command: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        max_buffer_size: int = 10 * 1024 * 1024,  # 10 MB payload guard
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.max_buffer_size = max_buffer_size

        self._process: Optional[asyncio.subprocess.Process] = None
        self._next_request_id: int = 1
        self._pending_requests: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._notification_handlers: Dict[str, List[Callable[[Dict[str, Any]], Coroutine[Any, Any, None] | None]]] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._closed: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """Launch the language server subprocess and start background stream readers."""
        async with self._lock:
            if self.is_running:
                return

            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    env=self.env,
                )
            except Exception as e:
                logger.error(f"Failed to launch LSP server process {self.command}: {e}")
                raise LspTransportError(f"Failed to start LSP process {self.command}: {e}") from e

            self._closed = False
            self._reader_task = asyncio.create_task(self._stdout_reader_loop(), name="lsp_stdout_reader")
            self._stderr_task = asyncio.create_task(self._stderr_reader_loop(), name="lsp_stderr_reader")
            logger.info(f"LSP server process started (PID {self._process.pid}): {' '.join(self.command)}")

    async def send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> Any:
        """
        Send a JSON-RPC request and wait for the correlated response.
        """
        if not self.is_running or self._process.stdin is None:
            raise LspConnectionClosedError("LSP server process is not running")

        async with self._lock:
            req_id = self._next_request_id
            self._next_request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params if params is not None else {},
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            await self._write_message(payload)
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            # Send cancellation notification to server
            try:
                await self.send_notification("$/cancelRequest", {"id": req_id})
            except Exception:
                pass
            raise LspTimeoutError(f"LSP request '{method}' (id={req_id}) timed out after {timeout}s")
        except Exception:
            self._pending_requests.pop(req_id, None)
            raise

        if "error" in response:
            err = response["error"]
            err_code = err.get("code", -1)
            err_msg = err.get("message", "Unknown LSP error")
            raise LspTransportError(f"LSP Error [{err_code}]: {err_msg}")

        return response.get("result")

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a one-way notification (no response expected)."""
        if not self.is_running or self._process.stdin is None:
            raise LspConnectionClosedError("LSP server process is not running")

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
        }
        await self._write_message(payload)

    def register_notification_handler(
        self,
        method: str,
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None] | None],
    ) -> None:
        """Register a callback for incoming notifications (e.g. textDocument/publishDiagnostics)."""
        handlers = self._notification_handlers.setdefault(method, [])
        if handler not in handlers:
            handlers.append(handler)

    async def _write_message(self, message: Dict[str, Any]) -> None:
        """Encode and frame message according to LSP Content-Length spec."""
        if self._process is None or self._process.stdin is None:
            raise LspConnectionClosedError("Process stdin is closed")

        encoded_body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(encoded_body)}\r\n\r\n".encode("ascii")
        try:
            self._process.stdin.write(header + encoded_body)
            await self._process.stdin.drain()
        except Exception as e:
            logger.error(f"Failed writing to LSP stdin: {e}")
            raise LspConnectionClosedError(f"Failed writing to LSP server: {e}") from e

    async def _stdout_reader_loop(self) -> None:
        """Parse incoming Content-Length delimited JSON-RPC messages from stdout."""
        stdout = self._process.stdout if self._process else None
        if stdout is None:
            return

        buffer = bytearray()
        try:
            while not self._closed and self.is_running:
                # 1. Read header block until \r\n\r\n
                while b"\r\n\r\n" not in buffer:
                    chunk = await stdout.read(4096)
                    if not chunk:
                        return
                    buffer.extend(chunk)
                    if len(buffer) > self.max_buffer_size:
                        raise LspTransportError("LSP stdout buffer exceeded maximum size")

                header_end = buffer.find(b"\r\n\r\n")
                header_data = bytes(buffer[:header_end]).decode("ascii", errors="replace")
                del buffer[: header_end + 4]

                # Parse Content-Length
                content_length: Optional[int] = None
                for line in header_data.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass

                if content_length is None or content_length <= 0:
                    continue

                if content_length > self.max_buffer_size:
                    raise LspTransportError(f"LSP message size {content_length} exceeds limit {self.max_buffer_size}")

                # 2. Read full content body
                while len(buffer) < content_length:
                    chunk = await stdout.read(min(4096, content_length - len(buffer)))
                    if not chunk:
                        return
                    buffer.extend(chunk)

                body_data = bytes(buffer[:content_length]).decode("utf-8", errors="replace")
                del buffer[:content_length]

                try:
                    parsed = json.loads(body_data)
                    self._dispatch_incoming(parsed)
                except Exception as e:
                    logger.warning(f"Error parsing/dispatching LSP message: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closed:
                logger.error(f"LSP stdout reader error: {e}")
        finally:
            self._fail_all_pending("LSP stdout stream closed")

    async def _stderr_reader_loop(self) -> None:
        """Log diagnostic output from server stderr."""
        stderr = self._process.stderr if self._process else None
        if stderr is None:
            return

        try:
            while not self._closed and self.is_running:
                line = await stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug(f"[LSP stderr] {text}")
        except (asyncio.CancelledError, Exception):
            pass

    def _dispatch_incoming(self, message: Dict[str, Any]) -> None:
        """Route message to pending future or notification handler."""
        if "id" in message and ("result" in message or "error" in message):
            # Response to request
            req_id = message["id"]
            future = self._pending_requests.pop(req_id, None)
            if future and not future.done():
                future.set_result(message)
        elif "method" in message:
            # Notification from server
            method = message["method"]
            handlers = self._notification_handlers.get(method, [])
            for handler in handlers:
                try:
                    res = handler(message)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
                except Exception as e:
                    logger.warning(f"Error in LSP notification handler for {method}: {e}")

    def _fail_all_pending(self, reason: str) -> None:
        """Cancel all awaiting requests when the stream terminates."""
        for future in list(self._pending_requests.values()):
            if not future.done():
                future.set_exception(LspConnectionClosedError(reason))
        self._pending_requests.clear()

    async def close(self) -> None:
        """Gracefully terminate transport and server process."""
        self._closed = True
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

        if self._process and self.is_running:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
