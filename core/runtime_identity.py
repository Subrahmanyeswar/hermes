# core/runtime_identity.py
"""
HERMES Canonical Runtime & Environment Identity (Python 3.12.x).

Ensures deterministic runtime discovery, validation, and enforcement:
- Canonical Python 3.12 requirement (rejects Python 3.10 and 3.13)
- Canonical repository-local virtual environment resolution and isolation
- Subprocess Python environment derivation (ensures child processes never leak system Python)
- Deterministic dependency lock inspection and verification
- Authoritative runtime identity shared by CLI, TUI, and headless execution
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

CANONICAL_PYTHON_MAJOR = 3
CANONICAL_PYTHON_MINOR = 12


class IncompatiblePythonVersionError(RuntimeError):
    """Raised when HERMES is executed on an unsupported Python version."""
    pass


class NonCanonicalEnvironmentError(RuntimeError):
    """Raised when HERMES is executed outside its canonical virtual environment."""
    pass


class DependencyDriftError(RuntimeError):
    """Raised when installed packages diverge from the authoritative requirements.lock."""
    pass


@dataclass
class RuntimeIdentity:
    """Authoritative representation of the running HERMES execution environment."""
    source_root: str
    version: str
    commit: str
    python_executable: str
    python_version: str
    environment_type: str  # "virtualenv" or "system"
    is_venv: bool
    is_canonical_python: bool
    is_canonical_venv: bool
    venv_path: Optional[str]
    workspace_root: str
    dependency_lock_hash: str
    t1_provider: str
    t1_model: str
    t2_provider: str
    t2_model: str
    t3_provider: str
    t3_model: str
    key_packages: Dict[str, str] = field(default_factory=dict)
    sys_path: List[str] = field(default_factory=list)
    env_vars: Dict[str, str] = field(default_factory=dict)

    def format_diagnostic(self) -> str:
        """Format an authoritative diagnostic banner."""
        py_status = "VALID (Python 3.12)" if self.is_canonical_python else f"INCOMPATIBLE ({self.python_version.split()[0]})"
        venv_status = "CANONICAL REPO VENV" if self.is_canonical_venv else f"NON-CANONICAL ({self.environment_type})"
        lines = [
            "============================================================",
            "                 HERMES RUNTIME IDENTITY",
            "============================================================",
            f"  Source Root      : {self.source_root}",
            f"  Version/Commit   : {self.version} ({self.commit[:10] if self.commit else 'unknown'})",
            f"  Python Exe       : {self.python_executable}",
            f"  Python Version   : {self.python_version.split()[0]} [{py_status}]",
            f"  Environment      : {self.environment_type} (venv={self.is_venv}) [{venv_status}]",
            f"  Venv Path        : {self.venv_path or 'None'}",
            f"  Dependency Lock  : SHA256:{self.dependency_lock_hash[:12]}",
            f"  Workspace Root   : {self.workspace_root}",
            "------------------------------------------------------------",
            "  Active Model Stack:",
            f"    • Tier 1 (Fast Execution) : {self.t1_provider} / {self.t1_model}",
            f"    • Tier 2 (Verification)   : {self.t2_provider} / {self.t2_model}",
            f"    • Tier 3 (Arbitration)    : {self.t3_provider} / {self.t3_model}",
            "------------------------------------------------------------",
            "  Key Dependency Versions:",
        ]
        for pkg, ver in sorted(self.key_packages.items()):
            lines.append(f"    • {pkg:<16}: {ver}")
        lines.append("============================================================")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_hermes_source_root() -> Path:
    """Return the absolute root path of the HERMES codebase."""
    return Path(__file__).resolve().parent.parent


def get_canonical_python_executable() -> str:
    """
    Returns the absolute path to the canonical Python 3.12 interpreter in the repository venv.
    If the active process is already running within the repository venv, returns sys.executable.
    """
    src_root = get_hermes_source_root()
    if sys.platform == "win32":
        venv_py = src_root / "venv" / "Scripts" / "python.exe"
    else:
        venv_py = src_root / "venv" / "bin" / "python"

    if venv_py.is_file():
        return str(venv_py.resolve())

    return sys.executable


def get_canonical_subprocess_env(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Construct an authoritative subprocess environment ensuring that:
    1. The canonical venv Scripts directory is at the front of PATH.
    2. VIRTUAL_ENV is pointed to the canonical venv.
    3. PYTHONHOME is removed so it cannot leak system Python libraries.
    4. PYTHONNOUSERSITE is set to 1 to prevent picking up user site-packages.
    """
    env = os.environ.copy()
    src_root = get_hermes_source_root()
    venv_dir = src_root / "venv"
    if sys.platform == "win32":
        scripts_dir = venv_dir / "Scripts"
    else:
        scripts_dir = venv_dir / "bin"

    path_entries = [str(scripts_dir)]
    if "PATH" in env:
        path_entries.append(env["PATH"])
    env["PATH"] = os.pathsep.join(path_entries)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)
    return env


