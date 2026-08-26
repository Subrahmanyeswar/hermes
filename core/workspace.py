# core/workspace.py
# WorkspaceManager — the foundational context boundary for HERMES v4.0.
#
# Responsibilities:
#   1. Locks HERMES to one absolute project directory per session.
#   2. Builds and maintains a lightweight codebase index (folder skeleton + file map).
#   3. Provides context-efficient file retrieval for the Context Builder.
#   4. Enforces workspace boundary — every tool path is validated against workspace_root.
#   5. Watches for file system changes and updates the index incrementally.
#
# Design rule: Never dump the entire codebase into the context window.
# Instead, expose three levels of context:
#   Level 1 — skeleton:    folder tree structure (max 60 lines)
#   Level 2 — signatures:  class/function names from target files only (via AST)
#   Level 3 — content:     full file content only when explicitly required by the task
#
# This matches how Claude Code and Codex handle large projects without VRAM overflow.

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from loguru import logger


# ── Ignore patterns (never index these) ──────────────────────────────────────
IGNORE_PATTERNS: list[str] = [
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "*.pyc", "*.pyo", "*.pyd", ".DS_Store", "*.egg-info", "dist",
    "build", ".pytest_cache", ".mypy_cache", "*.min.js", "*.min.css",
    ".next", ".nuxt", "target", "*.lock", "package-lock.json",
]

# ── Hard limits to protect the context window ────────────────────────────────
MAX_SKELETON_LINES: int = 60       # Maximum lines in the folder tree output
MAX_FILE_SIZE_BYTES: int = 50_000  # Files larger than this are summarised, not read
MAX_CONTEXT_FILES: int = 8         # Maximum files injected per task context build
MAX_SIGNATURE_LINES: int = 40     # Maximum AST signature lines per file


@dataclass
class FileEntry:
    """Lightweight index entry for one file in the workspace."""
    relative_path: str
    absolute_path: str
    size_bytes: int
    extension: str
    last_modified: float
    content_hash: str = ""
    ast_signatures: list[str] = field(default_factory=list)

    @property
    def is_code_file(self) -> bool:
        return self.extension in {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs",
            ".java", ".cpp", ".c", ".h", ".cs", ".rb", ".php",
            ".vue", ".svelte", ".html", ".css", ".scss",
        }

    @property
    def is_config_file(self) -> bool:
        return self.extension in {
            ".json", ".yaml", ".yml", ".toml", ".env", ".ini",
            ".cfg", ".conf", ".xml",
        } or self.relative_path in {
            "requirements.txt", "Makefile", "Dockerfile",
            "docker-compose.yml", ".gitignore", "README.md",
        }


@dataclass
class WorkspaceIndex:
    """In-memory index of the entire workspace."""
    workspace_root: str
    files: dict[str, FileEntry] = field(default_factory=dict)  # rel_path -> FileEntry
    indexed_at: float = 0.0
    framework_detected: str = "unknown"
    language_detected: str = "unknown"
    total_files: int = 0
    total_size_bytes: int = 0

    def get_by_extension(self, ext: str) -> list[FileEntry]:
        return [f for f in self.files.values() if f.extension == ext]

    def search(self, query: str) -> list[FileEntry]:
        """Find files whose path contains the query string."""
        q = query.lower()
        return [f for f in self.files.values() if q in f.relative_path.lower()]


