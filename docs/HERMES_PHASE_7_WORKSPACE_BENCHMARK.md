# HERMES Phase 7 — Workspace Intelligence Benchmark Report
===========================================================

**Environment:** NVIDIA RTX 3050 Laptop GPU (6GB VRAM) / Windows (x86_64)  
**Date:** September 1, 2026  
**Status:** VALIDATED  

---

## 1. Indexing & Incremental Update Benchmarks (50-File Repository)

| Operation | Files Processed | Measured Latency | Speedup vs Full Scan | Notes |
|---|---|---|---|---|
| **Initial Full Index** | 50 files (full AST parse + DB write) | **759.30 ms** | Baseline (1.0x) | Full structural discovery |
| **Unchanged Turn Check** | 50 files (mtime + size check) | **8.66 ms** | **87.7x Speedup** | 0 files reparsed |
| **1-File Modified Update**| 1 file modified (SHA256 re-parse) | **28.13 ms** | **27.0x Speedup** | Reparses only modified file |
| **Multi-Signal Retrieval**| Query matching across 50 files | **4.67 ms** | N/A | High precision & test pairing |

---

## 2. Accuracy & Test Pairing Metrics

| Query Target | Retrieved Files | Target Found? | Test File Paired? | Latency |
|---|---|---|---|---|
| `"Fix authentication login"` | `module_0/auth.py`, `module_3/test_auth.py` | **YES (Score 23.0)** | **YES (`test_auth.py`)** | **4.67 ms** |
| `"Database connection issue"`| `module_2/database.py` | **YES (Score 19.0)** | N/A | **3.82 ms** |
| `"User model definition"` | `module_1/models.py` | **YES (Score 18.5)** | N/A | **3.91 ms** |
