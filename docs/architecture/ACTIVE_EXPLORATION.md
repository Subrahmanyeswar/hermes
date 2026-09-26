# HERMES 2.x — Active Exploration & Just-in-Time Context Retrieval

**Status:** Authoritative Runtime Contract  
**Version:** HERMES 2.x (`Prompt 6`)  
**Anchor Baseline:** `3ce8f81` (`Prompt 2`)  
**State Architecture Baseline:** `712a84b` (`Prompt 3`)  
**Agent Loop Baseline:** `d68ecd7` (`Prompt 4`)  
**Tool Platform Baseline:** `1080eb2` (`Prompt 5`)  
**Reference Tag:** `v1.0.0-rc3` (`da30412b...`)  

---

## 1. Executive Mission & Philosophy

Prompt 6 transforms repository interaction from passive, brute-force context dumping into **Active, Progressive Exploration**. 

In naive agent architectures, agents attempt to solve coding problems by dumping thousands of lines of code into model context or reading whole repositories up front. This produces three catastrophic failures:
1. **Context Window Exhaustion:** Unrelated code dilutes model attention, causing reasoning degradation and missed instructions.
2. **High Latency & Inference Cost:** Ingesting 50,000 tokens per turn dramatically slows iteration speed.
3. **Stale Assumptions:** Models reason about code they fetched early in the conversation rather than verifying current state on disk.

HERMES 2.x enforces the principle:
> **Retrieve information progressively, inspect only the needed regions, and modify code surgically.**

```
                     ┌───────────────────────────────┐
                     │          Mission Goal         │
                     └───────────────┬───────────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │     1. Workspace Discovery    │
                     │  (Manifests, Roots, Language) │
                     └───────────────┬───────────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │    2. Structural Exploration  │
                     │  search.glob ("**/*.py", etc) │
                     └───────────────┬───────────────┘
                                     │ Likely files located
                                     ▼
                     ┌───────────────────────────────┐
                     │     3. Content / Symbol Search│
                     │   search.grep (Pattern/Regex) │
                     └───────────────┬───────────────┘
                                     │ Line numbers identified
                                     ▼
                     ┌───────────────────────────────┐
                     │     4. Targeted Inspection    │
                     │   fs.read(start_line, end_line)│
                     └───────────────┬───────────────┘
                                     │ Exact target understood
                                     ▼
                     ┌───────────────────────────────┐
                     │      5. Surgical Mutation     │
                     │   fs.edit(old_string, new_string)
                     └───────────────┬───────────────┘
                                     │ Minimal diff applied
                                     ▼
                     ┌───────────────────────────────┐
                     │   6. Verification & Evidence  │
                     │  (Syntax, Tests, Observations)│
                     └───────────────────────────────┘
```

---

## 2. Workspace Discovery (`WorkspaceDiscoveryService`)

To eliminate redundant discovery steps at the start of every turn, HERMES maintains a lightweight [`WorkspaceProfile`](file:///c:/Users/SUBBU/Downloads/hermes/tools/platform/workspace_discovery.py):
- **Evidence-Based Detection:** Identifies manifests (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`), source directories (`src/`, `lib/`, `core/`), test directories (`tests/`), and documentation roots.
- **Project Language Recognition:** Probes filesystem signals without guesswork (e.g. `pyproject.toml` -> Python, `tsconfig.json` -> TypeScript).
- **Cache Invalidation:** Cached with configurable TTL and invalidation triggers, ensuring the cache is never mistaken for authoritative filesystem truth.

---

## 3. Structural Discovery (`search.glob`)

`search.glob` provides fast structural mapping without reading file contents:
- **Noise Directory Filtering:** Automatically prunes standard noise directories (`.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `.tox`, `dist`, `build`).
- **Bounded Output:** Enforces `max_results` (default: 50) with explicit truncation banners (`[Truncated: maximum of 50 results returned. Narrow pattern to inspect further.]`).
- **Deterministic Ordering:** Returns sorted paths relative to workspace root.

---

## 4. Content & Symbol Search (`search.grep`)

`search.grep` enables targeted symbol and text discovery across workspace files:
- **Line-Addressable Format:** Returns compact results in standard `file:line: match` format, with optional indented context lines before and after.
- **Regex Validation (`GREP_INVALID_PATTERN`):** Validates regular expressions prior to search. If malformed regex is detected (e.g. unclosed brackets), a structured error is returned with actionable remediation advice rather than crashing the loop.
- **Cross-Platform Compatibility:** Operates consistently on Windows, Linux, and macOS without requiring native POSIX shell tools.
- **File Size Bounding:** Automatically skips binary files and oversized files (> 2 MB) to prevent search stalls.

---

## 5. Targeted Line Inspection (`fs.read`)

`fs.read` is designed for precision inspection:
- **1-Based Line Addressability:** Reads specific bounded slices via `start_line` (or `offset`) and `end_line` (or `max_lines` / `limit`).
- **Line Numbering:** Formats lines clearly with right-aligned line numbers:
  ```
  File: src/auth.py
  Lines: 120-125 of 450

   120 | def authenticate(user):
   121 |     if not user:
   122 |         return None
   123 |     token = generate_token(user.id)
   124 |     return token
  ```
- **Large-File Safety Policy:** If an agent requests a large file (> 500 lines) without specifying a range, `fs.read` defaults to returning the first 200 lines, with explicit truncation metadata and next offset guidance (`Use offset=201 to inspect subsequent lines`).
- **Workspace Close Matches:** If a requested file does not exist, `fs.read` searches the workspace and returns real suggestions (e.g., `Did you mean src/auth_service.py?`).

---

## 6. Distinction: Cache vs. Memory

HERMES 2.x establishes a clear architectural distinction between caching and memory:
- **Filesystem Cache (`FileIdentityCache`, `WorkspaceDiscoveryService`):** Ephemeral, thread-safe runtime caches used solely to optimize I/O and detect concurrency races. Never treated as durable truth.
- **Agent Memory (Prompt 8/9):** Persistent, user-scoped facts and guidelines stored across sessions.

---

## 7. Performance Benchmarks

Measured on the development environment across 20 iterations:
- **`fs.read` Small File (Lines 1-5):** `p50: 1.05 ms`, `p95: 2.11 ms`
- **`fs.read` Large File (Lines 500-550):** `p50: 1.20 ms`, `p95: 2.18 ms`
- **`search.glob` (50 files):** `p50: 2.68 ms`, `p95: 3.38 ms`
- **`search.grep` (Regex search across project):** `p50: 11.31 ms`, `p95: 46.41 ms`
- **Workspace Discovery:** `p50: 0.86 ms`, `p95: 1.01 ms`
