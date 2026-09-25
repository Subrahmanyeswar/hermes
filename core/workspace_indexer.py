# core/workspace_indexer.py
"""
Workspace Indexer & Incremental Change Engine for HERMES vNext (Phase 7).
Provides persistent SQLite storage, metadata+SHA256 change detection,
AST symbol extraction, import mapping, and dependency tracking.
"""

from __future__ import annotations

import ast
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

from loguru import logger
from config.model_config import WORKSPACE_INTELLIGENCE_ENABLED

IGNORE_PATTERNS = [
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "*.pyc", "*.pyo", "*.pyd", ".DS_Store", "*.egg-info", "dist",
    "build", ".pytest_cache", ".mypy_cache", "*.min.js", "*.min.css",
    ".next", ".nuxt", "target", "*.lock", "package-lock.json",
    "artifacts",
]

MAX_PARSE_FILE_SIZE = 500_000  # 500 KB limit for AST parsing
DB_PATH = Path("hermes_workspace_index.db")


@dataclass
class FileIndexRecord:
    rel_path: str
    abs_path: str
    extension: str
    language: str
    size_bytes: int
    mtime: float
    content_hash: str
    parse_status: str
    symbols: List[Dict[str, Any]] = field(default_factory=list)
    imports: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class IncrementalUpdateReport:
    workspace_root: str
    files_discovered: int = 0
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    duration_ms: float = 0.0
    added_records: List[FileIndexRecord] = field(default_factory=list)
    modified_records: List[FileIndexRecord] = field(default_factory=list)
    deleted_paths: Set[str] = field(default_factory=set)
    asts_rebuilt: int = 0
    symbols_rebuilt: int = 0
    imports_rebuilt: int = 0


class WorkspaceIndexStore:
    """Persistent SQLite repository for workspace metadata, AST symbols, and imports."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def check_integrity(self) -> bool:
        """Performs SQLite quick_check integrity validation."""
        try:
            with self._get_conn() as conn:
                res = conn.execute("PRAGMA quick_check").fetchone()
                return bool(res and res[0] == "ok")
        except Exception:
            return False

    def _create_tables(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    root_path TEXT,
                    framework TEXT,
                    primary_language TEXT,
                    indexed_at REAL,
                    file_count INTEGER,
                    total_size_bytes INTEGER
                );

                CREATE TABLE IF NOT EXISTS files (
                    workspace_id TEXT,
                    rel_path TEXT,
                    abs_path TEXT,
                    extension TEXT,
                    language TEXT,
                    size_bytes INTEGER,
                    mtime REAL,
                    content_hash TEXT,
                    parse_status TEXT,
                    indexed_at REAL,
                    PRIMARY KEY(workspace_id, rel_path)
                );

                CREATE TABLE IF NOT EXISTS symbols (
                    workspace_id TEXT,
                    rel_path TEXT,
                    symbol_name TEXT,
                    symbol_type TEXT,
                    signature TEXT,
                    line_number INTEGER
                );

                CREATE TABLE IF NOT EXISTS imports (
                    workspace_id TEXT,
                    rel_path TEXT,
                    imported_module TEXT,
                    imported_symbol TEXT,
                    is_local INTEGER,
                    resolved_rel_path TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_files_ws ON files(workspace_id);
                CREATE INDEX IF NOT EXISTS idx_symbols_ws ON symbols(workspace_id, rel_path);
                CREATE INDEX IF NOT EXISTS idx_imports_ws ON imports(workspace_id, rel_path);
            """)

    def reset_store(self):
        """Safely resets/quarantines corrupted database and re-initializes clean schema."""
        try:
            p = Path(self.db_path)
            if p.exists():
                bak = p.parent / f"{p.name}.corrupt_{int(time.time() * 1000)}"
                try:
                    p.rename(bak)
                except Exception:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass

            # Drop any lingering corrupted tables to allow fresh table creation
            try:
                with self._get_conn() as conn:
                    for tbl in ["files", "symbols", "imports", "workspaces"]:
                        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception:
                pass
        except Exception as e:
            logger.error("WorkspaceIndexStore: error resetting store: {}", e)
        self._create_tables()

    def _init_db(self):
        try:
            self._create_tables()
        except sqlite3.DatabaseError as e:
            logger.warning("WorkspaceIndexStore: detected corrupt database ({}). Resetting and initializing clean schema...", e)
            self.reset_store()


