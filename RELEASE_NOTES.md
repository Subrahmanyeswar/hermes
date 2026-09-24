# HERMES Release Notes — v1.0.0-rc1 (Release Candidate 1)

**Release Date**: September 24, 2026  
**Status**: **FROZEN CORE RUNTIME**  
**Qualification**: **10/10 Live Cloud Missions Passed (100.0%)**

---

## 1. Overview & Release Highlights

HERMES v1.0.0-rc1 marks the formal feature freeze and stabilization of the HERMES autonomous software engineering runtime. This release candidate establishes complete architectural separation across three specialized model tiers, deterministic multi-level verification, asynchronous background memory synthesis, and strict sandbox isolation.

### Key Milestones in v1.0.0-rc1:
- **100% Live Cloud Qualification**: Passed 10/10 diverse software engineering missions using live cloud inference (24 model calls) with zero mocks, zero synthetics, and zero cached responses.
- **Native Tool Calling**: Fully native OpenAI-compatible function calling via NVIDIA NIM SSE streaming for Tier 1.
- **Progressive Verification Gate**: Three-level verification hierarchy (Level 0 Deterministic AST -> Level 1 Subprocess Pytest & API Contract Analysis -> Level 2 Semantic Review).
- **Post-Plan Tool Surface Isolation**: Enforces physical artifact creation by restricting implementation phases to file-writing tools, preventing recursive inspection loops.
- **Fail-Closed Security**: Complete sandbox isolation, path traversal interception, credential exfiltration shields, and dangerous shell command filters.
- **Memory Evolution**: Non-blocking background fact extraction that persists project knowledge to `MEMORY.md` without impacting pipeline latency.

---

## 2. Locked Model Stack Specification

The model architecture is permanently locked for the v1.0.0 line:

- **Tier 1 (Primary Reasoning & Generation)**:
  - **Provider**: NVIDIA NIM
  - **Model ID**: `z-ai/glm-5.3-flash`
  - **Endpoint**: `https://integrate.api.nvidia.com/v1`
  - **Protocol**: HTTP/1.1 SSE Streaming with delta aggregation
- **Tier 2 (Semantic Verification & Quality)**:
  - **Provider**: Ollama Cloud
  - **Model ID**: `gpt-oss:120b-cloud`
  - **Endpoint**: `http://localhost:11434/api/generate`
- **Tier 3 (Arbitration & Escalation)**:
  - **Provider**: Ollama Cloud
  - **Model ID**: `nemotron-3-ultra:cloud`
  - **Endpoint**: `http://localhost:11434/api/generate`

---

## 3. Migration Notes (From Pre-Release Prototypes)

1. **Environment Configuration**:
   - `OPENROUTER_API_KEY` is no longer primary.
   - `NVIDIA_API_KEY` is mandatory for Tier 1 inference.
   - Ollama must be running locally (`ollama serve`) to proxy Tier 2 and Tier 3 cloud models.
2. **Model Call Telemetry**:
   - All model calls now emit canonical `MODEL_START`, `MODEL_COMPLETE`, and `MODEL_FAILED` events with high-resolution latency and token metrics.
3. **Completion Contract**:
   - Missions cannot report `success=True` unless all requested artifacts exist on disk with non-zero size and pass all structural/AST/runtime tests.
4. **Timeouts**:
   - `MODEL_TIMEOUT_SECONDS` is standardized to `360s` to accommodate cloud reasoning TTFT variations.

---

## 4. Test & Verification Coverage

- **Total Test Suite**: 213 unit, security, integration, and failure tests passing.
- **Security Tests**: 68/68 passed (100% pass on path traversal, dangerous commands, credentials).
- **TUI Tests**: 40/40 passed (all interactive components and lifecycle events verified).
- **Failure & Chaos Tests**: 59/59 passed (timeout, disconnection, cancellation, and crash resumption).
- **Closure Regression Tests**: 6/6 passed (large HTML parsing, API contracts, completion enforcement).

---

## 5. Known Limitations & Operational Guidance

- **NVIDIA NIM Shared Endpoint Latency**: Remote inference TTFT on the shared NVIDIA NIM endpoint varies under global demand (typically 30s–60s, occasionally up to 120s under peak load). This is remote provider latency and does not reflect local HERMES engine overhead (~67 ms).
- **Ollama Cloud Connectivity**: Tier 2 and Tier 3 require an active internet connection through the local Ollama gateway. If the gateway is unreachable, HERMES gracefully falls back to local deterministic verification gates.
