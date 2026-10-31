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
    workspace_dir: Path
    process: Optional[subprocess.Popen] = None
    started_at: float = 0.0

    @property
    def is_alive(self) -> bool:
        if self.process is None:
            return True
        return self.process.poll() is None


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

    def get_server_for_workspace(self, directory: Path | str) -> Optional[DevServerInfo]:
        """Return active dev server strictly matching the requested workspace directory."""
        dir_path = Path(directory).resolve()
        for s in self._servers.values():
            if s.is_alive and s.workspace_dir == dir_path:
                return s
        return None

    def stop_stale_servers_not_matching(self, current_workspace: Path | str) -> int:
        """Terminate any dev server serving a workspace other than current_workspace."""
        curr_path = Path(current_workspace).resolve()
        stopped = 0
        for name, s in list(self._servers.items()):
            if s.workspace_dir != curr_path:
                logger.info(f"DevServerManager: stopping non-matching server '{name}' serving {s.workspace_dir}")
                self.stop_server(name)
                stopped += 1
        return stopped

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

        # Fast reuse: if server with this name is already active for this directory, reuse immediately
        existing = self._servers.get(name)
        if existing and existing.is_alive:
            if existing.workspace_dir == dir_path:
                logger.info(f"Dev server '{name}' reused at {existing.url} (PID {existing.process.pid if existing.process else 'ext'})")
                return existing
            else:
                logger.info(f"Stopping stale dev server '{name}' for directory change to {dir_path}")
                self.stop_server(name)

        # Check if specified port is already serving
        if port is not None:
            try:
                async with httpx.AsyncClient(timeout=0.8) as client:
                    r = await client.get(f"http://{self.default_host}:{port}")
                    if r.status_code in (200, 404):
                        logger.info(f"DevServerManager: attaching to existing server on port {port} for {dir_path}")
                        info = DevServerInfo(
                            name=name,
                            port=port,
                            url=f"http://{self.default_host}:{port}",
                            process=None,
                            workspace_dir=dir_path,
                            started_at=time.time(),
                        )
                        self._servers[name] = info
                        return info
            except Exception:
                pass

        assigned_port = port or self.find_free_port()
        from core.runtime_identity import get_canonical_python_executable, get_canonical_subprocess_env
        cmd = [
            get_canonical_python_executable(),
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
            env=get_canonical_subprocess_env(),
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
