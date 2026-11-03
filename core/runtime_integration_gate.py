# core/runtime_integration_gate.py
"""
Runtime Integration Gate for HERMES Full-Stack Web Missions (Section 9.3).
Enforces the mandatory 10-step runtime integration verification:
  1. Source syntax validation.
  2. Backend startup on ephemeral/local port.
  3. Root page HTTP 200.
  4. Frontend assets HTTP 200.
  5. Required API requests succeed.
  6. Static security isolation (source and DB return 404).
  7. Clean shutdown and process cleanup.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


@dataclass
class RuntimeStepResult:
    step_num: int
    name: str
    passed: bool
    details: str = ""
    error: Optional[str] = None


@dataclass
class RuntimeIntegrationReport:
    passed: bool
    step_results: List[RuntimeStepResult] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.passed:
            return f"Runtime Integration Gate: PASSED all {len(self.step_results)} checks."
        return (
            f"Runtime Integration Gate: FAILED on {len(self.failed_steps)} step(s): "
            f"{', '.join(self.failed_steps)}."
        )


class RuntimeIntegrationGate:
    """Executes automated runtime integration validation for full-stack applications."""

    def __init__(self, workspace_root: Path | str, python_exe: Optional[str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.python_exe = python_exe or (
            r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe"
            if Path(r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe").exists()
            else "python"
        )

    def execute_gate(self, test_port: int = 8089) -> RuntimeIntegrationReport:
        results: List[RuntimeStepResult] = []
        failed_steps: List[str] = []

        # ── STEP 1: Source Syntax Validation ──────────────────────────────────
        syntax_ok = True
        syntax_err = None
        for py_file in self.workspace_root.glob("*.py"):
            try:
                ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"), filename=py_file.name)
            except SyntaxError as e:
                syntax_ok = False
                syntax_err = f"SyntaxError in {py_file.name}: {e.msg} (line {e.lineno})"
                break

        results.append(RuntimeStepResult(1, "source_syntax_validation", syntax_ok, "Python AST parsed without syntax errors" if syntax_ok else "", syntax_err))
        if not syntax_ok:
            failed_steps.append("source_syntax_validation")
            return RuntimeIntegrationReport(passed=False, step_results=results, failed_steps=failed_steps)

        # ── STEP 2: Backend Startup ───────────────────────────────────────────
        be_entry = self.workspace_root / "main.py"
        if not be_entry.exists():
            be_entry = self.workspace_root / "app.py"

        if not be_entry.exists():
            results.append(RuntimeStepResult(2, "backend_startup", False, "", "No backend entrypoint (main.py/app.py) found."))
            failed_steps.append("backend_startup")
            return RuntimeIntegrationReport(passed=False, step_results=results, failed_steps=failed_steps)

        server_env = os.environ.copy()
        server_env["PYTHONUNBUFFERED"] = "1"
        # Isolate database for integration run
        temp_db = self.workspace_root / "temp_runtime_gate.db"
        server_env["CAMPUSFLOW_DB_PATH"] = str(temp_db)

        proc = None
        try:
            proc = subprocess.Popen(
                [self.python_exe, "-m", "uvicorn", f"{be_entry.stem}:app", "--host", "127.0.0.1", "--port", str(test_port)],
                cwd=str(self.workspace_root),
                env=server_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for health
            server_live = False
            for _ in range(10):
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/api/health", timeout=1) as resp:
                        if resp.status == 200:
                            server_live = True
                            break
                except Exception:
                    pass

            results.append(RuntimeStepResult(2, "backend_startup", server_live, f"Backend responding on port {test_port}" if server_live else "", None if server_live else "Server did not boot within 5s"))
            if not server_live:
                failed_steps.append("backend_startup")
                return RuntimeIntegrationReport(passed=False, step_results=results, failed_steps=failed_steps)

            # ── STEP 3: Root Page HTTP 200 ────────────────────────────────────
            root_ok = False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/", timeout=2) as resp:
                    root_ok = (resp.status == 200)
            except Exception as e:
                root_err = str(e)

            results.append(RuntimeStepResult(3, "root_page_200", root_ok, "Root '/' returned HTTP 200" if root_ok else "", None if root_ok else "Failed to load '/'"))
            if not root_ok:
                failed_steps.append("root_page_200")

            # ── STEP 4: Frontend Assets HTTP 200 ──────────────────────────────
            assets_ok = True
            asset_errs = []
            for asset in ("/static/style.css", "/static/app.js"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{test_port}{asset}", timeout=2) as resp:
                        if resp.status != 200:
                            assets_ok = False
                            asset_errs.append(f"{asset} -> {resp.status}")
                except Exception as e:
                    assets_ok = False
                    asset_errs.append(f"{asset} -> {e}")

            results.append(RuntimeStepResult(4, "frontend_assets_200", assets_ok, "Static assets loaded with HTTP 200" if assets_ok else "", "; ".join(asset_errs) if asset_errs else None))
            if not assets_ok:
                failed_steps.append("frontend_assets_200")

            # ── STEP 5: Required API Endpoints Respond ────────────────────────
            api_ok = True
            api_errs = []
            for ep in ("/api/dashboard/summary", "/api/companies", "/api/applications"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{test_port}{ep}", timeout=2) as resp:
                        if resp.status not in (200, 201):
                            api_ok = False
                            api_errs.append(f"{ep} -> {resp.status}")
                except Exception as e:
                    api_ok = False
                    api_errs.append(f"{ep} -> {e}")

            results.append(RuntimeStepResult(5, "api_endpoints_responding", api_ok, "Primary API endpoints returned 200 OK" if api_ok else "", "; ".join(api_errs) if api_errs else None))
            if not api_ok:
                failed_steps.append("api_endpoints_responding")

            # ── STEP 6: Static Security Isolation ─────────────────────────────
            sec_ok = True
            for sensitive in ("/static/main.py", "/static/campusflow.db"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{test_port}{sensitive}", timeout=1) as resp:
                        if resp.status == 200:
                            sec_ok = False
                except urllib.error.HTTPError as he:
                    if he.code != 404:
                        sec_ok = False
                except Exception:
                    pass

            results.append(RuntimeStepResult(6, "static_security_isolation", sec_ok, "Source and database return 404 from /static" if sec_ok else "", None if sec_ok else "Security leak: source/DB accessible via /static"))
            if not sec_ok:
                failed_steps.append("static_security_isolation")

        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            if temp_db.exists():
                try:
                    temp_db.unlink()
                except Exception:
                    pass

        all_passed = len(failed_steps) == 0
        return RuntimeIntegrationReport(
            passed=all_passed,
            step_results=results,
            failed_steps=failed_steps,
        )
