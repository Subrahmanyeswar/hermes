# tools/platform/workspace_discovery.py
"""
Lightweight Workspace Discovery and Profile Cache for HERMES 2.x.
Provides evidence-based structural awareness (project type, manifest files,
source/test roots, VCS roots) so the agent does not repeatedly rediscover facts.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class WorkspaceProfile:
    """Evidence-based structural profile of a workspace."""
    workspace_root: str
    vcs_root: Optional[str] = None
    project_types: List[str] = field(default_factory=list)
    manifest_files: List[str] = field(default_factory=list)
    source_roots: List[str] = field(default_factory=list)
    test_roots: List[str] = field(default_factory=list)
    doc_roots: List[str] = field(default_factory=list)
    important_files: List[str] = field(default_factory=list)
    last_scanned_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "vcs_root": self.vcs_root,
            "project_types": self.project_types,
            "manifest_files": self.manifest_files,
            "source_roots": self.source_roots,
            "test_roots": self.test_roots,
            "doc_roots": self.doc_roots,
            "important_files": self.important_files,
            "last_scanned_at": self.last_scanned_at,
        }

    def to_summary_text(self) -> str:
        """Render a concise summary for model context."""
        lines = [f"Workspace: {Path(self.workspace_root).name}"]
        if self.project_types:
            lines.append(f"Project Type: {', '.join(self.project_types)}")
        if self.manifest_files:
            lines.append(f"Manifests: {', '.join(self.manifest_files)}")
        if self.source_roots:
            lines.append(f"Source Roots: {', '.join(self.source_roots)}")
        if self.test_roots:
            lines.append(f"Test Roots: {', '.join(self.test_roots)}")
        if self.important_files:
            lines.append(f"Key Files: {', '.join(self.important_files)}")
        return "\n".join(lines)


class WorkspaceDiscoveryService:
    """
    Scans and caches workspace profiles using deterministic file probes.
    Does not replace filesystem truth, but acts as a fast initial mental model.
    """

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._profiles: Dict[str, WorkspaceProfile] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def discover(self, root_path: Path | str, force_refresh: bool = False) -> WorkspaceProfile:
        """Probe workspace root and return evidence-based profile."""
        root = Path(root_path).resolve()
        root_str = str(root)

        with self._lock:
            existing = self._profiles.get(root_str)
            if existing and not force_refresh:
                if (time.time() - existing.last_scanned_at) < self._ttl_seconds:
                    return existing

        profile = self._scan_workspace(root)

        with self._lock:
            self._profiles[root_str] = profile

        return profile

    def _scan_workspace(self, root: Path) -> WorkspaceProfile:
        if not root.exists() or not root.is_dir():
            return WorkspaceProfile(workspace_root=str(root))

        manifests: List[str] = []
        project_types: List[str] = []
        source_roots: List[str] = []
        test_roots: List[str] = []
        doc_roots: List[str] = []
        important_files: List[str] = []
        vcs_root: Optional[str] = None

        # Check VCS
        if (root / ".git").exists():
            vcs_root = ".git"

        # Check Manifests and Project Types
        manifest_probes = [
            ("pyproject.toml", "python"),
            ("setup.py", "python"),
            ("requirements.txt", "python"),
            ("package.json", "node/javascript"),
            ("tsconfig.json", "typescript"),
            ("Cargo.toml", "rust"),
            ("go.mod", "go"),
            ("pom.xml", "java/maven"),
            ("build.gradle", "java/gradle"),
            ("Gemfile", "ruby"),
            ("composer.json", "php"),
        ]

        for filename, ptype in manifest_probes:
            probe = root / filename
            if probe.exists():
                manifests.append(filename)
                if ptype not in project_types:
                    project_types.append(ptype)

        # Check Standard Directory Structures
        dir_probes = [
            ("src", source_roots),
            ("lib", source_roots),
            ("core", source_roots),
            ("app", source_roots),
            ("tests", test_roots),
            ("test", test_roots),
            ("docs", doc_roots),
            ("documentation", doc_roots),
        ]

        for dname, target_list in dir_probes:
            dpath = root / dname
            if dpath.exists() and dpath.is_dir():
                target_list.append(dname)

        # Check Key Entrypoints / Configs
        key_files = [
            "README.md",
            "main.py",
            "app.py",
            "index.js",
            "index.ts",
            "config.py",
            "config.yaml",
            "docker-compose.yml",
            "Dockerfile",
            ".env.example",
        ]

        for kf in key_files:
            if (root / kf).exists():
                important_files.append(kf)

        return WorkspaceProfile(
            workspace_root=str(root),
            vcs_root=vcs_root,
            project_types=project_types,
            manifest_files=manifests,
            source_roots=source_roots,
            test_roots=test_roots,
            doc_roots=doc_roots,
            important_files=important_files,
            last_scanned_at=time.time(),
        )

    def invalidate(self, root_path: Path | str) -> None:
        """Invalidate cached profile for a workspace root."""
        root_str = str(Path(root_path).resolve())
        with self._lock:
            self._profiles.pop(root_str, None)

    def clear(self) -> None:
        """Clear all cached profiles."""
        with self._lock:
            self._profiles.clear()


# Global workspace discovery singleton
workspace_discovery = WorkspaceDiscoveryService()
