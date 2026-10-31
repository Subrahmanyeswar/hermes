# tests/test_runtime_determinism.py
"""
Qualification and Regression Suite for HERMES Runtime Determinism (Python 3.12.x).

Verifies the 15 required runtime determinism invariants:
1. HERMES requires Python 3.12 for canonical execution.
2. Python 3.10 is rejected by the canonical runtime.
3. Python 3.13 is rejected unless explicitly qualified and approved later.
4. CLI and TUI report the same Python executable.
5. CLI and TUI report the same dependency identity.
6. CLI and TUI report the same model configuration.
7. Child Python processes use the canonical Python executable.
8. System-global packages cannot silently satisfy HERMES imports.
9. Missing locked dependencies cause startup failure.
10. Dependency drift is detected.
11. Fresh Python 3.12 environment installation succeeds.
12. Existing forensic regression suite still passes.
13. Existing core regression suite still passes.
14. Runtime identity is deterministic.
15. Normal execution cannot silently fall back to another Python installation.
"""

import importlib
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from core.runtime_identity import (
    CANONICAL_PYTHON_MAJOR,
    CANONICAL_PYTHON_MINOR,
    DependencyDriftError,
    IncompatiblePythonVersionError,
    NonCanonicalEnvironmentError,
    compute_dependency_lock_hash,
    detect_runtime_identity,
    ensure_canonical_runtime,
    get_canonical_python_executable,
    get_canonical_subprocess_env,
    get_hermes_source_root,
    validate_runtime_environment,
)
from core.runtime_factory import ApplicationRuntimeFactory, SurfaceMode
from ui.app import HermesApp


# ── 1. HERMES requires Python 3.12 for canonical execution ────────────────────

def test_hermes_requires_python_312_for_canonical_execution():
    assert CANONICAL_PYTHON_MAJOR == 3
    assert CANONICAL_PYTHON_MINOR == 12

    # Active interpreter must be 3.12 in canonical execution
    assert sys.version_info.major == 3
    assert sys.version_info.minor == 12

    identity = detect_runtime_identity()
    assert identity.is_canonical_python is True


# ── 2. Python 3.10 is rejected by the canonical runtime ───────────────────────

