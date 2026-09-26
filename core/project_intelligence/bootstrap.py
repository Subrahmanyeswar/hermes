# core/project_intelligence/bootstrap.py
"""
Environment Lifecycle and Bootstrap Command Engine for HERMES 2.x Project Intelligence.
Discovers, indexes, and normalizes repository execution commands across platforms:
- install (dependencies)
- start (production application)
- test (unit and integration tests)
- lint (static analysis and formatting)
- build (compilation and packaging)
- dev (development server / watch mode)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from loguru import logger

from core.project_intelligence.models import BootstrapAction, BootstrapCommand, BootstrapManifest
from tools.platform.workspace_discovery import WorkspaceDiscoveryService, WorkspaceProfile


class BootstrapEngine:
    """
    Manages discovery and normalization of lifecycle commands.
    Distinguishes declared project commands from auto-detected workspace suggestions.
    Guarantees that commands are never auto-executed without explicit permission gating.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.discovery_service = WorkspaceDiscoveryService()
        self._manifest: Optional[BootstrapManifest] = None
        self._manifest_mtime: int = 0

    def discover_bootstrap_dir(self) -> Optional[Path]:
        """Locate bootstrap directory in workspace."""
        candidates = [
            self.workspace_root / ".hermes" / "bootstrap",
            self.workspace_root / ".bootstrap",
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return c
        return None

    def discover(self, force_reload: bool = False) -> BootstrapManifest:
        """
        Discover explicit bootstrap definitions or synthesize from workspace discovery.
        """
        b_dir = self.discover_bootstrap_dir()
        if b_dir:
            manifest = self._load_explicit_bootstrap(b_dir)
            if manifest:
                self._manifest = manifest
                return manifest

        # Fallback: Auto-detect from workspace manifests
        manifest = self._detect_from_workspace()
        self._manifest = manifest
        return manifest

    def get_command(self, action: str | BootstrapAction) -> Optional[BootstrapCommand]:
        """Retrieve command definition for a specific lifecycle action."""
        act_str = action.value if isinstance(action, BootstrapAction) else action.lower()
        if not self._manifest:
            self.discover()
        if self._manifest:
            return self._manifest.commands.get(act_str)
        return None

    def check_freshness(self) -> Tuple[bool, Optional[BootstrapManifest]]:
        """Check whether bootstrap files or underlying workspace manifests have changed."""
        b_dir = self.discover_bootstrap_dir()
        if b_dir:
            # Check explicit files
            for target_name in ("bootstrap.json", "bootstrap.yaml", "bootstrap.yml"):
                p = b_dir / target_name
                if p.exists():
                    try:
                        stat = p.stat()
                        if stat.st_mtime_ns != self._manifest_mtime:
                            fresh = self.discover(force_reload=True)
                            return True, fresh
                    except Exception:
                        pass
        return False, self._manifest

    # ── Explicit Loading ──────────────────────────────────────────────────────

    def _load_explicit_bootstrap(self, b_dir: Path) -> Optional[BootstrapManifest]:
        """Load declared bootstrap commands from bootstrap.json or bootstrap.yaml."""
        # 1. Check bootstrap.json
        json_file = b_dir / "bootstrap.json"
        if json_file.exists():
            try:
                raw_bytes = json_file.read_bytes()
                data = json.loads(raw_bytes.decode("utf-8"))
                commands = self._parse_command_dict(data, source="project")
                stat = json_file.stat()
                self._manifest_mtime = stat.st_mtime_ns
                return BootstrapManifest(
                    commands=commands,
                    source_file=str(json_file),
                    sha256_hash=hashlib.sha256(raw_bytes).hexdigest(),
                    manifest_type="explicit",
                )
            except Exception as exc:
                logger.error(f"BootstrapEngine: failed to parse '{json_file}': {exc}")

        # 2. Check bootstrap.yaml / yml
        for y_name in ("bootstrap.yaml", "bootstrap.yml"):
            y_file = b_dir / y_name
            if y_file.exists():
                try:
                    raw_bytes = y_file.read_bytes()
                    data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
                    commands = self._parse_command_dict(data, source="project")
                    stat = y_file.stat()
                    self._manifest_mtime = stat.st_mtime_ns
                    return BootstrapManifest(
                        commands=commands,
                        source_file=str(y_file),
                        sha256_hash=hashlib.sha256(raw_bytes).hexdigest(),
                        manifest_type="explicit",
                    )
                except Exception as exc:
                    logger.error(f"BootstrapEngine: failed to parse '{y_file}': {exc}")

        # 3. Check individual action files (e.g. test.md, install.md)
        commands: Dict[str, BootstrapCommand] = {}
        for action in BootstrapAction:
            f = b_dir / f"{action.value}.md"
            if f.exists():
                cmd = self._parse_single_action_file(f, action.value)
                if cmd:
                    commands[action.value] = cmd

        if commands:
            return BootstrapManifest(
                commands=commands,
                source_file=str(b_dir),
                manifest_type="explicit",
            )

        return None

    def _parse_command_dict(self, data: Dict[str, Any], source: str) -> Dict[str, BootstrapCommand]:
        """Convert dictionary of action definitions to BootstrapCommand objects."""
        # Unpack if nested under 'commands' or 'actions'
        if "commands" in data and isinstance(data["commands"], dict):
            data = data["commands"]
        elif "actions" in data and isinstance(data["actions"], dict):
            data = data["actions"]

        commands = {}
        for act_name, entry in data.items():
            if isinstance(entry, str):
                cmd = entry
                working_dir = "."
                timeout = 300
                platform = "all"
                desc = f"Run {act_name}"
                risk = self._classify_risk(act_name)
            elif isinstance(entry, dict):
                cmd = entry.get("command", "")
                working_dir = entry.get("working_directory", ".")
                timeout = int(entry.get("timeout_seconds", 300))
                platform = entry.get("platform", "all")
                desc = entry.get("description", f"Run {act_name}")
                risk = entry.get("risk", self._classify_risk(act_name))
            else:
                continue

            # Platform normalization for Windows
            norm_cmd = self._normalize_command_for_platform(cmd, platform)

            commands[act_name.lower()] = BootstrapCommand(
                action=act_name.lower(),
                command=norm_cmd,
                working_directory=working_dir,
                platform=platform,
                timeout_seconds=timeout,
                risk=risk,
                source=source,
                description=desc,
            )
        return commands

    def _parse_single_action_file(self, file_path: Path, action: str) -> Optional[BootstrapCommand]:
        """Extract command from a Markdown action file (e.g. test.md)."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            # Look for code block
            lines = content.splitlines()
            cmd_lines = []
            in_code = False
            for line in lines:
                if line.startswith("```"):
                    if in_code:
                        break
                    in_code = True
                    continue
                if in_code:
                    cmd_lines.append(line.strip())

            cmd = "\n".join(cmd_lines).strip()
            if not cmd and lines:
                cmd = lines[0].strip()

            if cmd:
                return BootstrapCommand(
                    action=action,
                    command=self._normalize_command_for_platform(cmd, "all"),
                    source="project",
                    risk=self._classify_risk(action),
                    description=f"Declared {action} action",
                )
        except Exception:
            pass
        return None

    # ── Workspace Heuristic Detection ─────────────────────────────────────────

    def _detect_from_workspace(self) -> BootstrapManifest:
        """Synthesize candidate bootstrap suggestions using WorkspaceDiscoveryService."""
        profile: WorkspaceProfile = self.discovery_service.discover(self.workspace_root)
        commands: Dict[str, BootstrapCommand] = {}

        is_windows = os.name == "nt"

        # Python projects
        if any("python" in pt for pt in profile.project_types) or any(m in profile.manifest_files for m in ("pyproject.toml", "setup.py", "requirements.txt")):
            py_cmd = "python" if is_windows else "python3"
            # Test
            commands["test"] = BootstrapCommand(
                action="test",
                command=f"{py_cmd} -m pytest",
                source="auto_detected",
                risk="low",
                description="Run pytest test suite",
            )
            # Lint
            commands["lint"] = BootstrapCommand(
                action="lint",
                command=f"{py_cmd} -m flake8",
                source="auto_detected",
                risk="low",
                description="Run Python linter",
            )
            # Install
            if (self.workspace_root / "requirements.txt").exists():
                commands["install"] = BootstrapCommand(
                    action="install",
                    command=f"{py_cmd} -m pip install -r requirements.txt",
                    source="auto_detected",
                    risk="high",
                    description="Install requirements via pip",
                )
            elif (self.workspace_root / "pyproject.toml").exists():
                commands["install"] = BootstrapCommand(
                    action="install",
                    command=f"{py_cmd} -m pip install -e .",
                    source="auto_detected",
                    risk="high",
                    description="Install package in editable mode",
                )

        # Node / TypeScript projects
        if any("node" in pt or "javascript" in pt or "typescript" in pt for pt in profile.project_types) or "package.json" in profile.manifest_files or (self.workspace_root / "package.json").exists():
            pkg_file = self.workspace_root / "package.json"
            if pkg_file.exists():
                try:
                    pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
                    scripts = pkg_data.get("scripts", {})
                    npm_prefix = "npm" if not is_windows else "npm.cmd"

                    if "test" in scripts:
                        commands["test"] = BootstrapCommand(
                            action="test",
                            command=f"{npm_prefix} test",
                            source="auto_detected",
                            risk="low",
                            description="Run npm test",
                        )
                    if "lint" in scripts:
                        commands["lint"] = BootstrapCommand(
                            action="lint",
                            command=f"{npm_prefix} run lint",
                            source="auto_detected",
                            risk="low",
                            description="Run npm lint",
                        )
                    if "build" in scripts:
                        commands["build"] = BootstrapCommand(
                            action="build",
                            command=f"{npm_prefix} run build",
                            source="auto_detected",
                            risk="medium",
                            description="Build project bundle",
                        )
                    if "dev" in scripts:
                        commands["dev"] = BootstrapCommand(
                            action="dev",
                            command=f"{npm_prefix} run dev",
                            source="auto_detected",
                            risk="medium",
                            description="Start development server",
                        )
                    commands["install"] = BootstrapCommand(
                        action="install",
                        command=f"{npm_prefix} install",
                        source="auto_detected",
                        risk="high",
                        description="Install node modules",
                    )
                except Exception:
                    pass

        return BootstrapManifest(
            commands=commands,
            source_file="workspace_discovery",
            manifest_type="workspace_detected",
        )

    def _normalize_command_for_platform(self, cmd: str, platform: str) -> str:
        """Adapt Unix command idioms to Windows where practical."""
        if os.name == "nt":
            if cmd.startswith("python3 "):
                return "python " + cmd[8:]
            if cmd == "pytest":
                return "python -m pytest"
        return cmd

    def _classify_risk(self, action: str) -> str:
        """Classify risk based on action semantics."""
        high_risk = {"install", "deploy", "migrate"}
        med_risk = {"build", "dev", "start"}
        if action in high_risk:
            return "high"
        if action in med_risk:
            return "medium"
        return "low"