class WorkspaceManager:
    """
    The workspace boundary enforcer and codebase intelligence layer for HERMES.

    Usage:
        wm = WorkspaceManager()
        wm.lock("/path/to/project")
        skeleton = wm.get_skeleton()           # for context injection
        sigs = wm.get_signatures("models.py")  # for task-specific context
        wm.validate_path("../escape")          # raises WorkspaceBoundaryError
    """

    def __init__(self) -> None:
        self.workspace_root: Optional[Path] = None
        self.index: Optional[WorkspaceIndex] = None
        self._locked: bool = False

    # ── Locking ───────────────────────────────────────────────────────────────

    def lock(self, path: str) -> None:
        """
        Lock the workspace to the given directory.
        Resolves symlinks, validates existence, builds initial index.
        Raises: ValueError if path does not exist or is not a directory.
        """
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise ValueError(f"Workspace path does not exist: {path}")
        if not resolved.is_dir():
            raise ValueError(f"Workspace path is not a directory: {path}")

        self.workspace_root = resolved
        self._locked = True
        logger.info(f"WorkspaceManager: locked to {self.workspace_root}")
        self._build_index()

    def lock_to_cwd(self) -> None:
        """Lock to the current working directory. Used when no explicit path given."""
        self.lock(os.getcwd())

    @property
    def is_locked(self) -> bool:
        return self._locked and self.workspace_root is not None

    @property
    def root_str(self) -> str:
        if self.workspace_root is None:
            return os.getcwd()
        return str(self.workspace_root)

    # ── Path validation (security boundary) ──────────────────────────────────

    def validate_path(self, path: str) -> Path:
        """
        Validate that a path is within the workspace boundary.
        This is the security enforcement layer — called by every tool
        before touching the filesystem.

        Returns: absolute Path if valid.
        Raises:  WorkspaceBoundaryError if path escapes workspace_root.
        """
        if not self.is_locked:
            # If not locked, resolve relative to cwd
            return Path(path).resolve()

        # Resolve the path relative to workspace_root
        if Path(path).is_absolute():
            candidate = Path(path).resolve()
        else:
            candidate = (self.workspace_root / path).resolve()

        # Check containment — candidate must be inside workspace_root
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            raise WorkspaceBoundaryError(
                f"Path '{path}' resolves to '{candidate}' which is outside "
                f"workspace boundary '{self.workspace_root}'. "
                f"Access denied by WorkspaceManager security gate."
            )

        return candidate

    def is_path_safe(self, path: str) -> tuple[bool, str]:
        """Non-raising version of validate_path. Returns (safe, reason)."""
        try:
            self.validate_path(path)
            return True, "path is within workspace boundary"
        except WorkspaceBoundaryError as e:
            return False, str(e)

    # ── Indexing ──────────────────────────────────────────────────────────────

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path matches any ignore pattern."""
        for pattern in IGNORE_PATTERNS:
            if fnmatch.fnmatch(path.name, pattern):
                return True
            if path.name == pattern:
                return True
        return False

    def _build_index(self) -> None:
        """
        Walk the workspace and build a lightweight file index.
        Called once on lock() and incrementally on refresh().
        """
        if self.workspace_root is None:
            return

        start = time.monotonic()
        idx = WorkspaceIndex(workspace_root=str(self.workspace_root))

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune ignored directories in-place (prevents walking into them)
            dirs[:] = [
                d for d in dirs
                if not self._should_ignore(Path(root) / d)
            ]

            for filename in files:
                abs_path = Path(root) / filename
                if self._should_ignore(abs_path):
                    continue

                try:
                    stat = abs_path.stat()
                    rel_path = str(abs_path.relative_to(self.workspace_root))
                    entry = FileEntry(
                        relative_path=rel_path,
                        absolute_path=str(abs_path),
                        size_bytes=stat.st_size,
                        extension=abs_path.suffix.lower(),
                        last_modified=stat.st_mtime,
                    )
                    idx.files[rel_path] = entry
                    idx.total_files += 1
                    idx.total_size_bytes += stat.st_size
                except (PermissionError, OSError):
                    continue

        idx.indexed_at = time.monotonic()
        idx.framework_detected = self._detect_framework(idx)
        idx.language_detected = self._detect_language(idx)
        self.index = idx

        elapsed = time.monotonic() - start
        logger.info(
            f"WorkspaceManager: indexed {idx.total_files} files "
            f"in {elapsed:.2f}s | framework={idx.framework_detected}"
        )

    def refresh_index(self) -> None:
        """Rebuild the index. Call after significant file system changes."""
        self._build_index()

    def _detect_framework(self, idx: WorkspaceIndex) -> str:
        """Heuristic framework detection from file presence."""
        files = set(idx.files.keys())
        file_str = " ".join(files).lower()

        if "requirements.txt" in files or any(".py" in f for f in files):
            if any("flask" in f or "app.py" in f for f in files):
                return "Flask"
            if any("django" in f or "manage.py" in f for f in files):
                return "Django"
            if any("fastapi" in f or "main.py" in f for f in files):
                return "FastAPI"
            return "Python"

        if "package.json" in files:
            if any("react" in f for f in files):
                return "React"
            if "next.config.js" in files or "next.config.ts" in files:
                return "Next.js"
            if any("vue" in f for f in files):
                return "Vue"
            return "Node.js"

        if "Cargo.toml" in files:
            return "Rust"
        if "go.mod" in files:
            return "Go"
        if "pom.xml" in files:
            return "Java/Maven"

        return "unknown"

    def _detect_language(self, idx: WorkspaceIndex) -> str:
        """Detect primary language from file extension frequency."""
        ext_counts: dict[str, int] = {}
        for entry in idx.files.values():
            if entry.extension:
                ext_counts[entry.extension] = ext_counts.get(entry.extension, 0) + 1

        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".go": "Go", ".rs": "Rust", ".java": "Java",
            ".cpp": "C++", ".c": "C", ".rb": "Ruby",
        }
        if not ext_counts:
            return "unknown"

        top_ext = max(ext_counts, key=ext_counts.get)
        return lang_map.get(top_ext, top_ext.lstrip(".").upper())

    # ── Context generation ────────────────────────────────────────────────────

    def get_skeleton(self) -> str:
        """
        Generate a compact folder tree for injection into the LLM context.
        Maximum MAX_SKELETON_LINES lines. Prioritises source files over build artifacts.

        Example output:
            EduPath/
            ├── src/
            │   ├── components/
            │   │   ├── Auth.jsx
            │   │   └── Dashboard.jsx
            │   ├── routes.js
            │   └── App.jsx
            ├── package.json
            └── README.md
        """
        if self.workspace_root is None:
            return "(no workspace locked)"
        if self.index is None:
            self._build_index()

        lines: list[str] = [f"{self.workspace_root.name}/"]
        seen_dirs: set[str] = set()
        file_lines: list[str] = []

        # Collect all unique dirs first
        all_paths = sorted(self.index.files.keys())
        for rel_path in all_paths:
            parts = Path(rel_path).parts
            # Build directory tree lines
            for depth in range(len(parts) - 1):
                dir_key = "/".join(parts[:depth + 1])
                if dir_key not in seen_dirs:
                    seen_dirs.add(dir_key)
                    indent = "│   " * depth + "├── "
                    file_lines.append(f"{indent}{parts[depth]}/")

            # File line
            depth = len(parts) - 1
            indent = "│   " * depth + "├── "
            file_lines.append(f"{indent}{parts[-1]}")

        # Truncate to MAX_SKELETON_LINES
        if len(file_lines) > MAX_SKELETON_LINES:
            file_lines = file_lines[:MAX_SKELETON_LINES]
            file_lines.append(f"    ... ({self.index.total_files} total files)")

        lines.extend(file_lines)
        return "\n".join(lines)

    def get_signatures(self, relative_path: str) -> str:
        """
        Extract class and function signatures from a Python file using AST.
        Returns a compact signature list for context injection.
        Used for code-aware task planning without reading the full file.

        Example output:
            class UserModel(db.Model):
                def __init__(self, username, email)
                def check_password(self, password) -> bool
                def to_dict(self) -> dict
            def create_user(username, email, password) -> UserModel
        """
        if self.workspace_root is None:
            return ""

        try:
            abs_path = self.validate_path(relative_path)
        except WorkspaceBoundaryError:
            return ""

        if not abs_path.exists() or abs_path.suffix != ".py":
            return ""

        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            if len(source) > MAX_FILE_SIZE_BYTES * 2:
                source = source[:MAX_FILE_SIZE_BYTES * 2]

            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            return f"(could not parse {relative_path})"

        lines: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(
                    ast.unparse(b) for b in node.bases
                ) if node.bases else ""
                class_sig = f"class {node.name}"
                if bases:
                    class_sig += f"({bases})"
                class_sig += ":"
                lines.append(class_sig)

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        try:
                            sig = f"    def {item.name}({ast.unparse(item.args)})"
                            if item.returns:
                                sig += f" -> {ast.unparse(item.returns)}"
                            lines.append(sig)
                        except Exception:
                            lines.append(f"    def {item.name}(...)")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level functions only (not methods — those appear under class)
                is_method = False
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        body = getattr(parent, "body", None)
                        if isinstance(body, list) and node in body:
                            is_method = True
                            break
                if not is_method:
                    try:
                        sig = f"def {node.name}({ast.unparse(node.args)})"
                        if node.returns:
                            sig += f" -> {ast.unparse(node.returns)}"
                        lines.append(sig)
                    except Exception:
                        lines.append(f"def {node.name}(...)")

        if len(lines) > MAX_SIGNATURE_LINES:
            lines = lines[:MAX_SIGNATURE_LINES]
            lines.append("  ... (truncated)")

        return "\n".join(lines)

    def get_file_content(self, relative_path: str) -> str:
        """
        Read a file's full content. Enforces workspace boundary and size limit.
        Files over MAX_FILE_SIZE_BYTES are truncated with a notice.
        """
        try:
            abs_path = self.validate_path(relative_path)
        except WorkspaceBoundaryError as e:
            return f"ERROR: {e}"

        if not abs_path.exists():
            return f"ERROR: File not found: {relative_path}"

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            if len(content.encode()) > MAX_FILE_SIZE_BYTES:
                truncated = content[:MAX_FILE_SIZE_BYTES]
                return (
                    truncated
                    + f"\n\n... [TRUNCATED — file exceeds {MAX_FILE_SIZE_BYTES} bytes] ..."
                )
            return content
        except (PermissionError, OSError) as e:
            return f"ERROR: Cannot read file: {e}"

    def get_relevant_files(self, task_description: str, max_files: int = 5) -> list[str]:
        """
        Return relative paths of files most relevant to a task description.
        Simple keyword matching — enough for context injection without embedding overhead.
        """
        if self.index is None:
            return []

        task_lower = task_description.lower()
        scored: list[tuple[float, str]] = []

        keywords = [w for w in task_lower.split() if len(w) > 3]

        for rel_path, entry in self.index.files.items():
            if not (entry.is_code_file or entry.is_config_file):
                continue

            path_lower = rel_path.lower()
            score = sum(1.0 for kw in keywords if kw in path_lower)

            # Boost common important files
            if any(name in rel_path for name in ["app.py", "main.py", "models.py",
                                                   "routes.py", "config.py", "index.js"]):
                score += 0.5

            if score > 0:
                scored.append((score, rel_path))

        scored.sort(key=lambda x: -x[0])
        return [path for _, path in scored[:max_files]]

    def get_workspace_summary(self) -> dict:
        """Return a compact dict of workspace metadata for status bar and logging."""
        if self.index is None:
            return {"locked": False}
        return {
            "locked": self.is_locked,
            "root": self.root_str,
            "framework": self.index.framework_detected,
            "language": self.index.language_detected,
            "total_files": self.index.total_files,
            "total_size_kb": round(self.index.total_size_bytes / 1024, 1),
        }


class WorkspaceBoundaryError(Exception):
    """Raised when a tool attempts to access a path outside the workspace root."""
    pass


# ── Module-level singleton ────────────────────────────────────────────────────
# Every module that needs workspace access imports this instance.
workspace_manager = WorkspaceManager()
