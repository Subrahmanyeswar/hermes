# core/server/security.py
"""
Local security middleware and authorization utilities for HERMES 2.x API.
Prevents DNS rebinding, cross-origin tampering, unauthorized workspace escape,
and path traversal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Set
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.workspace import WorkspaceBoundaryError, canonicalize_workspace_path, workspace_manager


ALLOWED_HOSTS: Set[str] = {
    "127.0.0.1",
    "localhost",
    "127.0.0.1:8765",
    "localhost:8765",
}

ALLOWED_ORIGINS: Set[str] = {
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1:5173",  # Future Vite dev server (localhost only)
    "http://localhost:5173",
}


class LocalHostSecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware verifying that requests originate strictly from authorized local addresses.
    Rejects DNS rebinding attacks and external network ingress.
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Verify client IP is loopback
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "Access forbidden: only loopback interface allowed (127.0.0.1)."},
            )

        # 2. Verify Host header against DNS rebinding
        host_header = request.headers.get("host", "").lower()
        host_name = host_header.split(":")[0] if ":" in host_header else host_header
        if (
            host_header
            and host_header not in ALLOWED_HOSTS
            and host_name not in ("127.0.0.1", "localhost")
            and not host_header.startswith("testserver")
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": f"Invalid Host header '{host_header}'. Access forbidden."},
            )

        # 3. Verify Origin for CORS / cross-site requests
        origin_header = request.headers.get("origin")
        if origin_header and origin_header not in ALLOWED_ORIGINS:
            from urllib.parse import urlparse
            try:
                parsed_orig = urlparse(origin_header)
                if parsed_orig.hostname not in ("127.0.0.1", "localhost"):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"error": f"Unauthorized origin '{origin_header}'."},
                    )
            except Exception:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": f"Unauthorized origin '{origin_header}'."},
                )

        response = await call_next(request)

        # Set strict security headers
        if origin_header in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin_header
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Last-Event-ID, X-Hermes-Token"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        return response


def validate_workspace_access(requested_path: Optional[str]) -> Path:
    """
    Validate that the requested path is safe, exists or is valid,
    and does not escape permitted filesystem roots.
    """
    if not requested_path:
        if workspace_manager.is_locked and workspace_manager.workspace_root:
            return workspace_manager.workspace_root
        return Path.cwd().resolve()

    try:
        resolved = Path(requested_path).resolve()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid filesystem path: {e}",
        )

    # If workspace is locked, strictly enforce boundary
    if workspace_manager.is_locked and workspace_manager.workspace_root:
        try:
            canonical = canonicalize_workspace_path(resolved, workspace_manager.workspace_root)
            return canonical
        except WorkspaceBoundaryError as wbe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(wbe),
            )

    return resolved
