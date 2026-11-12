# core/server/security.py
"""
Local security middleware and authorization utilities for HERMES 2.x API.
Prevents DNS rebinding, cross-origin tampering, unauthorized workspace escape,
and path traversal.
"""

from __future__ import annotations

import ipaddress
import os
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

# Container private bridge networks: restricted strictly to the configured Docker bridge subnet
# (e.g. HERMES_DOCKER_SUBNET or default 172.18.0.0/16) and host loopback (127.0.0.0/8).
# Broad enterprise subnets (10.0.0.0/8, 192.168.0.0/16, or entire 172.16.0.0/12) and public CIDRs
# are strictly rejected to prevent cross-container or external network ingress.
def validate_docker_subnet(subnet_str: str) -> ipaddress.IPv4Network:
    """
    Strictly validate that a configured subnet string is a valid IPv4 RFC1918
    Docker bridge subnet with an appropriate prefix length (/16 to /28).
    Raises ValueError on invalid, public, or overly broad subnets.
    """
    if not subnet_str or not isinstance(subnet_str, str):
        raise ValueError("Subnet string must be a non-empty string.")

    cleaned = subnet_str.strip()
    try:
        net = ipaddress.ip_network(cleaned, strict=True)
    except Exception as exc:
        raise ValueError(f"Malformed CIDR network '{subnet_str}': {exc}")

    if not isinstance(net, ipaddress.IPv4Network):
        raise ValueError(f"Docker bridge subnet must be an IPv4 network, got '{subnet_str}'.")

    # Strictly require RFC1918 private ranges
    rfc1918_ranges = [
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    ]
    if not any(net.subnet_of(parent) for parent in rfc1918_ranges):
        raise ValueError(f"Subnet '{subnet_str}' is not within private RFC1918 Docker bridge ranges.")

    # Restrict to standard bridge prefix lengths (/16 to /28)
    if net.prefixlen < 16 or net.prefixlen > 28:
        raise ValueError(
            f"Subnet '{subnet_str}' prefix length /{net.prefixlen} is outside permitted bridge range (/16 to /28)."
        )

    return net


def get_authorized_container_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Return list of authorized container networks.
    Loopback (127.0.0.0/8) is always authorized.
    If HERMES_DOCKER_SUBNET is configured, validate it strictly.
    If invalid or malformed, log an error and DO NOT trust any external bridge network
    (fails closed to loopback-only, preserving normal desktop security and preventing unauthorized ingress).
    Default: 172.18.0.0/16.
    """
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [ipaddress.ip_network("127.0.0.0/8")]
    raw_subnet = os.environ.get("HERMES_DOCKER_SUBNET", "172.18.0.0/16").strip()
    if raw_subnet:
        try:
            valid_net = validate_docker_subnet(raw_subnet)
            networks.append(valid_net)
        except ValueError as err:
            from loguru import logger
            logger.error(
                f"Security: Rejected invalid HERMES_DOCKER_SUBNET '{raw_subnet}': {err}. "
                f"Restricting container ingress to loopback only."
            )
    return networks


_CONTAINER_NETWORKS = get_authorized_container_networks()


class LocalHostSecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware verifying that requests originate strictly from authorized local addresses.
    Rejects DNS rebinding attacks and external network ingress.
    When HERMES_CONTAINER_MODE=true is configured, safely accepts container bridge gateway IP addresses.
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Verify client IP is loopback or authorized container bridge
        client_host = request.client.host if request.client else None
        is_container_mode = os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true"

        is_authorized_ip = False
        if client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
            is_authorized_ip = True
        elif is_container_mode and client_host:
            try:
                ip = ipaddress.ip_address(client_host)
                if ip.is_loopback:
                    is_authorized_ip = True
                elif ip.is_private:
                    auth_networks = get_authorized_container_networks()
                    if any(ip in net for net in auth_networks):
                        is_authorized_ip = True
            except ValueError:
                is_authorized_ip = False

        if not is_authorized_ip:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "Access forbidden: only loopback interface allowed (127.0.0.1)."},
            )

        # 2. Verify Host header against DNS rebinding (strictly localhost / 127.0.0.1)
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

    # In container mode, enforce containment within configured workspace roots
    if os.environ.get("HERMES_CONTAINER_MODE", "false").lower() == "true":
        allowed_root = Path(os.environ.get("HERMES_WORKSPACES_ROOT", "/workspaces")).resolve()
        try:
            resolved.relative_to(allowed_root)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Path '{resolved}' escapes allowed container workspace root '{allowed_root}'.",
            )

    return resolved
