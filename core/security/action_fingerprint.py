# core/security/action_fingerprint.py
"""
Deterministic Action Fingerprinting for HERMES 2.x Security.
Ensures stable, reproducible action identification for replay prevention,
approval binding, and cache invalidation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.security.models import ActionDescriptor


def normalize_path(path_str: str, workspace_root: Optional[str] = None) -> str:
    """
    Canonicalize path string for security comparison.
    Resolves relative navigations (..), converts separators, and normalizes casing.
    """
    if not path_str:
        return ""
    try:
        p = Path(path_str)
        # If relative and workspace provided, anchor it
        if not p.is_absolute() and workspace_root:
            p = (Path(workspace_root) / p).resolve()
        else:
            p = p.resolve()
        # Normalise separators to forward slashes and lowercase on Windows for canonical identity
        clean = str(p).replace("\\", "/")
        if os.name == "nt":
            clean = clean.lower()
        return clean
    except Exception:
        clean = path_str.strip().replace("\\", "/")
        if os.name == "nt":
            clean = clean.lower()
        return clean


def normalize_arguments(args: Dict[str, Any]) -> str:
    """Produce stable, key-sorted JSON serialization of arguments."""
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"))
    except Exception:
        # Fallback to string representation sorted by keys
        try:
            sorted_items = sorted((str(k), str(v)) for k, v in args.items())
            return json.dumps(sorted_items, separators=(",", ":"))
        except Exception:
            return str(args)


def compute_action_fingerprint(
    action: Optional[ActionDescriptor | str] = None,
    policy_version: str = "1.0.0",
    workspace_root: Optional[str] = None,
    tool_name: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    canonical_path: Optional[str] = None,
    command_str: Optional[str] = None,
    target_url: Optional[str] = None,
) -> str:
    """
    Compute a cryptographically secure, deterministic fingerprint of an action.
    Binds tool name, operation, canonical targets, arguments, and policy version.
    Supports both ActionDescriptor objects and direct kwargs.
    """
    if isinstance(action, ActionDescriptor):
        t_name = (action.tool_name or "").strip().lower()
        operation = (action.operation or "").strip().lower()
        targets = action.target_paths or ([action.canonical_path] if action.canonical_path else [])
        net = action.network_destinations or ([action.target_url] if action.target_url else [])
        args = action.arguments or {}
        cwd = action.cwd or ""
    else:
        t_name = ((action if isinstance(action, str) else tool_name) or "").strip().lower()
        operation = ""
        targets = [canonical_path] if canonical_path else []
        net = [target_url] if target_url else []
        args = arguments or {}
        cwd = ""

    # Canonicalize targets
    norm_targets = [
        normalize_path(p, workspace_root=workspace_root or cwd)
        for p in targets if p
    ]
    norm_targets.sort()

    # Canonicalize network targets
    norm_network = [d.strip().lower() for d in net if d]
    norm_network.sort()

    # Normalized arguments
    norm_args = normalize_arguments(args)

    # Core tuple to hash
    payload = {
        "tool": t_name,
        "op": operation,
        "targets": norm_targets,
        "network": norm_network,
        "args": norm_args,
        "cwd": normalize_path(cwd) if cwd else "",
        "policy": policy_version,
    }

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return sha
