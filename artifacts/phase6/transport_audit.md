# HERMES Phase 6: Model Transport, Streaming, Retry & Circuit-Breaker Audit

## 1. Audit Findings in Baseline Implementation
Prior to Phase 6 hardening, the transport layers exhibited the following risks:
1. **Unbounded Client Re-creation / Leakage:**
   - Both `NvidiaClient._get_client()` and `OllamaClient._get_client()` maintained single private instance variables without connection lifecycle integration with the central FastAPI server or service lifespan.
2. **Streaming Protocol Ambiguity:**
   - SSE streaming in `NvidiaClient` allowed completing streams on read timeouts if partial chunks had been received, which could treat incomplete assistant responses or unfinished tool call arguments as valid actions.
   - Ollama streams lacked strict verification of the `{"done": true}` terminal marker.
3. **Absence of Shared Circuit Breaker & Retry Coordinator:**
   - Ad-hoc retries in client loops risked multiplication across layers, and authentication/billing errors could trigger retries rather than failing fast.
   - User Stop signals (Phase 4) did not cleanly short-circuit retry delays across tiers.

## 2. Hardened Architecture Implemented
1. **`core/transport/types.py`:**
   - Typed `ErrorCategory` taxonomy (23 explicit categories).
   - Sanitized `StructuredTransportError` guaranteeing API keys, bearer tokens, and secrets are strictly redacted from exception messages and telemetry.
   - Deterministic HTTP status classifier (`classify_http_status`).
2. **`core/transport/client_manager.py`:**
   - Pooled connection management via `TransportClientManager`.
   - Shared client reuse across requests without inter-mission leakage.
   - Graceful shutdown lifecycle hook registered in FastAPI `lifespan`.
3. **`core/transport/stream_validator.py`:**
   - `SseStreamAccumulator` enforcing explicit `[DONE]` terminal marker and complete JSON tool call arguments.
   - `OllamaStreamAccumulator` enforcing terminal `{"done": true}` marker.
   - Strict rejection of incomplete streams (`STREAM_INCOMPLETE`).
4. **`core/transport/circuit_breaker.py`:**
   - Concurrency-safe, route-keyed (`provider:model`) three-state circuit breaker (`CLOSED` -> `OPEN` -> `HALF_OPEN`).
   - Configuration-failure suppression (`config_blocked`) preventing retry storms on invalid credentials or billing restrictions.
   - Phase 4 Stop cancellation isolation: user cancellations never count towards provider failure thresholds.
5. **`core/transport/retry_coordinator.py`:**
   - Centralized coordination of bounded retries and explicit tier fallback (`T1` -> `T2` -> `T3`).
   - Monotonic overall request deadline tracking preventing unbounded waiting.
   - `Retry-After` adherence with exponential backoff and jitter.
   - Immediate abort on mission cancellation (`abort_event.is_set()`).
