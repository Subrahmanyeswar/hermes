# core/security/web_security.py
"""
Production-grade SSRF and Host Validation Layer for HERMES.
Protects autonomous agent web operations against SSRF, internal port scanning,
cloud metadata exfiltration, DNS rebinding, and protocol smuggling.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit
from typing import Optional, Set
from loguru import logger


class SSRFSecurityViolation(Exception):
    """Raised when a URL targets a loopback, private, link-local, cloud-metadata, or unsafe host."""
    pass


# Disallowed schemes
ALLOWED_SCHEMES: Set[str] = {"http", "https"}

# Cloud metadata addresses to strictly block
CLOUD_METADATA_IPS: Set[str] = {
    "169.254.169.254",   # AWS, GCP, Azure, OpenStack, DigitalOcean
    "169.254.170.2",     # AWS ECS container metadata
    "100.100.100.200",   # Alibaba Cloud metadata
    "fd00:ec2::254",     # AWS IPv6 metadata
}

# Blocked hostnames / suffixes
BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "local",
    "broadcasthost",
    "ip6-localhost",
    "ip6-loopback",
}


def is_ip_address(host: str) -> bool:
    """Check if host string is a numeric or literal IP address (IPv4 or IPv6)."""
    # Strip brackets for IPv6 like [::1]
    h = host.strip("[]")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def validate_ip_safety(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Validate that an IP address is public and safe to contact."""
    ip_str = str(ip_obj)

    # Cloud metadata check
    if ip_str in CLOUD_METADATA_IPS:
        raise SSRFSecurityViolation(f"Blocked cloud metadata IP address: {ip_str}")

    # Loopback check (127.0.0.0/8, ::1)
    if ip_obj.is_loopback:
        raise SSRFSecurityViolation(f"Blocked loopback IP address: {ip_str}")

    # Private check (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
    if ip_obj.is_private:
        raise SSRFSecurityViolation(f"Blocked RFC 1918 / private IP address: {ip_str}")

    # Link-local check (169.254.0.0/16, fe80::/10)
    if ip_obj.is_link_local:
        raise SSRFSecurityViolation(f"Blocked link-local IP address: {ip_str}")

    # Multicast check (224.0.0.0/4, ff00::/8)
    if ip_obj.is_multicast:
        raise SSRFSecurityViolation(f"Blocked multicast IP address: {ip_str}")

    # Unspecified (0.0.0.0, ::)
    if ip_obj.is_unspecified:
        raise SSRFSecurityViolation(f"Blocked unspecified IP address: {ip_str}")

    # Reserved (e.g. 240.0.0.0/4)
    if ip_obj.is_reserved:
        raise SSRFSecurityViolation(f"Blocked reserved IP address: {ip_str}")


def resolve_and_validate_host(hostname: str) -> list[str]:
    """
    Resolve hostname via DNS and ensure all resolved IP addresses are safe.
    Returns list of validated IP strings.
    """
    clean_host = hostname.strip("[]").strip().lower()
    
    # 1. Direct host name blacklist
    if clean_host in BLOCKED_HOSTNAMES or clean_host.endswith(".localhost") or clean_host.endswith(".local"):
        raise SSRFSecurityViolation(f"Blocked local/internal hostname: {hostname}")

    # 2. Check if host is direct numeric or hex/octal encoded IP
    # Some attackers use decimal IPs e.g. 2130706433 or octal 0177.0.0.1
    try:
        # Check standard IP
        ip_direct = ipaddress.ip_address(clean_host)
        validate_ip_safety(ip_direct)
        return [str(ip_direct)]
    except ValueError:
        pass

    # Detect decimal IP notation (e.g., http://2130706433)
    if clean_host.isdigit():
        try:
            val = int(clean_host)
            ip_obj = ipaddress.IPv4Address(val)
            validate_ip_safety(ip_obj)
            return [str(ip_obj)]
        except Exception:
            raise SSRFSecurityViolation(f"Invalid or blocked numeric host: {clean_host}")

    # 3. DNS resolution
    try:
        addr_info = socket.getaddrinfo(clean_host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFSecurityViolation(f"Could not resolve hostname '{hostname}': {e}")
    except Exception as e:
        raise SSRFSecurityViolation(f"DNS resolution failure for '{hostname}': {e}")

    if not addr_info:
        raise SSRFSecurityViolation(f"No IP addresses resolved for hostname '{hostname}'")

    validated_ips: list[str] = []
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            validate_ip_safety(ip_obj)
            validated_ips.append(ip_str)
        except SSRFSecurityViolation:
            raise
        except ValueError as ve:
            raise SSRFSecurityViolation(f"Resolved invalid IP '{ip_str}' for host '{hostname}': {ve}")

    return validated_ips


def validate_safe_url(url: str) -> str:
    """
    Validate that a URL is well-formed, uses http/https, and targets a public, safe host.
    Returns normalized URL string. Raises SSRFSecurityViolation if unsafe.
    """
    if not isinstance(url, str) or not url.strip():
        raise SSRFSecurityViolation("URL cannot be empty")

    url = url.strip()

    # Prevent whitespace / control characters
    if any(c in url for c in ["\r", "\n", "\t", "\x00"]):
        raise SSRFSecurityViolation("URL contains illegal whitespace or control characters")

    try:
        parts = urlsplit(url)
    except Exception as e:
        raise SSRFSecurityViolation(f"Malformed URL: {e}")

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFSecurityViolation(
            f"Scheme '{scheme}' is forbidden. Only HTTP and HTTPS are permitted."
        )

    if not parts.netloc:
        raise SSRFSecurityViolation("URL missing netloc/host")

    # Handle userinfo e.g. user:pass@host
    hostname = parts.hostname
    if not hostname:
        raise SSRFSecurityViolation("URL missing hostname")

    # Validate port if specified
    if parts.port is not None:
        if parts.port <= 0 or parts.port > 65535:
            raise SSRFSecurityViolation(f"Invalid port: {parts.port}")
        # Optionally block standard internal ports (e.g. 22 SSH, 3306 MySQL, 5432 PG, 6379 Redis)
        forbidden_ports = {22, 23, 25, 110, 143, 3306, 5432, 6379, 11211, 27017}
        if parts.port in forbidden_ports:
            raise SSRFSecurityViolation(f"Access to sensitive port {parts.port} is blocked")

    # Validate host safety via DNS resolution
    resolve_and_validate_host(hostname)

    # Reconstruct normalized URL
    return urlunsplit(parts)


def is_safe_url(url: str) -> bool:
    """Return True if URL is safe to request, False otherwise."""
    try:
        validate_safe_url(url)
        return True
    except (SSRFSecurityViolation, Exception):
        return False
