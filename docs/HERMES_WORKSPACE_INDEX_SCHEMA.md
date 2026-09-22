# HERMES Workspace Index SQLite Schema
======================================

**Database:** `hermes_workspace_index.db`  
**Schema Version:** 1.0  
**Date:** September 1, 2026  

---

## 1. Table Definitions

### `workspaces`
Stores top-level metadata for indexed workspaces.
```sql
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,
    root_path TEXT,
    framework TEXT,
    primary_language TEXT,
    indexed_at REAL,
    file_count INTEGER,
    total_size_bytes INTEGER
);
```

### `files`
Tracks individual file metadata, timestamps, and SHA-256 content hashes.
```sql
CREATE TABLE files (
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
CREATE INDEX idx_files_ws ON files(workspace_id);
```

### `symbols`
Stores AST-extracted classes, methods, and functions.
```sql
CREATE TABLE symbols (
    workspace_id TEXT,
    rel_path TEXT,
    symbol_name TEXT,
    symbol_type TEXT,
    signature TEXT,
    line_number INTEGER
);
CREATE INDEX idx_symbols_ws ON symbols(workspace_id, rel_path);
```

### `imports`
Tracks import statements and internal module dependencies.
```sql
CREATE TABLE imports (
    workspace_id TEXT,
    rel_path TEXT,
    imported_module TEXT,
    imported_symbol TEXT,
    is_local INTEGER,
    resolved_rel_path TEXT
);
CREATE INDEX idx_imports_ws ON imports(workspace_id, rel_path);
```