class WorkspaceIndexer:
    """
    Coordinates workspace discovery, parsing, and incremental change detection.
    """

    def __init__(self, store: Optional[WorkspaceIndexStore] = None, enabled: bool = WORKSPACE_INTELLIGENCE_ENABLED):
        self.store = store or WorkspaceIndexStore()
        self.enabled = enabled
        self._full_scans_count: int = 0
        self._incremental_updates_count: int = 0

    @property
    def full_scans_count(self) -> int:
        return self._full_scans_count

    @property
    def incremental_updates_count(self) -> int:
        return self._incremental_updates_count

    def _should_ignore(self, path: Path) -> bool:
        for pattern in IGNORE_PATTERNS:
            if fnmatch.fnmatch(path.name, pattern) or path.name == pattern:
                return True
        return False

    def _detect_language(self, ext: str) -> str:
        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".jsx": "React/JSX", ".tsx": "React/TSX", ".go": "Go",
            ".rs": "Rust", ".java": "Java", ".cpp": "C++", ".c": "C",
            ".html": "HTML", ".css": "CSS", ".json": "JSON", ".toml": "TOML",
            ".yaml": "YAML", ".yml": "YAML", ".md": "Markdown", ".sh": "Shell"
        }
        return lang_map.get(ext.lower(), "Unknown")

    def _calculate_hash(self, path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def parse_python_file(self, content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract classes, functions, and imports from Python source using AST."""
        symbols = []
        imports = []
        try:
            tree = ast.parse(content)
        except Exception:
            return symbols, imports

        for node in ast.walk(tree):
            # Symbols: Classes
            if isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "type": "class",
                    "signature": f"class {node.name}",
                    "line": getattr(node, "lineno", 0)
                })
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append({
                            "name": f"{node.name}.{item.name}",
                            "type": "method",
                            "signature": f"def {item.name}(...)",
                            "line": getattr(item, "lineno", 0)
                        })

            # Symbols: Functions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top level only
                symbols.append({
                    "name": node.name,
                    "type": "function",
                    "signature": f"def {node.name}(...)",
                    "line": getattr(node, "lineno", 0)
                })

            # Imports: import X
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "module": alias.name,
                        "symbol": "",
                        "is_local": 0
                    })

            # Imports: from X import Y
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append({
                        "module": mod,
                        "symbol": alias.name,
                        "is_local": 1 if node.level > 0 else 0
                    })

        return symbols, imports

    def parse_js_ts_file(self, content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract functions, classes, and imports from JS/TS source using regex."""
        symbols = []
        imports = []

        # Classes
        for m in re.finditer(r"class\s+([A-Za-z0-9_$]+)", content):
            symbols.append({"name": m.group(1), "type": "class", "signature": f"class {m.group(1)}", "line": 0})

        # Functions
        for m in re.finditer(r"(?:function\s+([A-Za-z0-9_$]+)|const\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)", content):
            name = m.group(1) or m.group(2)
            if name:
                symbols.append({"name": name, "type": "function", "signature": f"function {name}()", "line": 0})

        # Imports: import ... from '...'
        for m in re.finditer(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", content):
            mod = m.group(1)
            imports.append({"module": mod, "symbol": "", "is_local": 1 if mod.startswith(".") else 0})

        return symbols, imports

    def parse_file(self, abs_path: Path, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        """Parse source code for symbols and imports."""
        if abs_path.stat().st_size > MAX_PARSE_FILE_SIZE:
            return [], [], "SKIPPED_TOO_LARGE"

        ext = abs_path.suffix.lower()
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return [], [], f"READ_ERROR: {e}"

        if ext == ".py":
            symbols, imports = self.parse_python_file(content, rel_path)
            return symbols, imports, "PARSED"
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            symbols, imports = self.parse_js_ts_file(content, rel_path)
            return symbols, imports, "PARSED"

        return [], [], "NO_PARSER"

    def index_workspace(self, root_path: Path | str, force_rebuild: bool = False) -> Dict[str, Any]:
        """Initial full scan or rebuild of the workspace."""
        root = Path(root_path).resolve()
        ws_id = str(root)
        start_time = time.perf_counter()
        self._full_scans_count += 1

        logger.info("WorkspaceIndexer: full indexing on '{}' (force_rebuild={})", root, force_rebuild)

        files_to_index: List[FileIndexRecord] = []
        total_size = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not self._should_ignore(Path(dirpath) / d)]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if self._should_ignore(fpath):
                    continue

                try:
                    stat = fpath.stat()
                    rel_p = fpath.relative_to(root).as_posix()
                    ext = fpath.suffix.lower()
                    lang = self._detect_language(ext)
                    c_hash = self._calculate_hash(fpath)
                    symbols, imports, status = self.parse_file(fpath, rel_p)

                    files_to_index.append(FileIndexRecord(
                        rel_path=rel_p,
                        abs_path=str(fpath),
                        extension=ext,
                        language=lang,
                        size_bytes=stat.st_size,
                        mtime=stat.st_mtime,
                        content_hash=c_hash,
                        parse_status=status,
                        symbols=symbols,
                        imports=imports
                    ))
                    total_size += stat.st_size
                except Exception as e:
                    logger.debug("WorkspaceIndexer: skip file {}: {}", fpath, e)

        # Write to SQLite in transaction
        with self.store._get_conn() as conn:
            conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", (ws_id,))
            conn.execute("DELETE FROM files WHERE workspace_id = ?", (ws_id,))
            conn.execute("DELETE FROM symbols WHERE workspace_id = ?", (ws_id,))
            conn.execute("DELETE FROM imports WHERE workspace_id = ?", (ws_id,))

            conn.execute("""
                INSERT INTO workspaces (workspace_id, root_path, framework, primary_language, indexed_at, file_count, total_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ws_id, str(root), "Python/General", "Python", time.time(), len(files_to_index), total_size))

            for f in files_to_index:
                conn.execute("""
                    INSERT INTO files (workspace_id, rel_path, abs_path, extension, language, size_bytes, mtime, content_hash, parse_status, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ws_id, f.rel_path, f.abs_path, f.extension, f.language, f.size_bytes, f.mtime, f.content_hash, f.parse_status, time.time()))

                for s in f.symbols:
                    conn.execute("""
                        INSERT INTO symbols (workspace_id, rel_path, symbol_name, symbol_type, signature, line_number)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (ws_id, f.rel_path, s["name"], s["type"], s["signature"], s["line"]))

                for imp in f.imports:
                    conn.execute("""
                        INSERT INTO imports (workspace_id, rel_path, imported_module, imported_symbol, is_local, resolved_rel_path)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (ws_id, f.rel_path, imp["module"], imp["symbol"], imp["is_local"], ""))

        dur = (time.perf_counter() - start_time) * 1000.0
        logger.info("WorkspaceIndexer: indexed {} files ({:.1f} KB) in {:.2f}ms", len(files_to_index), total_size / 1024.0, dur)

        return {
            "workspace_id": ws_id,
            "files_indexed": len(files_to_index),
            "total_size_bytes": total_size,
            "duration_ms": dur,
            "records": files_to_index,
        }

    def update_workspace(self, root_path: Path | str) -> IncrementalUpdateReport:
        """Fast incremental update: re-indexes ONLY added, modified, or deleted files."""
        root = Path(root_path).resolve()
        ws_id = str(root)
        start_time = time.perf_counter()
        self._incremental_updates_count += 1

        try:
            # Check if workspace exists in DB
            with self.store._get_conn() as conn:
                ws_row = conn.execute("SELECT workspace_id FROM workspaces WHERE workspace_id = ?", (ws_id,)).fetchone()
                if not ws_row:
                    res_init = self.index_workspace(root)
                    return IncrementalUpdateReport(
                        workspace_root=str(root),
                        files_discovered=res_init.get("files_indexed", 0),
                        files_added=res_init.get("files_indexed", 0),
                        asts_rebuilt=res_init.get("files_indexed", 0),
                        duration_ms=(time.perf_counter() - start_time) * 1000.0
                    )

                # Load existing file metadata map: rel_path -> (mtime, size, content_hash)
                existing_files = {
                    r["rel_path"]: (r["mtime"], r["size_bytes"], r["content_hash"])
                    for r in conn.execute("SELECT rel_path, mtime, size_bytes, content_hash FROM files WHERE workspace_id = ?", (ws_id,)).fetchall()
                }
        except sqlite3.DatabaseError as e:
            logger.warning("WorkspaceIndexer.update_workspace: Database corruption detected ({}). Triggering safe recovery...", e)
            self.store.reset_store()
            res_rec = self.index_workspace(root, force_rebuild=True)
            return IncrementalUpdateReport(
                workspace_root=str(root),
                files_discovered=res_rec.get("files_indexed", 0),
                files_added=res_rec.get("files_indexed", 0),
                asts_rebuilt=res_rec.get("files_indexed", 0),
                duration_ms=(time.perf_counter() - start_time) * 1000.0
            )

        disk_files: Set[str] = set()
        added_files: List[FileIndexRecord] = []
        modified_files: List[FileIndexRecord] = []
        unchanged_count = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not self._should_ignore(Path(dirpath) / d)]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if self._should_ignore(fpath):
                    continue

                rel_p = fpath.relative_to(root).as_posix()
                disk_files.add(rel_p)

                try:
                    stat = fpath.stat()
                    if rel_p not in existing_files:
                        # NEW file
                        c_hash = self._calculate_hash(fpath)
                        syms, imps, st = self.parse_file(fpath, rel_p)
                        added_files.append(FileIndexRecord(
                            rel_path=rel_p, abs_path=str(fpath), extension=fpath.suffix.lower(),
                            language=self._detect_language(fpath.suffix), size_bytes=stat.st_size,
                            mtime=stat.st_mtime, content_hash=c_hash, parse_status=st, symbols=syms, imports=imps
                        ))
                    else:
                        old_mtime, old_size, old_hash = existing_files[rel_p]
                        if stat.st_mtime != old_mtime or stat.st_size != old_size:
                            c_hash = self._calculate_hash(fpath)
                            if c_hash != old_hash:
                                # MODIFIED file
                                syms, imps, st = self.parse_file(fpath, rel_p)
                                modified_files.append(FileIndexRecord(
                                    rel_path=rel_p, abs_path=str(fpath), extension=fpath.suffix.lower(),
                                    language=self._detect_language(fpath.suffix), size_bytes=stat.st_size,
                                    mtime=stat.st_mtime, content_hash=c_hash, parse_status=st, symbols=syms, imports=imps
                                ))
                            else:
                                unchanged_count += 1
                        else:
                            unchanged_count += 1
                except Exception:
                    continue

        deleted_files = set(existing_files.keys()) - disk_files

        # Apply DB updates in transaction
        if added_files or modified_files or deleted_files:
            with self.store._get_conn() as conn:
                for del_p in deleted_files:
                    conn.execute("DELETE FROM files WHERE workspace_id = ? AND rel_path = ?", (ws_id, del_p))
                    conn.execute("DELETE FROM symbols WHERE workspace_id = ? AND rel_path = ?", (ws_id, del_p))
                    conn.execute("DELETE FROM imports WHERE workspace_id = ? AND rel_path = ?", (ws_id, del_p))

                for f in modified_files:
                    conn.execute("DELETE FROM symbols WHERE workspace_id = ? AND rel_path = ?", (ws_id, f.rel_path))
                    conn.execute("DELETE FROM imports WHERE workspace_id = ? AND rel_path = ?", (ws_id, f.rel_path))
                    conn.execute("""
                        UPDATE files SET mtime = ?, size_bytes = ?, content_hash = ?, parse_status = ?, indexed_at = ?
                        WHERE workspace_id = ? AND rel_path = ?
                    """, (f.mtime, f.size_bytes, f.content_hash, f.parse_status, time.time(), ws_id, f.rel_path))
                    for s in f.symbols:
                        conn.execute("INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?)", (ws_id, f.rel_path, s["name"], s["type"], s["signature"], s["line"]))
                    for imp in f.imports:
                        conn.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?)", (ws_id, f.rel_path, imp["module"], imp["symbol"], imp["is_local"], ""))

                for f in added_files:
                    conn.execute("""
                        INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (ws_id, f.rel_path, f.abs_path, f.extension, f.language, f.size_bytes, f.mtime, f.content_hash, f.parse_status, time.time()))
                    for s in f.symbols:
                        conn.execute("INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?)", (ws_id, f.rel_path, s["name"], s["type"], s["signature"], s["line"]))
                    for imp in f.imports:
                        conn.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?)", (ws_id, f.rel_path, imp["module"], imp["symbol"], imp["is_local"], ""))

        dur = (time.perf_counter() - start_time) * 1000.0
        logger.debug(
            "WorkspaceIndexer.update: +{} ~{} -{} ={} ({:.2f}ms)",
            len(added_files), len(modified_files), len(deleted_files), unchanged_count, dur
        )

        asts_rebuilt = sum(1 for f in (added_files + modified_files) if f.parse_status == "PARSED")
        symbols_rebuilt = sum(len(f.symbols) for f in (added_files + modified_files))
        imports_rebuilt = sum(len(f.imports) for f in (added_files + modified_files))

        return IncrementalUpdateReport(
            workspace_root=str(root),
            files_discovered=len(disk_files),
            files_added=len(added_files),
            files_modified=len(modified_files),
            files_deleted=len(deleted_files),
            files_unchanged=unchanged_count,
            duration_ms=dur,
            added_records=added_files,
            modified_records=modified_files,
            deleted_paths=deleted_files,
            asts_rebuilt=asts_rebuilt,
            symbols_rebuilt=symbols_rebuilt,
            imports_rebuilt=imports_rebuilt,
        )


# Global singleton
workspace_indexer = WorkspaceIndexer()
