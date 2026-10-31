# HERMES PHASE 4 — MODEL TRANSPORT & NETWORK RESILIENCE
## Final Forensic Audit, Bounded Implementation, Recovery Verification & Acceptance Lock Report

---

## 1. Executive Summary and Phase Identity

- **Project:** HERMES
- **Phase:** 4
- **Name:** Model Transport and Network Resilience
- **Status:** **CLOSED / LOCKED**
- **Date & Timestamp:** 2026-10-21T14:48:30Z
- **Canonical Python Environment:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)
- **Repository Root:** `C:\Users\SUBBU\Downloads\hermes`
- **Model Stack Configuration (Preserved & Verified):**
  - **Tier 1:** NVIDIA NIM — `z-ai/glm-5.3-flash`
  - **Tier 2:** Ollama Cloud — `gpt-oss:120b-cloud`
  - **Tier 3:** Ollama Cloud — `nemotron-3-ultra:cloud`

HERMES Phase 4 has successfully hardened the model transport layer and network resilience across all three model tiers. The implementation addresses transport timeouts, midstream stream-stall truncation, classification of transient vs. permanent provider errors, circuit breaker state transitions, automatic tier fallback, durable network waiting (`WAITING_FOR_PROVIDER` and `WAITING_FOR_NETWORK`), autonomous recovery without global WAN toggling, user stop race handling, connection pool lifecycle, and idempotency guarantees preventing duplicate tool executions upon retry.

All 23 required acceptance scenarios (Scenarios A through W) have been proven passing across 9 dedicated test suites (29 tests, 100% pass rate). All historical transport suites (38 tests) and baseline regression suites for Phases 1, 2, and 3 (109 tests) remain 100% green with zero regressions. The frontend snapshot race suite and GUI production build completed cleanly with exit code 0.

---

## 2. Model Tier Timeout and Retry Policy Configuration

Each model tier operates under strict, tier-aware deadlines enforced via `core/transport/client_manager.py` and `core/transport/retry_coordinator.py`:

| Tier | Provider | Model | Connect Timeout | First Token Deadline | Stream Idle Timeout | Overall Deadline | Max Retries |
|---|---|---|---|---|---|---|---|
| **Tier 1** | `nvidia_nim` | `z-ai/glm-5.3-flash` | 5.0s | 12.0s | 8.0s | 60.0s | 3 |
| **Tier 2** | `ollama` | `gpt-oss:120b-cloud` | 8.0s | 25.0s | 15.0s | 120.0s | 3 |
| **Tier 3** | `ollama` | `nemotron-3-ultra:cloud` | 10.0s | 35.0s | 20.0s | 180.0s | 3 |

### Retry and Backoff Properties
- **Base delay:** 1.0 second.
- **Backoff multiplier:** 2.0x exponential backoff.
- **Maximum delay ceiling:** 30.0 seconds.
- **Jitter algorithm:** Full jitter (`random.uniform(0, current_delay)`) to prevent thundering herd behavior.
- **Retry-After header precedence:** When an HTTP 429 or 503 response includes a `Retry-After` header (in seconds), that duration supersedes the default exponential backoff calculation.
- **Overall request deadline budget:** Individual retries cannot exceed the configured tier overall deadline budget; attempts past the deadline are aborted immediately.

---

## 3. Error Classification and Redaction Taxonomy

Errors encountered at the HTTP transport or socket layer are structured and classified into deterministic categories (`core/transport/types.py`):