def compute_dependency_lock_hash() -> str:
    """Calculate deterministic SHA256 of requirements.lock."""
    src_root = get_hermes_source_root()
    lock_file = src_root / "requirements.lock"
    if not lock_file.exists():
        lock_file = src_root / "requirements-lock.txt"
    if lock_file.exists():
        try:
            return hashlib.sha256(lock_file.read_bytes()).hexdigest()
        except Exception:
            pass
    return "unlocked_unknown"


def get_git_commit(root: Path) -> str:
    """Resolve current git commit hash if available."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_package_versions() -> Dict[str, str]:
    """Inspect versions of critical HERMES dependencies using importlib.metadata."""
    packages = ["pydantic", "textual", "typer", "httpx", "loguru", "pytest", "aiofiles", "rich"]
    versions: Dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "not installed"
        except Exception:
            versions[pkg] = "unknown"
    return versions


def detect_runtime_identity(workspace_root: Optional[str] = None) -> RuntimeIdentity:
    """
    Inspect the active runtime and return the authoritative RuntimeIdentity.
    """
    src_root = get_hermes_source_root()
    commit = get_git_commit(src_root)

    # Version
    version_str = "1.0.0-rc1"
    try:
        from main import __version__
        version_str = __version__
    except Exception:
        pass

    # Python version compatibility check
    is_canonical_py = (sys.version_info[0] == CANONICAL_PYTHON_MAJOR and sys.version_info[1] == CANONICAL_PYTHON_MINOR)

    # Venv detection and canonical repo venv check
    is_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    env_type = "virtualenv" if is_venv else "system"
    venv_path = sys.prefix if is_venv else os.environ.get("VIRTUAL_ENV")

    expected_venv = (src_root / "venv").resolve()
    is_canonical_venv = is_venv and (Path(sys.prefix).resolve() == expected_venv)

    # Dependency lock hash
    lock_hash = compute_dependency_lock_hash()

    # Authoritative workspace root
    from core.workspace import workspace_manager
    ws_root = (
        workspace_root
        or (workspace_manager.root_str if workspace_manager.is_locked else str(Path.cwd()))
    )

    # Active model configuration
    try:
        from config.model_config import (
            TIER1_PROVIDER, TIER1_MODEL,
            TIER2_PROVIDER, TIER2_MODEL,
            TIER3_PROVIDER, TIER3_MODEL,
        )
    except Exception:
        TIER1_PROVIDER, TIER1_MODEL = "unknown", "unknown"
        TIER2_PROVIDER, TIER2_MODEL = "unknown", "unknown"
        TIER3_PROVIDER, TIER3_MODEL = "unknown", "unknown"

    key_pkgs = get_package_versions()

    env_vars = {
        k: os.environ[k]
        for k in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
        if k in os.environ
    }

    return RuntimeIdentity(
        source_root=str(src_root),
        version=version_str,
        commit=commit,
        python_executable=sys.executable,
        python_version=sys.version,
        environment_type=env_type,
        is_venv=is_venv,
        is_canonical_python=is_canonical_py,
        is_canonical_venv=is_canonical_venv,
        venv_path=venv_path,
        workspace_root=ws_root,
        dependency_lock_hash=lock_hash,
        t1_provider=TIER1_PROVIDER,
        t1_model=TIER1_MODEL,
        t2_provider=TIER2_PROVIDER,
        t2_model=TIER2_MODEL,
        t3_provider=TIER3_PROVIDER,
        t3_model=TIER3_MODEL,
        key_packages=key_pkgs,
        sys_path=list(sys.path),
        env_vars=env_vars,
    )


def validate_runtime_environment(
    strict: bool = True,
    workspace_root: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate that the active environment satisfies the HERMES canonical runtime contract:
    1. Python version is strictly 3.12.x
    2. Active interpreter is the repository-local virtual environment
    3. Source tree is the authoritative repository root
    4. Required locked packages are present and match locked versions
    """
    errors: List[str] = []
    warnings: List[str] = []
    src_root = get_hermes_source_root()

    # 1. Python version check
    if sys.version_info[0] != CANONICAL_PYTHON_MAJOR or sys.version_info[1] != CANONICAL_PYTHON_MINOR:
        v_str = f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}"
        errors.append(
            f"Incompatible Python version: Python {v_str}. "
            f"HERMES strictly requires Python 3.12.x. Normal execution on Python 3.10, 3.13, etc. is rejected."
        )

    # 2. Canonical virtual environment check
    is_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    expected_venv = (src_root / "venv").resolve()
    if not is_venv:
        errors.append(
            f"Running under system Python ({sys.executable}). "
            f"HERMES requires execution within the canonical virtual environment at {expected_venv}."
        )
    elif Path(sys.prefix).resolve() != expected_venv:
        errors.append(
            f"Running under non-canonical virtual environment: {sys.prefix}. "
            f"Expected canonical repository venv at {expected_venv}."
        )

    # 3. Source root validation
    if not (src_root / "main.py").is_file():
        errors.append(f"Invalid HERMES source root: {src_root}. main.py not found.")

    # 4. Dependency lock verification
    lock_file = src_root / "requirements.lock"
    locked_deps: Dict[str, str] = {}
    if lock_file.exists():
        for line in lock_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "==" in line:
                pkg_name, pkg_ver = line.split("==", 1)
                locked_deps[pkg_name.lower().replace("-", "_")] = pkg_ver.strip()

    missing_pkgs: List[str] = []
    drifted_pkgs: List[str] = []

    for pkg_name, locked_ver in locked_deps.items():
        try:
            installed_ver = importlib.metadata.version(pkg_name)
            if installed_ver != locked_ver:
                drifted_pkgs.append(f"{pkg_name} (installed {installed_ver} != locked {locked_ver})")
        except importlib.metadata.PackageNotFoundError:
            # Check with hyphen as well
            try:
                alt_name = pkg_name.replace("_", "-")
                installed_ver = importlib.metadata.version(alt_name)
                if installed_ver != locked_ver:
                    drifted_pkgs.append(f"{pkg_name} (installed {installed_ver} != locked {locked_ver})")
            except importlib.metadata.PackageNotFoundError:
                missing_pkgs.append(pkg_name)

    if missing_pkgs:
        errors.append(f"Missing required locked packages: {', '.join(missing_pkgs[:10])}")
    if drifted_pkgs:
        errors.append(f"Dependency version drift detected against requirements.lock: {', '.join(drifted_pkgs[:10])}")

    is_valid = len(errors) == 0

    if strict and not is_valid:
        if any("Incompatible Python" in e for e in errors):
            raise IncompatiblePythonVersionError("\n".join(errors))
        if any("system Python" in e or "non-canonical" in e for e in errors):
            raise NonCanonicalEnvironmentError("\n".join(errors))
        if missing_pkgs or drifted_pkgs:
            raise DependencyDriftError("\n".join(errors))
        raise RuntimeError("\n".join(errors))

    return {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "executable": sys.executable,
        "venv_path": sys.prefix,
        "lock_hash": compute_dependency_lock_hash(),
        "locked_package_count": len(locked_deps),
    }


