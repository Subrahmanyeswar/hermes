# Documentation Audit & Reconciliation: OPERATOR_GUIDE.md

**Date**: 2026-10-12  
**Audited Document**: [`OPERATOR_GUIDE.md`](file:///c:/Users/SUBBU/Downloads/hermes/OPERATOR_GUIDE.md)  
**Target Release**: HERMES v1.0.0-rc1  

---

## 1. Audit Scope & Findings

| Item / Section | Current Documentation | Actual Implementation / Test Reality | Audit Finding & Recommendation |
| :--- | :--- | :--- | :--- |
| **Title & Version** | `# HERMES v4.0 — Operator Guide & Launch Manual` | Fastapi server health endpoint reports `version: "1.0.0-rc1"` | Document title reflects legacy internal phase nomenclature (`v4.0`); clarify release-candidate version `v1.0.0-rc1`. |
| **GUI Launch / Stop Commands** | Section 7 lists `.\scripts\launch_gui.ps1` and `.\scripts\stop_gui.ps1` | `core.server.launcher` handles launch/stop safely on port 8765 | **Accurate & Verified**. Commands match implemented PowerShell & Python launcher interfaces. |
| **Model Stack** | T1: `z-ai/glm-5.3-flash`, T2: `gpt-oss:120b-cloud`, T3: `nemotron-3-ultra:cloud` | Matches `config/model_config.py` and live health endpoint | **Accurate & Verified**. All 3 tiers confirmed live and responsive. |
| **Provider Credentials** | T1 requires `NVIDIA_API_KEY`. T2/T3 require local daemon `http://127.0.0.1:11434` running cloud models. | `models/nvidia_client.py` uses `NVIDIA_API_KEY` (or `TIER1_BASE_URL`). `models/ollama_client.py` connects to local Ollama. | **Clarified**: Explicitly explain that T2/T3 communicate via the local Ollama server running cloud models (`ollama serve`), while T1 connects directly to NVIDIA NIM API. |
| **Observation Timeout vs Execution Deadline** | Mentions UI latency and model timeouts | AgentLoop enforces bounded mission execution deadlines (default 180s/300s); UI has independent polling | **Clarified**: Distinguish browser SSE stream timeouts from runtime execution budgets and deadlines. |
| **Health Endpoint Semantics** | Mentions `/api/health` | `/api/health` verifies backend process readiness and configured model stack, but is not an end-to-end ping of remote models | **Clarified**: State explicitly that `/api/health` proves local server health, not external model quota availability. |
| **Regression Commands** | Lists Phase 4 qualification test files (11 files, 132 tests) | Stage 0–7.2 canonical acceptance suite is 13 files, 85 tests | **Updated**: Add exact command to run the 13 canonical Stage 0–7.2 acceptance test suites (`test_runtime_reliability_gate.py` through `test_stage7_2_concurrent_isolation.py`). |

---

## 2. Reconciled Actions

1. Added notes clarifying `v1.0.0-rc1` release candidate nomenclature alongside internal development labels.
2. Verified exact environment variable specifications (`NVIDIA_API_KEY`) and local Ollama daemon requirement for T2/T3 (`gpt-oss:120b-cloud` and `nemotron-3-ultra:cloud`).
3. Documented distinction between server health (`/api/health`) and external provider reachability.
4. Documented canonical Stage 0–7.2 regression command in addition to legacy benchmark suites.