| HTTP / Socket Signal | Categorization | Retryable? | Behavior & Fallback Action |
|---|---|---|---|
| **HTTP 400** | `BAD_REQUEST` | No | Model prompt syntax or arguments malformed; fails immediately without retry. |
| **HTTP 401** | `AUTHENTICATION` | No | Invalid or missing API key; halts route, emits diagnostic, enters `WAITING_FOR_PROVIDER`. |
| **HTTP 402** | `BILLING` | No | Credit exhaustion or delinquent account; fails route immediately without retry. |
| **HTTP 403** | `PERMISSION / QUOTA_EXHAUSTED` | No | Account permission denied or quota exhausted; triggers fallback or enters waiting. |
| **HTTP 404** | `NOT_FOUND` | No | Model or endpoint does not exist on provider route. |
| **HTTP 408** | `TRANSIENT_TIMEOUT` | Yes | Request timeout; retries with exponential backoff up to tier retry budget. |
| **HTTP 429 (Rate Limit)** | `RATE_LIMIT` | Yes | Temporary concurrency limit; backs off with jitter or follows `Retry-After`. |
| **HTTP 429 (Quota Exhausted)** | `QUOTA_EXHAUSTED` | No | Distinguishes `"quota"` or `"credits"` keywords in response body; falls back to Tier 2/3. |
| **HTTP 500 / 502 / 504** | `SERVER_ERROR` | Yes | Transient upstream failure; retries within budget before escalating. |
| **HTTP 503** | `SERVICE_UNAVAILABLE` | Yes | Temporary overload; honors `Retry-After` or backs off. |
| **Connect Timeout** | `CONNECT_TIMEOUT` | Yes | Socket connection unreachable; counts towards circuit breaker failure threshold. |
| **Stream Idle Timeout** | `STREAM_STALL` | Yes | No token chunks received within idle window; resets accumulator and retries. |
| **Midstream Disconnect** | `STREAM_INCOMPLETE` | No (for chunk) | Stream truncated before `[DONE]` or `done: true`; partial tokens discarded. |
| **Malformed Tool JSON** | `TOOL_CALL_PARSE_ERROR`| No | Truncated tool arguments rejected before reaching dispatcher. |

### Secret Redaction Policy
All URLs, query parameters, header dumps, payload previews, and error logs are scrubbed via `core/transport/types.py:redact_secrets()`. Bearer tokens (`Bearer nvapi-...`, `nvapi-...`), authorization headers, and credential patterns are replaced with `[REDACTED_SECRET]` before persistence to event journals or broadcast to the GUI.

---

## 4. Stream Accumulation and Chunk Integrity

`core/transport/stream_validator.py` provides stream accumulators for both SSE (NVIDIA NIM) and NDJSON (Ollama):
- **SSE Stream Accumulator (`SseStreamAccumulator`):**
  - Accumulates delta chunks into text buffers.
  - Verifies presence of terminal `data: [DONE]`.
  - Rejects incomplete or truncated streams (`STREAM_INCOMPLETE`) if the connection terminates before `[DONE]`.
  - Validates tool call argument fragments; ensures complete, valid JSON syntax before emitting tool call requests.
- **NDJSON Stream Accumulator (`OllamaStreamAccumulator`):**
  - Parses successive newline-delimited JSON objects.
  - Requires `done: true` in final chunk to validate completion.
  - Discards intermediate tokens and raises structured errors if the stream ends prematurely.

---

## 5. Circuit Breaker & Multi-Tier Fallback

`core/transport/circuit_breaker.py` implements a route-isolated 3-state circuit breaker per `(provider, model)` pair:
- **State Machine:**
  - `CLOSED`: Normal operation.
  - `OPEN`: Triggered after **5 consecutive transport failures**. Incoming requests to this tier fail fast with `CIRCUIT_OPEN` for a **cooldown period of 30.0 seconds**.
  - `HALF_OPEN`: Once cooldown expires, allows 1 trial request through. Success transitions back to `CLOSED`; failure immediately re-opens the circuit for another cooldown.
- **Cancellation Isolation:**
  - Explicit user Stop requests, mission cancellations, and client-side aborts **do not** increment failure counters or trip circuit breakers.
- **Deterministic Multi-Tier Fallback:**
  - If Tier 1 fails 5 times and trips its circuit breaker, `core/transport/retry_coordinator.py` automatically routes the execution turn to Tier 2 (`gpt-oss:120b-cloud`).
  - If Tier 2 also exhausts retries or trips its breaker, execution routes to Tier 3 (`nemotron-3-ultra:cloud`).
  - If all three tiers are unavailable, the mission enters `WAITING_FOR_PROVIDER`.

---

## 6. Durable Waiting and Autonomous Recovery