def ensure_canonical_runtime(workspace_root: Optional[str] = None) -> None:
    """
    Fail-fast startup gate for all HERMES CLI, TUI, and mission operations.
    Exits with error code 1 immediately if runtime invariants are violated.
    """
    # 1. Fast Python version check
    if sys.version_info[0] != CANONICAL_PYTHON_MAJOR or sys.version_info[1] != CANONICAL_PYTHON_MINOR:
        v_str = f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}"
        sys.stderr.write(
            f"\n[HERMES FATAL ERROR] Incompatible Python interpreter: Python {v_str}\n"
            f"HERMES strictly requires Python 3.12.x. Python 3.10, 3.13, etc. are rejected.\n"
            f"Launch via canonical launcher:\n"
            f"  .\\hermes.bat <args>\n"
            f"Or directly with canonical interpreter:\n"
            f"  .\\venv\\Scripts\\python.exe main.py <args>\n\n"
        )
        sys.exit(1)

    # 2. Comprehensive validation
    res = validate_runtime_environment(strict=False, workspace_root=workspace_root)
    if not res["valid"]:
        err_lines = "\n".join(f"  • {e}" for e in res["errors"])
        sys.stderr.write(
            f"\n[HERMES RUNTIME VALIDATION FAILED]\n{err_lines}\n\n"
            f"Execution halted to protect environment determinism.\n"
            f"Please run via the canonical launcher or run: .\\hermes.bat env-check\n\n"
        )
        sys.exit(1)
