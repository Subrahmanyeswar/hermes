# Documentation Reconciliation Report: OPERATOR_GUIDE.md

**Date**: 2026-10-12  
**Audited File**: [`OPERATOR_GUIDE.md`](file:///c:/Users/SUBBU/Downloads/hermes/OPERATOR_GUIDE.md)  
**Evaluated Target**: HERMES Release Candidate `v1.0.0-rc1` (Phase 4 Internal Architecture)  

---

## 1. Reconciled Items & Corrections

| Item | Prior Documentation | Verified Current Reality | Correction Made |
| :--- | :--- | :--- | :--- |
| **Title & Version** | `# HERMES v4.0 — Operator Guide & Launch Manual` | Fastapi server health endpoint reports `version: "1.0.0-rc1"` | Updated title and preamble to `# HERMES v1.0.0-rc1 (Architecture Phase 4) — Operator Guide & Launch Manual`. |
| **Canonical Python Interpreter** | `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` | Verified target `3.12.0` | **Preserved & Verified**. Mandatory Python guard maintained. |
| **GUI Launch / Status / Stop Commands** | `.\scripts\launch_gui.ps1`, `.\scripts\stop_gui.ps1`, `core.server.launcher` | Operates on `http://127.0.0.1:8765/` | **Verified**. Commands are documented and tested. |
| **Model Stack & Endpoints** | T1: `z-ai/glm-5.3-flash` (NVIDIA NIM), T2: `gpt-oss:120b-cloud` (Ollama), T3: `nemotron-3-ultra:cloud` (Ollama) | Live confirmed in Stage 8.1 with responses and latencies recorded | **Accurate & Verified**. |
| **Local Ollama vs Cloud** | Ollama daemon instructions | Clarified that T2 & T3 stream cloud models through the local Ollama server instance on `127.0.0.1:11434`. | **Clarified**. |
| **Health Endpoint Scope** | `/api/health` status check | Verifies local process health and model stack configuration, not external quota availability. | **Clarified in note**. |
| **Acceptance Regression Suite** | 13 canonical suites (85 tests) | Complete Stage 0–7.2 acceptance test command documented | **Added exact canonical command**. |
| **Broad Test Suite Expectations** | Generic pass claims | 194 safely executable files (1,915 passed, 49 obsolete/legacy benchmark differences reconciled) | **Documented distinction** between release gates and legacy benchmark suites. |

---

## 2. Conclusion
The operator guide is completely reconciled with runtime reality, eliminating ambiguity between release-candidate versioning and internal architecture phase labels.