- **`WAITING_FOR_PROVIDER` vs. `WAITING_FOR_NETWORK`:**
  - **`WAITING_FOR_PROVIDER`:** Entered when all configured model providers/tiers are unreachable, quota-exhausted, or reporting 5xx/429 outages.
  - **`WAITING_FOR_NETWORK`:** Entered when local environment prerequisites (e.g., package registry unreachable, socket binding failure, or network-bound tool blocker) prevent progress.
- **Local Provider Recovery without Global WAN Toggle:**
  - `core/network/coordinator.py` evaluates provider health independently via route probes.
  - When an individual provider recovers, missions blocked in `WAITING_FOR_PROVIDER` resume automatically without waiting for or requiring a global WAN state toggle.
- **Stop Control Race Invariant:**
  - If a user sends a Stop signal while a mission is in `WAITING_FOR_PROVIDER` or during an active recovery trial, the Stop signal is atomic and **always wins**. The mission transitions to `CANCELLED` and does not restart or replay.
- **Recovery Flapping Protection:**
  - Probes must observe stable connectivity across successive checks before declaring a route restored, preventing recovery flapping loops.

---

## 7. Execution Idempotency and Tool Call Deduplication

`core/network/supervisor.py` enforces end-to-end execution idempotency:
- When transport retries occur during a model turn, any previously generated tool calls or partial generations are indexed by tool execution fingerprint (`tool_name`, `arguments_hash`, `turn_index`).
- Physical file operations, bash commands, and workspace writes cannot be re-executed twice for the same logical step.
- Events are persisted to the durable WAL journal **prior** to broadcasting over SSE to the frontend, preventing ghost event states.

---

## 8. Detailed Scenario Verification Matrix (Scenarios A through W)

