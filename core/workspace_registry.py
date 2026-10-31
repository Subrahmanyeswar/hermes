# core/workspace_registry.py
"""
Persistent Workspace Registry for HERMES Stage 9 Project Hub.
Manages recent workspaces, active workspace selection, validation,
and protected HERMES root detection.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

# HERMES repository root detection
HERMES_ROOT = Path(__file__).resolve().parent.parent

def get_canonical_registry_path() -> Path:
    """Resolve the canonical HERMES recent workspaces registry path."""
    env_path = os.environ.get("HERMES_REGISTRY_FILE")
    if env_path:
        return Path(env_path).resolve()
    return HERMES_ROOT / "data" / "recent_workspaces.json"


REGISTRY_FILE = get_canonical_registry_path()


def is_hermes_repo_root(path: Path | str) -> bool:
    """Return True if the given path matches the HERMES runtime repository root."""
    try:
        resolved = Path(path).resolve()
        return resolved == HERMES_ROOT.resolve()
    except Exception:
        return False


class WorkspaceRegistry:
    """
    Thread-safe persistent registry of opened and active workspaces.
    Stores metadata (path, name, last_opened, total_files, framework, language, is_hermes_repo).
    """

    def __init__(self, registry_file: Optional[Path | str] = None):
        self.registry_file = Path(registry_file).resolve() if registry_file else get_canonical_registry_path()
        self._lock = threading.RLock()
        self._active_path: Optional[str] = None
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            self._save({"active_path": None, "workspaces": []})

    def _load(self) -> Dict[str, Any]:
        try:
            if self.registry_file.exists():
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read workspace registry: {e}")
        return {"active_path": None, "workspaces": []}

    def _save(self, data: Dict[str, Any]) -> None:
        try:
            temp_file = self.registry_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.registry_file)
        except Exception as e:
            logger.error(f"Failed to save workspace registry: {e}")

    def inspect_directory(self, path: Path) -> Dict[str, Any]:
        """Scan directory lightly to count files and detect framework/language."""
        from core.workspace import IGNORE_PATTERNS
        total_files = 0
        framework = "unknown"
        language = "unknown"

        lang_counts: Dict[str, int] = {}
        has_pkg_json = False
        has_reqs_txt = False
        has_pyproject = False
        has_cargo = False

        try:
            # Walk up to 1000 files for fast inspection
            for root, dirs, files in os.walk(str(path)):
                # Filter ignored dirs in place
                dirs[:] = [d for d in dirs if d not in IGNORE_PATTERNS and not d.startswith(".")]
                for f in files:
                    if any(f.endswith(ign.replace("*", "")) for ign in IGNORE_PATTERNS if ign.startswith("*")):
                        continue
                    total_files += 1
                    ext = Path(f).suffix.lower()
                    if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".html"):
                        lang_counts[ext] = lang_counts.get(ext, 0) + 1
                    if f == "package.json":
                        has_pkg_json = True
                    elif f == "requirements.txt":
                        has_reqs_txt = True
                    elif f == "pyproject.toml":
                        has_pyproject = True
                    elif f == "Cargo.toml":
                        has_cargo = True
                    if total_files >= 1000:
                        break
                if total_files >= 1000:
                    break

            if has_pkg_json:
                framework = "Node/Web"
            elif has_pyproject or has_reqs_txt:
                framework = "Python"
            elif has_cargo:
                framework = "Rust"

            if lang_counts:
                top_ext = max(lang_counts.items(), key=lambda x: x[1])[0]
                ext_map = {
                    ".py": "python",
                    ".ts": "typescript",
                    ".tsx": "react/ts",
                    ".js": "javascript",
                    ".jsx": "react/js",
                    ".rs": "rust",
                    ".go": "go",
                    ".html": "html",
                }
                language = ext_map.get(top_ext, top_ext.lstrip("."))
        except Exception as e:
            logger.warning(f"Error inspecting directory {path}: {e}")

        return {
            "total_files": total_files,
            "framework": framework,
            "language": language,
        }

    def register_or_select(self, folder_path: str | Path, set_active: bool = True) -> Dict[str, Any]:
        """
        Validate directory, resolve path, add to recent workspaces, and optionally set as active.
        """
        resolved = Path(folder_path).resolve()
        if not resolved.exists():
            raise ValueError(f"Directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {resolved}")

        path_str = str(resolved)
        is_hermes = is_hermes_repo_root(resolved)
        inspection = self.inspect_directory(resolved)

        with self._lock:
            data = self._load()
            workspaces = data.get("workspaces", [])

            # Find existing entry or create new
            now = time.time()
            entry = None
            for w in workspaces:
                if Path(w["path"]).resolve() == resolved:
                    entry = w
                    break

            if entry:
                entry["last_opened"] = now
                entry["exists"] = True
                entry["total_files"] = inspection["total_files"]
                entry["framework"] = inspection["framework"]
                entry["language"] = inspection["language"]
                entry["is_hermes_repo"] = is_hermes
            else:
                entry = {
                    "path": path_str,
                    "name": resolved.name or path_str,
                    "last_opened": now,
                    "exists": True,
                    "total_files": inspection["total_files"],
                    "framework": inspection["framework"],
                    "language": inspection["language"],
                    "is_hermes_repo": is_hermes,
                }
                workspaces.append(entry)

            # Sort by last_opened descending
            workspaces.sort(key=lambda x: x.get("last_opened", 0), reverse=True)
            # Keep top 30
            workspaces = workspaces[:30]

            if set_active:
                data["active_path"] = path_str
                self._active_path = path_str

            data["workspaces"] = workspaces
            self._save(data)

            return entry

    def _get_active_path_unlocked(self, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        cand = self._active_path
        if not cand:
            if data is None:
                data = self._load()
            cand = data.get("active_path")
        if cand and Path(cand).exists() and Path(cand).is_dir():
            return cand
        return None

    def get_active_path(self) -> Optional[str]:
        with self._lock:
            return self._get_active_path_unlocked()

    def list_workspaces(self) -> List[Dict[str, Any]]:
        with self._lock:
            data = self._load()
            active = self._get_active_path_unlocked(data)
            raw_workspaces = data.get("workspaces", [])
            valid_workspaces = []
            changed = False
            for w in raw_workspaces:
                p = Path(w["path"])
                exists = p.exists() and p.is_dir()
                if exists:
                    w["exists"] = True
                    is_act = (p.resolve() == Path(active).resolve()) if active else False
                    w["is_active"] = is_act
                    w["is_hermes_repo"] = is_hermes_repo_root(p)
                    # Refresh file count & metadata dynamically for valid directories
                    try:
                        meta = self.inspect_directory(p)
                        new_total = meta.get("total_files", w.get("total_files", 0))
                        if new_total != w.get("total_files"):
                            w["total_files"] = new_total
                            changed = True
                        if meta.get("language") and meta.get("language") != "unknown":
                            w["language"] = meta["language"]
                        if meta.get("framework") and meta.get("framework") != "unknown":
                            w["framework"] = meta["framework"]
                    except Exception:
                        pass
                    valid_workspaces.append(w)

            # If cleaned list or metadata changed, persist cleanup
            if len(valid_workspaces) != len(raw_workspaces) or changed:
                data["workspaces"] = valid_workspaces
                data["active_path"] = active
                self._save(data)

            return valid_workspaces

    def remove_recent(self, folder_path: str | Path) -> bool:
        """Remove a folder from recent list without deleting filesystem content."""
        resolved = Path(folder_path).resolve()
        with self._lock:
            data = self._load()
            workspaces = data.get("workspaces", [])
            initial_len = len(workspaces)
            workspaces = [w for w in workspaces if Path(w["path"]).resolve() != resolved]
            data["workspaces"] = workspaces
            if data.get("active_path") and Path(data["active_path"]).resolve() == resolved:
                data["active_path"] = workspaces[0]["path"] if workspaces else None
                self._active_path = data["active_path"]
            self._save(data)
            return len(workspaces) < initial_len


# Global singleton instance
workspace_registry = WorkspaceRegistry()
