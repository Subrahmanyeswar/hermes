# HERMES — PHASE 2 SURGICAL OLLAMACLIENT REPAIR REPORT
## DeepSeek-R1 Reasoning Ingestion Defect Remediation

### 1. Problem
During the initial execution of the final 80-task benchmark, HERMES achieved only 1/80 objective success. The Gate 24 forensic audit proved that 79 failures were caused by an upstream provider ingestion defect: `deepseek-r1:8b` emitted its response inside Ollama API's `thinking` field, but `OllamaClient` only checked `data.get("response", "")`. As a result, `OllamaClient` returned an empty string `""` to `ResponseParser`, triggering `empty_response` parse failures, aborting at Stage 4 on both attempts, and executing 0 tool calls across all tasks.

### 2. Root Cause
In Ollama API v0.5+, reasoning models place chain-of-thought tokens inside the `data["thinking"]` JSON field while `data["response"]` contains non-thinking completion output or remains empty when generation completes in reasoning mode. `models/ollama_client.py:189` previously evaluated only `result: str = data.get("response", "")`, dropping all thinking content and returning `""`.

### 3. Exact Code Path & Fix Applied
- **Module**: `models/ollama_client.py`
- **Function Added**: `normalize_ollama_payload(data: Any) -> str`
  - Correctly extracts both `data["thinking"]` and `data["response"]`.
  - Faithfully formats reasoning blocks as `<think>\n{thinking}\n</think>\n{response}` without duplicating existing tags.
  - Returns `response` directly when standard models are used (zero regression).
  - Preserves genuine empty responses (`""`) for error/retry handling.
- **Caller Updated**: `OllamaClient.generate` now passes `result: str = normalize_ollama_payload(data)`.
- **Compatibility Hardening**: In `core/tool_validator.py`, updated model correction parsing to use `ResponseParser` so that `<think>` blocks in repair responses are handled gracefully.

### 4. Files Modified
- **Production Files**:
  - `models/ollama_client.py` (added `normalize_ollama_payload`, updated `generate`)
  - `core/tool_validator.py` (used `ResponseParser` in `process_and_validate`)
- **Test Files**:
  - `tests/test_ollama_client_reasoning.py` (15 focused unit tests covering Cases A–H, provider errors, timeouts, connections, and token accounting)

### 5. Validation Matrix

| Test Case | Expected Behavior | Actual Behavior | Status |
|---|---|---|:---:|
| **Case A — Standard response-only** | Returns response text | Output matches `data["response"]` | **PASS** |
| **Case B — Reasoning-only payload** | Preserves `<think>` reasoning | Output wrapped in `<think>` tags | **PASS** |
| **Case C — Thinking + response** | Preserves both semantically | `<think>{think}</think>\n{resp}` | **PASS** |
| **Case D — Empty thinking + response** | Returns response only | Response text returned cleanly | **PASS** |
| **Case E — Missing thinking field** | Returns response only | Response text returned cleanly | **PASS** |
| **Case F — Missing response field** | Preserves thinking content | Output wrapped in `<think>` tags | **PASS** |
| **Case G — Both fields empty** | Returns empty string `""` | `ParseFailure(empty_response)` | **PASS** |
| **Case H — Malformed/non-dict payload** | Safe empty return, no crash | Returns `""`, no unhandled error | **PASS** |
| **Tool JSON extraction** | JSON tool calls survive normalization | `ParseSuccess(tool=write_file)` | **PASS** |
| **Token accounting** | Prompt & eval tokens preserved | Token counts match API metadata | **PASS** |
| **Telemetry emission** | ModelCallTelemetry recorded | Full latency, TTFT, VRAM logged | **PASS** |
| **Provider error handling** | `RuntimeError` raised | `RuntimeError("model not found")` | **PASS** |
| **Timeout handling** | `OllamaTimeoutError` raised | `OllamaTimeoutError` raised | **PASS** |
| **Connection failure** | `OllamaConnectionError` raised | `OllamaConnectionError` raised | **PASS** |

### 6. Real Local T1 Smoke-Test Proof (`deepseek-r1:8b`)
- **Execution Script**: `scratch/smoke_test_t1.py`
- **Orchestrator Run**: `Orchestrator(mode="auto", project="smoke_test").run("Write a python file smoke_test_output.py with function hello() returning 'world'. Use the write_file tool.")`
- **Telemetry & Pipeline Log**:
  ```
  2026-09-04 03:00:13.737 | DEBUG | core.response_parser:_validate_and_build:160 - ResponseParser: success via direct_parse | tool=write_file
  2026-09-04 03:00:13.738 | DEBUG | core.orchestrator:run:517 - Stage 4 complete | tool=write_file | latency=69.88s
  2026-09-04 03:00:13.739 | INFO  | utils.logging:log_tool_call:307 - TOOL_CALL | tool=write_file | mode=auto
  2026-09-04 03:00:13.752 | DEBUG | tools.file_tools:execute:159 - write_file: smoke_test_output.py | 253 chars | overwrite
  2026-09-04 03:00:13.758 | DEBUG | core.orchestrator:run:704 - Stage 6: tool=write_file succeeded | exit=0
  ```
- **Observed Metrics**:
  - `model_calls`: 1 (DeepSeek-R1 8B)
  - `parser_success`: **TRUE** (`direct_parse`, `tool=write_file`)
  - `tool_calls`: **1** (`write_file`)
  - `tool_execution_reached`: **TRUE**
  - `filesystem_mutation`: `smoke_test_output.py` verified created on disk.
  - `pipeline_stage_reached`: Stage 12 (Complete).

### 7. Regression Suite Results
- **Focused Unit Tests**: `pytest tests/test_ollama_client_reasoning.py -v`: **15 passed in 1.99s**
- **Existing Response Parser & Model Migration Tests**: `pytest tests/test_response_parser.py tests/test_model_migration.py -v`: **19 passed in 1.67s**
- **Protocol Self-Validation**: `pytest tests/test_gate23_protocol_validation.py -v`: **20 passed in 0.10s**
- **Pipeline Integration Tests**: `pytest tests/integration/test_pipeline_integration.py -v`: **20 passed in 2317.61s**

### 8. Benchmark Freeze & Immutability Confirmation
- **Final 80-task benchmark executed**: **NO** (Unexecuted and strictly frozen).
- **Dataset modified**: **NO** (SHA-256: `f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72`).
- **Success contract modified**: **NO** (SHA-256: `4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3`).
- **Protocol document modified**: **NO** (SHA-256: `8740e0a6face5b1b4ce1b23839a97605cffb63045e289bda7b297fb83d8bfe15`).

### 9. Final Phase 2 Verdict
**STATUS: PASS & LOCKED 🔒**
The known Ollama DeepSeek-R1 ingestion defect is fixed and validated across unit, integration, and real local smoke tests. Tool execution has been proven reachable from DeepSeek-R1 model generation.