| Scenario | Description | Test Suite & Function | Verification Result |
|---|---|---|---|
| **A** | Connect timeout enforcement per tier | `tests/test_phase4_transport_timeouts.py::test_scenario_a_connect_timeout_enforced` | **PASSED** (Timed out at 5.0s, structured error emitted) |
| **B** | First token deadline enforcement | `tests/test_phase4_transport_timeouts.py::test_scenario_b_first_token_deadline_enforced` | **PASSED** (Aborted after 12.0s without first chunk) |
| **C** | Midstream stall detection | `tests/test_phase4_transport_timeouts.py::test_scenario_c_midstream_stall_detection` | **PASSED** (Stall detected after 8.0s idle window) |
| **D** | Overall request deadline | `tests/test_phase4_transport_timeouts.py::test_scenario_d_overall_request_deadline_enforced` | **PASSED** (Exceeded 60.0s tier budget, halted cleanly) |
| **E** | Transient retry with backoff and Retry-After | `tests/test_phase4_retry_backoff.py::test_scenario_e_transient_error_retry_and_backoff` | **PASSED** (3 retries with jitter, Retry-After honored) |
| **F** | HTTP 401 immediate non-retryable failure | `tests/test_phase4_transport_error_classification.py::test_scenario_f_http_401_fails_immediately` | **PASSED** (No retries, AUTHENTICATION error) |
| **G** | HTTP 402/403 permanent error classification | `tests/test_phase4_transport_error_classification.py::test_scenario_g_http_402_and_403_non_retryable` | **PASSED** (Immediate halt, BILLING/PERMISSION classified) |
| **H** | HTTP 429 rate limit vs. quota differentiation | `tests/test_phase4_transport_error_classification.py::test_scenario_h_rate_limit_vs_quota_exhausted_classification` | **PASSED** (Rate limit retried; quota exhaustion falls back) |
| **I** | Truncated stream token discarding | `tests/test_phase4_stream_integrity.py::test_scenario_i_truncated_stream_discarded` | **PASSED** (Incomplete SSE tokens discarded, error raised) |
| **J** | Malformed tool call JSON rejection | `tests/test_phase4_stream_integrity.py::test_scenario_j_malformed_tool_call_json_rejected` | **PASSED** (Malformed arguments caught prior to tool exec) |
| **K** | Circuit breaker 5-failure trip and half-open | `tests/test_phase4_circuit_breaker_fallback.py::test_scenario_k_circuit_breaker_5_failures_open_and_half_open` | **PASSED** (CLOSED -> OPEN after 5, HALF_OPEN on cooldown) |
| **L** | Explicit Tier 1 to Tier 2 fallback | `tests/test_phase4_circuit_breaker_fallback.py::test_scenario_l_explicit_tier1_to_tier2_fallback` | **PASSED** (T1 OPEN routes seamlessly to T2) |
| **M** | All tiers failing enters WAITING_FOR_PROVIDER | `tests/test_phase4_network_waiting.py::test_scenario_m_all_tiers_failing_enters_waiting_for_provider` | **PASSED** (Tiers 1, 2, 3 exhausted -> WAITING_FOR_PROVIDER) |
| **N** | Provider recovery without WAN toggle | `tests/test_phase4_provider_recovery.py::test_scenario_n_provider_recovery_without_global_wan_toggle` | **PASSED** (Individual route probe restores mission) |
| **O** | User stop wins race against recovery | `tests/test_phase4_provider_recovery.py::test_scenario_o_user_stop_wins_recovery_race` | **PASSED** (Stop event supersedes recovery; stays CANCELLED) |
| **P** | Recovery flap deduplication | `tests/test_phase4_provider_recovery.py::test_scenario_p_recovery_flap_deduplication` | **PASSED** (Intermittent flap does not cycle attempts) |
| **Q** | Cold restart recovery classification | `tests/test_phase4_transport_end_to_end.py::test_scenario_q_cold_restart_recovery_classification` | **PASSED** (Restarts into WAITING_FOR_PROVIDER safely) |
| **R** | Recoverable workspace blocker waiting | `tests/test_phase4_network_waiting.py::test_scenario_r_recoverable_workspace_blocker_enters_waiting_for_network` | **PASSED** (Enters WAITING_FOR_NETWORK truthfully) |
| **S** | Probing security TLS and captive portal | `tests/test_phase4_transport_end_to_end.py::test_scenario_s_probing_security_tls_and_captive_portal` | **PASSED** (Captive portal redirect rejected) |
| **T** | Client reuse and connection pool lifecycle | `tests/test_phase4_client_lifecycle.py::test_scenario_t_client_reuse_and_preservation` | **PASSED** (Same httpx client reused across turns) |
| **U** | No duplicate tool execution on retry | `tests/test_phase4_transport_end_to_end.py::test_scenario_u_no_duplicate_tool_execution_on_transport_retry` | **PASSED** (Tool supervisor drops duplicate invocations) |
| **V** | Credential and key redaction | `tests/test_phase4_transport_error_classification.py::test_scenario_v_credential_and_key_redaction` | **PASSED** (API tokens sanitized to [REDACTED_SECRET]) |
| **W** | Truthful events broadcast contract | `tests/test_phase4_transport_end_to_end.py::test_scenario_w_truthful_events_persisted_before_broadcast` | **PASSED** (Persistence before SSE broadcast verified) |

---

## 9. Comprehensive Verification and Regression Results

### 9.1 Phase 4 Dedicated Test Suites (29 / 29 PASSED - 100%)
- `tests/test_phase4_transport_timeouts.py`: **4 passed** (Scenarios A, B, C, D)
- `tests/test_phase4_transport_error_classification.py`: **5 passed** (Scenarios F, G, H, V)
- `tests/test_phase4_stream_integrity.py`: **3 passed** (Scenarios I, J)
- `tests/test_phase4_retry_backoff.py`: **3 passed** (Scenario E)
- `tests/test_phase4_circuit_breaker_fallback.py`: **3 passed** (Scenarios K, L)
- `tests/test_phase4_network_waiting.py`: **2 passed** (Scenarios M, R)
- `tests/test_phase4_provider_recovery.py`: **3 passed** (Scenarios N, O, P)
- `tests/test_phase4_client_lifecycle.py`: **2 passed** (Scenario T)
- `tests/test_phase4_transport_end_to_end.py`: **4 passed** (Scenarios Q, S, U, W)