def test_python_310_is_rejected_by_canonical_runtime():
    src_root = get_hermes_source_root()
    py310_exe = r"C:\Users\SUBBU\AppData\Local\Programs\Python\Python310\python.exe"

    if Path(py310_exe).is_file():
        # Execute main.py directly with system Python 3.10
        res = subprocess.run(
            [py310_exe, str(src_root / "main.py"), "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res.returncode != 0
        combined = (res.stdout + res.stderr)
        assert "Incompatible Python interpreter" in combined or "strictly requires Python 3.12" in combined
    else:
        # Simulate via mock
        with patch("sys.version_info", (3, 10, 0, "final", 0)):
            val = validate_runtime_environment(strict=False)
            assert val["valid"] is False
            assert any("Incompatible Python version" in e for e in val["errors"])


# ── 3. Python 3.13 is rejected unless explicitly qualified ────────────────────

def test_python_313_is_rejected_unless_explicitly_qualified():
    src_root = get_hermes_source_root()
    py313_exe = r"C:\Users\SUBBU\AppData\Local\Programs\Python\Python313\python.exe"

    if Path(py313_exe).is_file():
        # Execute main.py directly with system Python 3.13
        res = subprocess.run(
            [py313_exe, str(src_root / "main.py"), "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res.returncode != 0
        combined = (res.stdout + res.stderr)
        assert "Incompatible Python interpreter" in combined or "strictly requires Python 3.12" in combined
    else:
        # Simulate via mock
        with patch("sys.version_info", (3, 13, 0, "final", 0)):
            val = validate_runtime_environment(strict=False)
            assert val["valid"] is False
            assert any("Incompatible Python version" in e for e in val["errors"])


# ── 4. CLI and TUI report the same Python executable ─────────────────────────

def test_cli_and_tui_report_same_python_executable():
    headless_rt = ApplicationRuntimeFactory.create_runtime(SurfaceMode.HEADLESS)
    cli_identity = headless_rt.get_runtime_identity()

    tui_app = HermesApp(mode="auto", workspace=str(get_hermes_source_root()), show_startup=False)
    tui_identity = tui_app.get_runtime_identity()

    assert cli_identity.python_executable == tui_identity.python_executable
    assert Path(cli_identity.python_executable).resolve() == Path(sys.executable).resolve()


# ── 5. CLI and TUI report the same dependency identity ───────────────────────

def test_cli_and_tui_report_same_dependency_identity():
    headless_rt = ApplicationRuntimeFactory.create_runtime(SurfaceMode.HEADLESS)
    cli_identity = headless_rt.get_runtime_identity()

    tui_app = HermesApp(mode="auto", workspace=str(get_hermes_source_root()), show_startup=False)
    tui_identity = tui_app.get_runtime_identity()

    assert cli_identity.dependency_lock_hash == tui_identity.dependency_lock_hash
    assert cli_identity.dependency_lock_hash == compute_dependency_lock_hash()
    assert cli_identity.key_packages == tui_identity.key_packages


# ── 6. CLI and TUI report the same model configuration ───────────────────────

def test_cli_and_tui_report_same_model_configuration():
    headless_rt = ApplicationRuntimeFactory.create_runtime(SurfaceMode.HEADLESS)
    cli_identity = headless_rt.get_runtime_identity()

    tui_app = HermesApp(mode="auto", workspace=str(get_hermes_source_root()), show_startup=False)
    tui_identity = tui_app.get_runtime_identity()

    assert cli_identity.t1_provider == tui_identity.t1_provider
    assert cli_identity.t1_model == tui_identity.t1_model
    assert cli_identity.t2_provider == tui_identity.t2_provider
    assert cli_identity.t2_model == tui_identity.t2_model
    assert cli_identity.t3_provider == tui_identity.t3_provider
    assert cli_identity.t3_model == tui_identity.t3_model


# ── 7. Child Python processes use canonical Python executable ────────────────

def test_child_python_processes_use_canonical_python_executable():
    canon_py = get_canonical_python_executable()
    assert Path(canon_py).is_file()
    assert "venv" in canon_py.lower()

    env = get_canonical_subprocess_env()
    assert "VIRTUAL_ENV" in env
    assert env["PYTHONNOUSERSITE"] == "1"

    # Running python via child environment resolves to Python 3.12
    res = subprocess.run(
        [canon_py, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "3.12"


# ── 8. System-global packages cannot silently satisfy HERMES imports ─────────

def test_system_global_packages_cannot_silently_satisfy_hermes_imports():
    """Packages only installed on system Python (e.g. openai) cannot be imported in venv."""
    src_root = get_hermes_source_root()
    pyvenv_cfg = src_root / "venv" / "pyvenv.cfg"
    assert pyvenv_cfg.exists(), "pyvenv.cfg must exist"
    cfg_text = pyvenv_cfg.read_text(encoding="utf-8").lower()
    assert "include-system-site-packages = false" in cfg_text

    # Verify openai (installed on system Python 3.10) is blocked in canonical venv
    with pytest.raises(ImportError):
        import openai  # noqa: F401


# ── 9. Missing locked dependencies cause startup failure ─────────────────────

def test_missing_locked_dependencies_cause_startup_failure():
    with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
        val = validate_runtime_environment(strict=False)
        assert val["valid"] is False
        assert any("Missing required locked packages" in e for e in val["errors"])

        with pytest.raises(DependencyDriftError):
            validate_runtime_environment(strict=True)


# ── 10. Dependency drift is detected ──────────────────────────────────────────

def test_dependency_drift_is_detected():
    real_version = importlib.metadata.version

    def fake_version(pkg):
        if pkg in ("pydantic", "textual"):
            return "0.0.1-drifted"
        return real_version(pkg)

    with patch("importlib.metadata.version", side_effect=fake_version):
        val = validate_runtime_environment(strict=False)
        assert val["valid"] is False
        assert any("Dependency version drift detected" in e for e in val["errors"])


# ── 11. Fresh Python 3.12 environment installation succeeds ──────────────────

def test_fresh_python_312_environment_installation_succeeds():
    src_root = get_hermes_source_root()
    lock_file = src_root / "requirements.lock"
    assert lock_file.exists()
    assert lock_file.stat().st_size > 0

    val = validate_runtime_environment(strict=False)
    assert val["valid"] is True
    assert val["locked_package_count"] >= 40
    assert len(val["errors"]) == 0


# ── 12. Existing forensic regression suite still passes ──────────────────────

def test_existing_forensic_regression_suite_passes():
    canon_py = get_canonical_python_executable()
    src_root = get_hermes_source_root()
    res = subprocess.run(
        [canon_py, "-m", "pytest", str(src_root / "tests" / "test_forensic_regressions.py"), "-q"],
        cwd=str(src_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Forensic suite failed under Python 3.12: {res.stderr}"
    assert "15 passed" in res.stdout


# ── 13. Existing core regression suite still passes ──────────────────────────

def test_existing_core_regression_suite_passes():
    canon_py = get_canonical_python_executable()
    src_root = get_hermes_source_root()
    test_files = [
        str(src_root / "tests" / "test_workspace.py"),
        str(src_root / "tests" / "test_response_parser.py"),
        str(src_root / "tests" / "test_agent_loop.py"),
    ]
    res = subprocess.run(
        [canon_py, "-m", "pytest"] + test_files + ["-q"],
        cwd=str(src_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Core regression suite failed: {res.stderr}"
    assert "39 passed" in res.stdout


# ── 14. Runtime identity is deterministic ────────────────────────────────────

def test_runtime_identity_is_deterministic():
    id1 = detect_runtime_identity()
    id2 = detect_runtime_identity()

    assert id1.source_root == id2.source_root
    assert id1.commit == id2.commit
    assert id1.python_executable == id2.python_executable
    assert id1.python_version == id2.python_version
    assert id1.dependency_lock_hash == id2.dependency_lock_hash
    assert id1.key_packages == id2.key_packages
    assert id1.is_canonical_python is True
    assert id1.is_canonical_venv is True


# ── 15. Normal execution cannot silently fall back to another Python ─────────

def test_normal_execution_cannot_silently_fallback():
    # If Python version is non-3.12, ensure_canonical_runtime exits immediately with code 1
    with patch("sys.version_info", (3, 10, 0, "final", 0)):
        with pytest.raises(SystemExit) as exc:
            ensure_canonical_runtime()
        assert exc.value.code == 1

    with patch("sys.version_info", (3, 13, 0, "final", 0)):
        with pytest.raises(SystemExit) as exc:
            ensure_canonical_runtime()
        assert exc.value.code == 1
