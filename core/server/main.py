# core/server/main.py
"""
CLI and Entrypoint launcher for HERMES 2.x Local FastAPI Server.
Binds strictly to 127.0.0.1:8765 by default.
"""

from __future__ import annotations

import argparse
import sys
import uvicorn
from loguru import logger

from core.server.app import app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, log_level: str = "info") -> None:
    """Run the Uvicorn ASGI server binding exclusively to loopback."""
    if host not in ("127.0.0.1", "localhost"):
        logger.error(f"Security violation: Refusing to bind server to non-loopback host '{host}'.")
        sys.exit(1)

    logger.info(f"Starting HERMES Local Server on http://{host}:{port} ...")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HERMES Local Runtime API Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host address (must be 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: 8765)")
    parser.add_argument("--log-level", default="info", help="Uvicorn log level")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, log_level=args.log_level)
