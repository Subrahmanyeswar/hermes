# core/browser/dev_server.py
"""
Local Development Server Lifecycle Manager for HERMES 2.x (Prompt 17).
Spawns, monitors, and cleanly terminates test dev servers (python http.server,
Vite, Node, etc.) with automatic port assignment and HTTP readiness polling.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("hermes.browser.dev_server")


@dataclass
class DevServerInfo:
    """Information about an active development server."""
    name: str
    port: int
    url: str
    process: subprocess.Popen
    workspace_dir: Path
    started_at: float = 0.0

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None


class DevServerManager:
    """Manages test servers required for browser evaluation."""

    def __init__(self, default_host: str = "127.0.0.1") -> None:
        self.default_host = default_host
        self._servers: Dict[str, DevServerInfo] = {}

    @classmethod
    def find_free_port(cls) -> int:
        """Find an available TCP port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def start_static_server(
        self,
        directory: Path | str,
        name: str = "static_dev_server",
        port: Optional[int] = None,
        timeout: float = 10.0,
    ) -> DevServerInfo:
        """
        Start Python's built-in http.server to serve a static web directory.
        Polls until the server responds to HTTP GET requests.
        """
        dir_path = Path(directory).resolve()
        if not dir_path.exists():
            raise FileNotFoundError(f"Static directory '{dir_path}' does not exist")

        assigned_port = port or self.find_free_port()
        cmd = [
            sys.executable,
            "-m",
            "http.server",
            str(assigned_port),
            "--bind",
            self.default_host,
            "--directory",
            str(dir_path),
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        server_url = f"http://{self.default_host}:{assigned_port}"
        info = DevServerInfo(
            name=name,
            port=assigned_port,
            url=server_url,
            process=process,
            workspace_dir=dir_path,
            started_at=time.time(),
        )

        # Poll HTTP readiness
        start_t = time.monotonic()
        ready = False
        while time.monotonic() - start_t < timeout:
            if process.poll() is not None:
                raise RuntimeError(f"Server process terminated unexpectedly with code {process.returncode}")
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    r = await client.get(server_url)
                    if r.status_code in (200, 404):  # 404 is still an active web server
                        ready = True
                        break
            except Exception:
                await asyncio.sleep(0.15)

        if not ready:
            process.terminate()
            raise TimeoutError(f"Dev server failed to become ready at {server_url} within {timeout}s")

        self._servers[name] = info
        logger.info(f"Dev server '{name}' ready at {server_url} (PID {process.pid})")
        return info

    def stop_server(self, name: str) -> None:
        """Terminate a specific server by name."""
        info = self._servers.pop(name, None)
        if info and info.process:
            try:
                info.process.kill()
                info.process.wait(timeout=2.0)
            except Exception:
                try:
                    info.process.kill()
                except Exception:
                    pass
            logger.info(f"Dev server '{name}' stopped.")

    def stop_all(self) -> None:
        """Cleanly stop all servers managed by this instance."""
        for name in list(self._servers.keys()):
            self.stop_server(name)

    def get_server(self, name: str) -> Optional[DevServerInfo]:
        return self._servers.get(name)