### 9.2 Historical Transport Suites (38 / 38 PASSED - 100%)
- `tests/test_phase6_transport_hardening.py`: **16 passed**
- `tests/test_phase7_network_recovery.py`: **15 passed**
- `tests/test_phase10_network_and_provider_faults.py`: **7 passed**

### 9.3 Locked Baseline Regressions (109 / 109 PASSED - 100%)
- **Phase 1 Baseline:** **26 passed** (`test_phase1_gap_b_event_history_refresh.py`, `test_phase1_gap_c_hidden_directory_safety.py`, `test_phase1_gap_d_runtime_identity.py`, `test_phase1_greenfield_end_to_end.py`, `test_phase1_mission_lifecycle.py`)
- **Phase 2 Baseline:** **65 passed** (`test_phase2_complete.py`, `test_phase2_concurrency.py`, `test_phase2_core_runtime_repair.py`, `test_phase2_durable_persistence.py`, `test_phase2_golden_scenarios.py`, `test_phase2_gui_lifecycle.py`, `test_phase2_mission_lifecycle.py`, `test_phase2_restart_recovery.py`, `test_phase2_stale_worker_fencing.py`, `test_phase2_stop_safety.py`, `test_phase2_wal_integrity.py`, `test_phase2_workspace_reconciliation.py`)
- **Phase 3 Baseline:** **18 passed** (`test_phase3_attempt_snapshot_fencing.py`, `test_phase3_controlled_e2e_mission.py`, `test_phase3_event_contract.py`, `test_phase3_event_history_replay.py`, `test_phase3_event_persistence_order.py`, `test_phase3_execution_activity_events.py`, `test_phase3_no_fake_progress.py`, `test_phase3_sse_reconnect.py`)

### 9.4 Frontend Verification
- `node gui/test_snapshot_race.mjs`: **5/5 PASSED** (Proving delayed snapshot rejection, attempt fencing, deduplication, isolation, and event reconciliation)
- `npm --prefix gui run build`: **PASSED** (`tsc && vite build` built in 6.17s, exit 0)

---

## 10. Formal Gate Sign-Off Matrix

| Gate | Identity & Description | Audit Criterion | Sign-Off Status |
|---|---|---|---|
| **Gate A** | Timeout Precision | Granular timeouts (connect, first token, stream idle, overall) enforced per tier | **SIGNED_OFF** |
| **Gate B** | Classification Accuracy | Deterministic separation of transient vs permanent (401/402/403/429-quota) errors | **SIGNED_OFF** |
| **Gate C** | Streaming Integrity | Discarding partial tokens upon disconnect; rejection of malformed tool JSON | **SIGNED_OFF** |
| **Gate D** | Retry & Circuit Breaker Discipline | 5-failure threshold, cooldown, half-open trial, cancellation immunity, tier fallback | **SIGNED_OFF** |
| **Gate E** | Durable Waiting Semantics | Correct `WAITING_FOR_PROVIDER` and `WAITING_FOR_NETWORK` lifecycle states | **SIGNED_OFF** |
| **Gate F** | Autonomous Recovery Honesty | Resumes without WAN toggle; user Stop wins race; flap dampening enforced | **SIGNED_OFF** |
| **Gate G** | Execution Idempotency | No duplicate physical tool calls on transport retry; WAL persistence before broadcast | **SIGNED_OFF** |
| **Gate H** | Security & Credential Safety | Secrets redacted in all logs, payloads, events, and errors; TLS validation enforced | **SIGNED_OFF** |
| **Gate I** | Baseline Regression Zero Defects | 100% pass across Phases 1, 2, and 3 regression suites and frontend production build | **SIGNED_OFF** |

---

## 11. Acceptance Lock Confirmation

HERMES Phase 4: Model Transport and Network Resilience has satisfied all verification gates, contractual constraints, and acceptance criteria. All tests execute deterministically against the canonical Python 3.12.0 virtual environment with no reliance on unpinned external state or destructive operations.

Phase 4 is hereby **FORMALLY CLOSED AND LOCKED**.
