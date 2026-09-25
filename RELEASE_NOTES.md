# HERMES Release Notes — v1.0.0-rc2 (Release Candidate 2)

**Release Date**: September 25, 2026  
**Base Commit**: `68d3f9454bae3006c975ac0817928cd52ae805af`  
**Status**: **PRODUCTION RELEASE CANDIDATE 2**  
**Historical RC1 Release**: `v1.0.0-rc1` remains permanently pinned to commit `b36ddb31eee93ea00b10d5f09c98e2c91fb501ba`.

---

## 1. Overview & RC2 Highlights

HERMES v1.0.0-rc2 delivers critical runtime correctness, telemetry attribution, live stall prevention, and stage progression enhancements discovered during extensive live-cloud stress testing:

- **Live Repeated-Read Stall Closure**: Implemented workspace snapshotting and a state-aware no-progress detector in `MissionRunner`. When an implementation task encounters repeated identical read-only inspections (`list_directory`, `read_file`) without modifying workspace state, HERMES publishes an `agent_stall_detected` event and injects deterministic guidance enforcing immediate `write_file` invocation. Tested and verified on the historical complex multi-page website prompt without looping.
- **Request-Scoped Telemetry Attribution**: Propagated `request_id`, `mission_id`, `task_id`, `stage`, and `execution_mode` explicitly through all inference paths (`Orchestrator._generate_t1()`, `Tier2Verifier.verify()`, `NvidiaClient`, and `OllamaClient`). Removed global first-active-request lookup fallbacks to guarantee 100% request isolation and zero cross-request contamination. All production runs strictly report `execution_mode: "production"`.
- **Single-File Inspection Optimization**: Optimized `MissionPlanner.plan_async()` to avoid injecting redundant workspace inspection tasks for self-contained single-file creations and empty workspaces, reducing trivial task model invocation from 2 calls to exactly 1 call.
- **Dynamic TUI Stage Progression**: Bound real-time `stage_start` and `stage_end` event propagation in `HermesApp`, `ChatPanel`, and `StatusBar`, ensuring the interface dynamically steps through stages 1 to 12 rather than freezing on Stage 1 (Input Sanitization). Formatted T1 status badge as `GLM-5.3-Flash`.
- **Accurate Failure Semantics (`VERIFICATION_INTERRUPTED`)**: When implementation artifacts are physically created on disk but subsequent remote semantic verification is interrupted by cloud provider network disconnections, HERMES preserves the artifact on disk and returns an explicit `VERIFICATION_INTERRUPTED` status instead of conflating physical existence with full semantic verification or destroying the artifact.

---

## 2. Canonical RC2 Qualification Test Suite

To ensure reproducible release accounting, the authoritative non-cloud test suite was executed:
```bash
uv run pytest tests/test_closure_regressions.py tests/test_model_migration.py tests/test_write_files_batch.py tests/test_tui.py tests/test_security.py tests/test_gate15_7_security.py tests/test_gate15_2_chaos.py tests/test_failure_modes.py
```

### Authoritative Suite Breakdown:
- `tests/test_closure_regressions.py`: 18/18 passed (all 8 RC2 closure requirements validated)
- `tests/test_model_migration.py`: 14/14 passed
- `tests/test_write_files_batch.py`: 16/16 passed
- `tests/test_tui.py`: 40/40 passed
- `tests/test_security.py`: 28/28 passed
- `tests/test_gate15_7_security.py`: 24/24 passed
- `tests/test_gate15_2_chaos.py`: 23/23 passed
- `tests/test_failure_modes.py`: 10/10 passed

**Total Canonical Count**: **173 passed in 42.56s (100% pass rate, 0 failed, 0 skipped)**  
*(Note on historical counts: Earlier RC1 draft notes referenced 213 tests across deprecated prototype milestone gates from earlier local-model iterations. The canonical reproducible test count for the frozen cloud architecture in RC2 is 173).*

---

## 3. Locked Model Stack Specification

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

# Historical Release Notes — v1.0.0-rc1

**Release Date**: September 24, 2026  
**Commit**: `b36ddb31eee93ea00b10d5f09c98e2c91fb501ba`  
**Status**: **PREVIOUS RELEASE CANDIDATE (PERMANENTLY PINNED)**  
**Qualification**: **10/10 Live Cloud Missions Passed (100.0%)**

### Key Milestones in v1.0.0-rc1:
- **100% Live Cloud Qualification**: Passed 10/10 diverse software engineering missions using live cloud inference (24 model calls) with zero mocks, zero synthetics, and zero cached responses.
- **Native Tool Calling**: Fully native OpenAI-compatible function calling via NVIDIA NIM SSE streaming for Tier 1.
- **Progressive Verification Gate**: Three-level verification hierarchy (Level 0 Deterministic AST -> Level 1 Subprocess Pytest & API Contract Analysis -> Level 2 Semantic Review).
- **Post-Plan Tool Surface Isolation**: Enforces physical artifact creation by restricting implementation phases to file-writing tools.
- **Fail-Closed Security**: Complete sandbox isolation, path traversal interception, credential exfiltration shields, and dangerous shell command filters.
- **Memory Evolution**: Non-blocking background fact extraction that persists project knowledge to `MEMORY.md` without impacting pipeline latency.
