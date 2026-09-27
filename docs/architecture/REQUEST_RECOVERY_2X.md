# REQUEST RECOVERY 2.x — BOUNDED ATTEMPTS & REPLAY SAFETY

## 1. Logical Request vs. Physical Attempt
HERMES 2.x decouples logical generation requests from physical network attempts:
- **Logical Request (`LogicalRequest`)**: Represents the semantic intention of an agent turn. Preserves prompt text, system prompt, accumulated outputs, and executed tool call references.
- **Physical Attempt (`RequestAttempt`)**: Represents an individual TCP connection or SSE stream attempt (`att_xxxxxxxx`). Tracks its own TTFT, deltas received, duration, and failure classification.

---

## 2. Failure Classification Matrix
All exceptions are mapped to canonical `FailureClassification`:

| Category | Classification | Retryable | Action |
| :--- | :--- | :--- | :--- |
| **Transport** | `CONNECT_TIMEOUT` | Yes | Fresh connection retry with backoff |
| **Transport** | `READ_TIMEOUT` | Yes | Retry / Fallback to non-streaming |
| **Transport** | `CONNECTION_RESET` | Yes | Pool recycle & fresh connection retry |
| **Transport** | `CONNECTION_REFUSED`| Yes | Bounded retry (max 3) |
| **Transport** | `DNS_ERROR` | No | Fast failure |
| **Streaming** | `STREAM_STALL` | Yes | Abort stalled stream, fallback or retry |
| **HTTP** | `HTTP_429` | Yes | Backoff retry with jitter |
| **HTTP** | `HTTP_5XX` | Yes | Server transient retry |
| **HTTP** | `AUTH_FAILURE` (401/403) | No | Fast failure, no retries |
| **HTTP** | `MODEL_NOT_FOUND` (404)| No | Fast failure, no retries |
| **HTTP** | `INVALID_REQUEST` (400)| No | Fast failure, no retries |
| **Control** | `CANCELLED` | No | Immediate abort |
| **Control** | `DEADLINE_EXCEEDED`| No | Budget exhausted, abort |

---

## 3. Fresh Connection Guarantee
Reusing a half-closed, poisoned, or timed-out socket causes silent hangs or socket-level protocol errors.
When retrying an attempt (`attempt_index > 1`), `NetworkSupervisor` explicitly calls `adapter.aclose()` to close the persistent HTTP connection pool and establish a fresh connection from scratch.

---

## 4. Non-Streaming Fallback
If streaming fails due to a network glitch, chunk decoding error, or provider proxy issue:
1. `NetworkSupervisor` switches `use_streaming = False`.
2. Emits `NETWORK_DEGRADED` event to inform TUI and reducer.
3. Dispatches next attempt via `execute_non_stream()`.
4. Successfully returns `NormalizedModelResponse` without user disruption.

---

## 5. Tool-Call Replay Safety
When a model stream breaks or retries after emitting partial tool calls:
1. `NetworkSupervisor.register_executed_tool_call(tool_call_id, turn_id)` tracks tool execution.
2. If a subsequent retry attempt yields the same tool call, `NetworkSupervisor` suppresses duplicate execution.
3. In `AgentLoop`, before executing any action, `is_tool_call_executed` verifies whether the tool has already executed. If so, a deduplication observation is recorded and physical tool execution is skipped.
