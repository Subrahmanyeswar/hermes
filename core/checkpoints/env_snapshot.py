# core/checkpoints/env_snapshot.py
"""
Execution environment snapshotting and fingerprinting for HERMES 2.x.

Core Invariants:
1. STRICT ALLOWLIST: Only explicitly approved, non-sensitive environment variables are captured.
2. ZERO SECRETS: Never snapshot API keys, tokens, passwords, or arbitrary os.environ.
3. ENVIRONMENT FINGERPRINT: Deterministic hash identifies environment drift upon resume.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from pathlib import Path
from typing import Dict, Set

from core.persistence.models import EnvironmentManifest


ALLOWLISTED_ENV_VARS: Set[str] = {
    "PYTHON_VERSION",
    "HERMES_MODE",
    "TIER1_PROVIDER",
    "MODEL_NAME",
    "HERMES_ENV",
    "PYTHONOPTIMIZE",
}


class EnvironmentSnapshotter:
    """
    Captures allowlisted environment configuration for drift detection.
    """

    @classmethod
    def create_snapshot(cls, cwd: Path | str) -> EnvironmentManifest:
        allowlisted_env: Dict[str, str] = {}
        for var_name in sorted(ALLOWLISTED_ENV_VARS):
            if var_name in os.environ:
                val = os.environ[var_name]
                # Defensive check against accidentally allowlisting a secret
                if not any(token in val.lower() for token in ("sk-", "ghp_", "bearer")):
                    allowlisted_env[var_name] = val

        os_name = platform.system()
        os_version = platform.release()
        arch = platform.machine()
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        resolved_cwd = str(Path(cwd).resolve())

        # Generate deterministic fingerprint
        hasher = hashlib.sha256()
        hasher.update(f"{os_name}:{os_version}:{arch}:{py_ver}:{resolved_cwd}".encode("utf-8"))
        for k, v in sorted(allowlisted_env.items()):
            hasher.update(f"{k}={v}".encode("utf-8"))
        fingerprint = hasher.hexdigest()

        return EnvironmentManifest(
            os_name=os_name,
            os_version=os_version,
            architecture=arch,
            python_version=py_ver,
            cwd=resolved_cwd,
            allowlisted_env=allowlisted_env,
            fingerprint=fingerprint,
        )
