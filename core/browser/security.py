# core/browser/security.py
"""
Browser Security & Boundary Manager for HERMES 2.x (Prompt 17).
Enforces URL navigation policies (SSRF defense, localhost scoping),
redacts sensitive credentials from network/console/DOM logs,
and preserves the Prompt 13 untrusted-data boundary.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

BLOCKED_HOSTNAMES: Set[str] = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

BLOCKED_IPS: List[str] = [
    "169.254.169.254",  # AWS/GCP/Azure link-local metadata service
    "fd00::/8",
]

SENSITIVE_HEADER_NAMES: Set[str] = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "proxy-authorization",
    "x-auth-token",
}

SENSITIVE_QUERY_PARAMS: Set[str] = {
    "token",
    "secret",
    "key",
    "api_key",
    "password",
    "auth",
    "access_token",
}


class BrowserSecurityViolation(PermissionError):
    """Raised when a browser action violates security policy."""
    pass


class BrowserSecurityManager:
    """Enforces network, content, and credential boundaries for browser automation."""

    def __init__(self, allow_localhost: bool = True) -> None:
        self.allow_localhost = allow_localhost

    def validate_url(self, url_str: str) -> str:
        """
        Validate that the target URL is safe to navigate to.
        Prevents SSRF, cloud metadata exfiltration, and prohibited schemes.
        """
        if not url_str or not isinstance(url_str, str):
            raise BrowserSecurityViolation("Empty or invalid URL provided")

        clean_url = url_str.strip()
        if clean_url in ("about:blank", "about:srcdoc"):
            return clean_url

        try:
            parsed = urlparse(clean_url)
        except Exception as e:
            raise BrowserSecurityViolation(f"Malformed URL '{clean_url}': {e}") from e

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https", "file", "data"):
            raise BrowserSecurityViolation(
                f"Prohibited URL scheme '{scheme}'. Only http, https, file, data, and about:blank are allowed."
            )

        if scheme in ("file", "data"):
            if scheme == "file":
                # Vite / ESM module CORS defense
                file_path_str = parsed.path
                if file_path_str.startswith("/") and len(file_path_str) > 2 and file_path_str[2] == ":":
                    file_path_str = file_path_str[1:]
                from pathlib import Path
                file_p = Path(file_path_str)
                is_vite_or_esm = False
                parent_dir = file_p.parent if file_p.exists() else Path.cwd()
                if (parent_dir / "vite.config.js").exists() or (parent_dir / "vite.config.ts").exists():
                    is_vite_or_esm = True
                elif (parent_dir / "package.json").exists():
                    try:
                        pkg_content = (parent_dir / "package.json").read_text(encoding="utf-8", errors="ignore").lower()
                        if "vite" in pkg_content:
                            is_vite_or_esm = True
                    except Exception:
                        pass
                if file_p.suffix.lower() in (".html", ".htm") and file_p.exists():
                    try:
                        html_text = file_p.read_text(encoding="utf-8", errors="ignore").lower()
                        if 'type="module"' in html_text or "type='module'" in html_text:
                            is_vite_or_esm = True
                    except Exception:
                        pass
                # Check workspace manager locked root as well
                try:
                    from core.workspace import workspace_manager
                    if workspace_manager.is_locked and workspace_manager.workspace_root:
                        ws_root = Path(workspace_manager.workspace_root)
                        if (ws_root / "vite.config.js").exists() or (ws_root / "vite.config.ts").exists():
                            is_vite_or_esm = True
                except Exception:
                    pass

                if is_vite_or_esm:
                    raise BrowserSecurityViolation(
                        f"Vite/ESM module application cannot be opened via 'file://' ({clean_url}). "
                        "Browser CORS policy blocks ES module scripts loaded from 'file://' (origin 'null'). "
                        "Vite applications must be served over HTTP. "
                        "Use browser_open_preview or start a dev server and navigate via http://127.0.0.1:<port>."
                    )
            return clean_url

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise BrowserSecurityViolation(f"Missing hostname in URL '{clean_url}'")

        # 1. Block known cloud metadata hostnames
        if hostname in BLOCKED_HOSTNAMES:
            raise BrowserSecurityViolation(f"Navigation to cloud metadata service '{hostname}' is strictly blocked (SSRF defense).")

        # 2. Localhost evaluation policy
        is_localhost = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
        if is_localhost:
            if not self.allow_localhost:
                raise BrowserSecurityViolation("Localhost navigation is currently disabled by policy.")
            return clean_url

        # 3. Check IP address ranges for SSRF
        try:
            ip = ipaddress.ip_address(hostname)
            for blocked_ip in BLOCKED_IPS:
                if "/" in blocked_ip:
                    if ip in ipaddress.ip_network(blocked_ip):
                        raise BrowserSecurityViolation(f"SSRF blocked: Navigation to link-local/metadata IP '{ip}' is prohibited.")
                elif str(ip) == blocked_ip:
                    raise BrowserSecurityViolation(f"SSRF blocked: Navigation to link-local/metadata IP '{ip}' is prohibited.")

            # Block private IP ranges unless localhost allowed
            if (ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local) and not is_localhost:
                raise BrowserSecurityViolation(f"SSRF blocked: Navigation to private network IP '{ip}' is prohibited.")
        except ValueError:
            # Hostname is a domain name, not an IP
            pass

        return clean_url

    def redact_url(self, url_str: str) -> str:
        """Scrub secret credentials from query parameters in URLs."""
        if not url_str or "?" not in url_str:
            return url_str

        try:
            parsed = urlparse(url_str)
            params = parse_qsl(parsed.query, keep_blank_values=True)
            redacted_params = []
            for k, v in params:
                if k.lower() in SENSITIVE_QUERY_PARAMS:
                    redacted_params.append((k, "[REDACTED]"))
                else:
                    redacted_params.append((k, v))
            new_query = urlencode(redacted_params)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception:
            return url_str

    def redact_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Scrub authorization tokens and cookies from recorded headers."""
        cleaned = {}
        for k, v in headers.items():
            if k.lower() in SENSITIVE_HEADER_NAMES:
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = v
        return cleaned

    def sanitize_text(self, text: str) -> str:
        """Strip raw API keys and Bearer tokens from console or page text."""
        if not text:
            return ""
        # Redact Bearer tokens
        scrubbed = re.sub(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", r"\1[REDACTED]", text, flags=re.IGNORECASE)
        # Redact common key formats (sk-..., nvapi-..., etc.)
        scrubbed = re.sub(r"\b(nvapi-[A-Za-z0-9\-_]{20,})\b", "[REDACTED_API_KEY]", scrubbed)
        scrubbed = re.sub(r"\b(sk-[A-Za-z0-9\-_]{20,})\b", "[REDACTED_API_KEY]", scrubbed)
        return scrubbed
